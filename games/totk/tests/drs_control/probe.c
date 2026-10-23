// runtime/drs_control.h (TOTK_DRS): the automatic resolution controller against a simulated game. Per frame the GPU needs
// fixed + pixels * scale^2 ms (noise optional); its time reaches the controller 9 presents late, as nvn_gpu_frame_ms gives
// it, and a new scale is in force two frames after the decision. The present interval is the cap or the slower of CPU and
// GPU. Checks: the level it settles on, how fast, that it stays there (no oscillation), recovery, the minimum, a CPU-bound
// game, a GPU that clocks down when it has time (probes), the interval fallback, a live minimum change. Negative control:
// samples twice as late as the controller allows for must make it overshoot, which the level check must see.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "drs_control.h"

static int failures, checked;
static void check(int ok, const char *what) { checked++; if (!ok) { failures++; fprintf(stderr, "FAIL: %s\n", what); } }

typedef struct {
    float fixed, pixels;    /* GPU ms: fixed + pixels * s^2 at the GPU's full clock */
    float noise;            /* +- share, uniform */
    float cpu_ms;           /* the CPU's frame time (0: none) */
    float cap_ms;           /* the frame-rate cap's interval (0: uncapped) */
    float dvfs;             /* > 0: the GPU clocks down to keep this share of the interval busy (its time reads at least that) */
    int no_gpu;             /* no GPU times: the controller falls back to the interval */
    int lag;                /* presents between a frame and its GPU time reaching the controller (9 in the game) */
    float cliff_at, cliff_ms;   /* above this scale the GPU needs cliff_ms more (a cache that stops fitting) */
} Plant;

enum { MAXF = 60 * 240 };
typedef struct { DrsCtl c; float scale_at[MAXF]; float gpu_at[MAXF]; int frame; double now; unsigned changes; float lowest; } Sim;
static unsigned rng = 12345;
static float frand(void) { rng = rng * 1103515245u + 12345u; return (float)((rng >> 8) & 0xffff) / 65535.0f; }

static void sim_start(Sim *s, float min) { drs_reset(&s->c, min, 0); s->frame = 0; s->now = 0; s->changes = 0; s->lowest = 1; }

/* Runs `seconds` of frames against plant p; returns the changes made. */
static unsigned run(Sim *s, const Plant *p, double seconds, float target) {
    unsigned before = s->changes; double end = s->now + seconds;
    while (s->now < end && s->frame + 4 < MAXF) {
        int f = s->frame;
        float sc = s->c.level[s->c.cur];
        s->scale_at[f + 2] = sc;   /* decided now, in force two frames later */
        float scale = f >= 2 && s->scale_at[f] > 0 ? s->scale_at[f] : 1.0f;
        float g = (p->fixed + p->pixels * scale * scale + (p->cliff_ms > 0 && scale > p->cliff_at ? p->cliff_ms : 0)) * (1.0f + p->noise * (2.0f * frand() - 1.0f));
        float iv = g; if (p->cpu_ms > iv) iv = p->cpu_ms; if (p->cap_ms > iv) iv = p->cap_ms;
        float shown = p->dvfs > 0 && g < p->dvfs * iv ? p->dvfs * iv : g;
        s->gpu_at[f] = shown;
        s->now += iv / 1000.0;
        int lagged = f - p->lag, got = !p->no_gpu && lagged >= 0;
        if (drs_step(&s->c, target, got, got ? (uint32_t)lagged + 100 : 0, got ? s->gpu_at[lagged] : 0, f ? iv : -1, s->now)) s->changes++;
        if (s->c.level[s->c.cur] < s->lowest) s->lowest = s->c.level[s->c.cur];
        s->frame++;
    }
    return s->changes - before;
}
static float scale(const Sim *s) { return s->c.level[s->c.cur]; }
static int near(float a, float b) { return fabsf(a - b) < 0.001f; }

int main(void) {
    static Sim s;
    const float T = 16.6f;
    char what[256];

    // Levels: 1.0 down to the minimum in 5 % steps; the minimum is a level; 0.5 is the lowest.
    sim_start(&s, 0.67f);
    check(s.c.nlevel == 8 && near(s.c.level[0], 1) && near(s.c.level[6], 0.70f) && near(s.c.level[7], 0.67f), "levels 1.0 .. 0.70, 0.67");
    drs_levels(&s.c, 0.2f);
    check(s.c.nlevel == 11 && near(s.c.level[10], 0.5f), "minimum clamped to 0.5: 11 levels");
    drs_levels(&s.c, 1.0f);
    check(s.c.nlevel == 1 && near(s.c.level[0], 1), "minimum 1.0: one level");
    drs_levels(&s.c, 0.68f);
    check(near(s.c.level[s.c.nlevel - 2], 0.75f) && near(s.c.level[s.c.nlevel - 1], 0.68f), "a level closer to the minimum than half a step gives way to it");

    // GPU-bound at 1.0 (20 ms: the user's 1440p + TAA at 50 fps): settles at 0.80, the highest level below 93 % of T
    // (0.85 needs 15.56 ms > 15.44), within two seconds, and stays there for a minute.
    sim_start(&s, 0.67f);
    Plant heavy = {4, 16, 0.03f, 0, 0, 0, 0, 9, 0, 0};
    run(&s, &heavy, 2.0, T);
    snprintf(what, sizeof what, "GPU-bound 20 ms: at 0.80 after 2 s (got %.2f)", scale(&s)); check(near(scale(&s), 0.80f), what);
    unsigned ch = run(&s, &heavy, 60, T);
    snprintf(what, sizeof what, "GPU-bound: no change in the next minute (%u)", ch); check(ch == 0 && near(scale(&s), 0.80f), what);
    check(s.c.downs >= 1 && s.c.downs <= 2, "GPU-bound: one or two reductions to get there (at most 3 levels each)");

    // Noisy (+-10 %) and capped at 60: still one level, at most a couple of moves a minute after settling.
    sim_start(&s, 0.67f);
    Plant noisy = {4, 16, 0.10f, 0, 16.67f, 0, 0, 9, 0, 0};
    run(&s, &noisy, 5, T);
    ch = run(&s, &noisy, 60, T);
    snprintf(what, sizeof what, "noisy and capped: at most 2 changes a minute (%u) around 0.75-0.80 (%.2f)", ch, scale(&s));
    check(ch <= 2 && scale(&s) >= 0.749f && scale(&s) <= 0.801f, what);

    // Light (9 ms): stays at full scale, nothing changes.
    sim_start(&s, 0.67f);
    Plant light = {3, 6, 0.05f, 0, 0, 0, 0, 9, 0, 0};
    ch = run(&s, &light, 30, T);
    check(ch == 0 && near(scale(&s), 1), "light: 1.0, no change");

    // Light -> heavy -> light: down within 1.5 s, back to 1.0 within 20 s.
    double t0 = s.now; run(&s, &heavy, 1.5, T); (void)t0;
    snprintf(what, sizeof what, "load step: below 0.85 within 1.5 s (%.2f)", scale(&s)); check(scale(&s) < 0.851f, what);
    run(&s, &heavy, 10, T);
    run(&s, &light, 20, T);
    snprintf(what, sizeof what, "load gone: back at 1.0 within 20 s (%.2f)", scale(&s)); check(near(scale(&s), 1), what);

    // Far too heavy (40 ms): the minimum, and it stays there.
    sim_start(&s, 0.67f);
    Plant huge = {8, 32, 0.03f, 0, 0, 0, 0, 9, 0, 0};
    run(&s, &huge, 3, T);
    ch = run(&s, &huge, 30, T);
    check(near(scale(&s), 0.67f) && ch == 0, "40 ms: the minimum 0.67, steady");

    // CPU-bound (20 ms frames, GPU at 9 ms): frames miss, but the GPU is not why: no reduction.
    sim_start(&s, 0.67f);
    Plant cpu = {3, 6, 0.05f, 20, 0, 0, 0, 9, 0, 0};
    ch = run(&s, &cpu, 30, T);
    check(ch == 0 && near(scale(&s), 1), "CPU-bound: stays at 1.0");

    // GPU that clocks down (capped at 60, the time reads at least 80 % of the interval): from a low level the plain
    // prediction (0.8 T x 1.13 > 0.85 T) never allows a step up; the probes climb back, one level per 8 s.
    sim_start(&s, 0.67f);
    run(&s, &huge, 3, T);
    Plant dvfs = {3, 6, 0.03f, 0, 16.67f, 0.8f, 0, 9, 0, 0};
    run(&s, &dvfs, 70, T);
    snprintf(what, sizeof what, "clocked-down GPU: probes reach 1.0 within 70 s (%.2f, %u probes, %u failed)", scale(&s), s.c.probes, s.c.failed);
    check(near(scale(&s), 1) && s.c.probes >= 4 && s.c.failed == 0, what);

    // Probes that fail back off: capped, the GPU clocked down at 0.85 (true 13.1 ms reads 13.3), but above 0.875 a cliff
    // (+1.5 ms) puts 0.90 at 15.8 ms, over 93 %. Every probe to 0.90 is undone, back to 0.85 (not lower), and they thin out.
    sim_start(&s, 0.67f);
    Plant edge = {3, 14, 0.02f, 0, 16.67f, 0.8f, 0, 9, 0.875f, 1.5f};
    run(&s, &edge, 5, T);
    unsigned p0 = s.c.probes; s.lowest = 1;
    run(&s, &edge, 180, T);
    snprintf(what, sizeof what, "failed probes back off: %u in 3 minutes (%u failed), never below 0.85 (%.2f), at %.2f", s.c.probes - p0, s.c.failed, s.lowest, scale(&s));
    check(s.c.probes - p0 >= 2 && s.c.probes - p0 <= 5 && s.c.failed >= 2 && s.lowest > 0.849f && scale(&s) >= 0.849f && scale(&s) <= 0.901f, what);

    // No GPU times: the interval stands in. Uncapped and GPU-bound, it lowers until the frames are on time.
    sim_start(&s, 0.67f);
    Plant blind = {4, 16, 0.03f, 0, 0, 0, 1, 9, 0, 0};
    run(&s, &blind, 10, T);
    snprintf(what, sizeof what, "no GPU time: the interval brings it to 0.85 or below (%.2f, fallback %d)", scale(&s), s.c.fallback);
    check(scale(&s) <= 0.851f && s.c.fallback, what);

    // A live minimum change while lower: the level in force moves up to the new minimum.
    sim_start(&s, 0.67f);
    run(&s, &huge, 3, T);
    drs_levels(&s.c, 0.8f);
    check(near(scale(&s), 0.8f), "minimum raised to 0.8 while at 0.67: 0.8");

    // Negative control: GPU times 30 presents late (the controller allows for 12) make it decide on old samples and
    // overshoot below 0.80; the level check above must catch that.
    sim_start(&s, 0.67f);
    Plant late = heavy; late.lag = 30;
    run(&s, &late, 3, T);
    int caught = !near(scale(&s), 0.80f);
    check(caught, "negative control: samples 30 presents late overshoot (the level check sees it)");

    // Non-finite timings must not poison the median or cause a scale decision.
    sim_start(&s, 0.67f);
    for (unsigned i = 0; i < 100; i++) drs_step(&s.c, T, 1, i, INFINITY, NAN, i / 60.0);
    check(near(scale(&s), 1) && s.c.ngpu == 0 && s.c.niv == 0, "invalid timings ignored");
    check(near(drs_clamp_min(NAN), 0.67f), "NaN minimum uses default");

    printf("{\"probe\":\"drs_control\",\"checked\":%d,\"failures\":%d}\n", checked, failures);
    return failures ? 1 : 0;
}
