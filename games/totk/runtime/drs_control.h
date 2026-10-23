/* The controller of the automatic resolution (TOTK_DRS, runtime/game_patches_v143.c) without the runtime, so
   tests/drs_control/probe.c can drive it with made-up frame times. Once per presented frame it takes the newest GPU time
   (gfx/nvn/hle_nvn.c nvn_gpu_frame_ms: the command buffers' GPU time of one game frame, read 8 presents late once
   complete) and the present interval, and picks the scale (both axes) the game's renderer uses for its scene.

   The scale moves between levels, not continuously: the game sizes its scene targets from the scale every frame
   (main+0xd5c24, rounded to 8 pixels), so every scale is another set of texture sizes, and MetalFX TAA (totk_taa.m)
   builds a new scaler and drops its history at every size it has not got. Few sizes, rare changes.

   Constants (shares of the frame-time target T: 16.7 ms, 1000 / the FPS cap, or TOTK_DRS_TARGET_MS):
   DRS_STEP       5 % of each axis between levels (about 10 % of the pixels), from 1.0 down to the minimum, which is a
                  level itself (TOTK_DRS_MIN, 0.67 by default: 2560x1440 -> 1715x965; 8 levels, 11 at 0.5).
   DRS_WIN        15 frames in the moving windows (a quarter of a second at 60 fps), judged by their median, so a single
                  long frame (a shader compile, streaming) does not move the scale.
   DRS_SETTLE     GPU frames after a change that may still show the old scale (8 presents late, plus margin); only
                  samples after them count, and DRS_FRESH (10) of them are needed before the next decision.
   DRS_DOWN_AT    0.93: GPU median above 93 % of T -> lower. A GPU this busy drops frames at the next spike.
   DRS_AIM        0.88: a reduction goes to the highest level whose predicted GPU time is within 88 % of T, at most
                  DRS_MAX_DOWN (3) levels at once. Prediction: GPU time ~ scale^2. Work that does not shrink with the
                  scene (shadow maps, UI, the output upscale) makes the real drop smaller than predicted, so a reduction
                  errs towards too little and the next decision finishes it (about 0.4 s later).
   DRS_MISS       1.2: an interval that long missed the target. A third of the window missed with the GPU above
                  DRS_MISS_GPU (85 %) also lowers the scale: GPU work outside the per-frame time (the present's MetalFX
                  upscale, frame interpolation) can still make frames late. Not while the median interval is above
                  DRS_PACED (1.25 T): the game then runs at a lower rate on purpose (30+30 interpolation, a loading screen).
   DRS_UP_AT      0.85: one level up when its predicted GPU time is within 85 % of T and no frame in the window missed,
                  held for DRS_UP_HOLD_S (1 s), the last change at least DRS_UP_DWELL_S (2 s) ago. The landing point
                  (at most 85 %) and the point that lowers it again (93 %) leave a hysteresis band of 8 % of T, more than
                  the step itself changes once the part that does not shrink is counted.
   Probe          Apple GPUs clock down when they have time to spare, so with a frame-rate cap the GPU time stays high
                  and the prediction may never allow the step up. After DRS_PROBE_S (8 s) at a level, one level up is
                  tried when its predicted GPU time has stayed below DRS_DOWN_AT with nothing missed for DRS_PROBE_HOLD_S
                  (2 s). A reduction within DRS_PROBE_FAIL_S (4 s) is a failed probe: back to the level it left (which
                  held), and the wait doubles (at most DRS_PROBE_MAX_S, 64 s); a probe that holds resets the wait. At
                  worst one failed probe a minute.
   Fallback       no GPU time for DRS_GPU_STALE (60) frames: the median interval stands in for it (lower above
                  DRS_FB_DOWN_AT, 1.05 T; up as above; no probes). Under a cap the interval cannot show headroom, so the
                  scale then only goes down. */
#pragma once
#include <stdint.h>
#include <math.h>
#include <string.h>

enum { DRS_LEVELS = 12, DRS_WIN = 15, DRS_FRESH = 10, DRS_MAX_DOWN = 3, DRS_SETTLE = 12, DRS_SETTLE_IV = 8, DRS_GPU_STALE = 60 };
#define DRS_STEP 0.05f
#define DRS_MIN_DEFAULT 0.67f
#define DRS_MIN_LOWEST 0.5f
#define DRS_DOWN_AT 0.93f
#define DRS_AIM 0.88f
#define DRS_UP_AT 0.85f
#define DRS_MISS 1.2f
#define DRS_MISS_GPU 0.85f
#define DRS_PACED 1.25f
#define DRS_FB_DOWN_AT 1.05f
#define DRS_UP_DWELL_S 2.0
#define DRS_UP_HOLD_S 1.0
#define DRS_PROBE_S 8.0
#define DRS_PROBE_HOLD_S 2.0
#define DRS_PROBE_MAX_S 64.0
#define DRS_PROBE_FAIL_S 4.0

typedef struct {
    float level[DRS_LEVELS], min; int nlevel, cur;   /* scales from 1.0 down to min; cur: the one in force */
    float gpu[DRS_WIN], iv[DRS_WIN]; int ngpu, igpu, niv, iiv;   /* samples since the last change (ring buffers) */
    uint32_t gpu_frame, settle_frame; int have_frame, have_settle, skip_gpu, skip_iv, since_gpu;
    double changed_at, up_since, probe_since, probe_at, probe_wait;   /* seconds; < 0: not running */
    int probe_from;                                  /* the level a probe in flight left */
    unsigned downs, ups, probes, failed;
    float g, ivm; int miss, fallback;   /* the last decision's inputs (GPU or stand-in median, interval median, missed), for the log */
} DrsCtl;

static inline float drs_clamp_min(float m) { return m >= DRS_MIN_LOWEST && m <= 1.0f ? m : m > 1.0f ? 1.0f : m < DRS_MIN_LOWEST ? DRS_MIN_LOWEST : DRS_MIN_DEFAULT; }   /* NaN: the default */

/* The levels for minimum min; the level in force becomes the lowest one at or above the scale it had. */
static inline void drs_levels(DrsCtl *c, float min) {
    float was = c->nlevel ? c->level[c->cur] : 1.0f;
    c->min = min = drs_clamp_min(min); c->nlevel = 0;
    for (int i = 0; i < DRS_LEVELS; i++) {
        float s = 1.0f - DRS_STEP * (float)i;
        if (s < min + 0.5f * DRS_STEP - 0.001f) break;   /* closer to the minimum than half a step: the minimum takes its place */
        c->level[c->nlevel++] = s;
    }
    if (c->nlevel < DRS_LEVELS && (!c->nlevel || c->level[c->nlevel - 1] > min)) c->level[c->nlevel++] = min;
    c->cur = 0;
    while (c->cur + 1 < c->nlevel && c->level[c->cur + 1] >= was - 0.001f) c->cur++;
}

static inline void drs_clear(DrsCtl *c) { c->ngpu = c->igpu = c->niv = c->iiv = 0; }

/* After a change (and at the start): samples that may still show the old scale are skipped. */
static inline void drs_settle(DrsCtl *c) {
    drs_clear(c);
    c->have_settle = c->have_frame; c->settle_frame = c->gpu_frame + DRS_SETTLE;
    c->skip_gpu = c->have_frame ? 0 : DRS_SETTLE;   /* no GPU frame number seen yet: count samples instead */
    c->skip_iv = DRS_SETTLE_IV;
}

/* Full scale, nothing measured yet (switched on). */
static inline void drs_reset(DrsCtl *c, float min, double now) {
    memset(c, 0, sizeof *c);
    drs_levels(c, min); c->cur = 0;
    c->changed_at = now; c->up_since = c->probe_since = c->probe_at = -1; c->probe_wait = DRS_PROBE_S;
    drs_settle(c);
}

/* A pause (no presents for a while, the clock jumped): the windows start again; the scale and the timers stay. */
static inline void drs_pause(DrsCtl *c) { drs_clear(c); c->up_since = c->probe_since = -1; }

static inline float drs_median(const float *v, int n) {
    float s[DRS_WIN];
    if (n > DRS_WIN) n = DRS_WIN;
    for (int i = 0; i < n; i++) {   /* insertion sort: at most 15 values */
        float x = v[i]; int j = i;
        while (j > 0 && s[j - 1] > x) { s[j] = s[j - 1]; j--; }
        s[j] = x;
    }
    return n ? (n & 1 ? s[n / 2] : 0.5f * (s[n / 2 - 1] + s[n / 2])) : -1;
}

static inline int drs_move(DrsCtl *c, int to, double now) {
    c->cur = to; c->changed_at = now; c->up_since = c->probe_since = -1;
    drs_settle(c);
    return 1;
}

/* One presented frame. gpu_new: a GPU time arrived (gpu_ms of game frame gpu_frame, numbers increasing); iv_ms: the
   present interval, < 0 for none (the first frame; after a pause, call drs_pause instead). target_ms: T. now: seconds.
   Returns 1 when c->cur changed: the caller then puts c->level[c->cur] in force. */
static inline int drs_step(DrsCtl *c, float target_ms, int gpu_new, uint32_t gpu_frame, float gpu_ms, float iv_ms, double now) {
    const float T = target_ms;
    if (gpu_new && isfinite(gpu_ms) && gpu_ms > 0) {
        c->gpu_frame = gpu_frame; c->since_gpu = 0;
        if (!c->have_frame) { c->have_frame = 1; if (!c->have_settle && c->skip_gpu) { c->have_settle = 1; c->settle_frame = gpu_frame + c->skip_gpu; c->skip_gpu = 0; } }
        if (c->have_settle && (int32_t)(gpu_frame - c->settle_frame) <= 0) {}   /* may still be the old scale */
        else if (gpu_ms > 0) { c->gpu[c->igpu] = gpu_ms; c->igpu = (c->igpu + 1) % DRS_WIN; if (c->ngpu < DRS_WIN) c->ngpu++; }
    } else if (c->since_gpu <= DRS_GPU_STALE) c->since_gpu++;
    if (isfinite(iv_ms) && iv_ms > 0) {
        if (c->skip_iv > 0) c->skip_iv--;   /* the first presents after a change (a new TAA scaler is built there) */
        else { c->iv[c->iiv] = iv_ms; c->iiv = (c->iiv + 1) % DRS_WIN; if (c->niv < DRS_WIN) c->niv++; }
    }
    const int fb = c->since_gpu > DRS_GPU_STALE, n = fb ? c->niv : c->ngpu;
    if (n < DRS_FRESH || !isfinite(T) || !(T > 0)) return 0;
    const float g = drs_median(fb ? c->iv : c->gpu, n), ivm = c->niv >= DRS_FRESH ? drs_median(c->iv, c->niv) : -1, s = c->level[c->cur];
    int miss = 0;
    for (int i = 0; i < c->niv; i++) miss += c->iv[i] > DRS_MISS * T;
    c->g = g; c->ivm = ivm; c->miss = miss; c->fallback = fb;
    const int late = ivm > 0 && ivm <= DRS_PACED * T && 3 * miss >= c->niv && g > DRS_MISS_GPU * T;
    if (fb ? g > DRS_FB_DOWN_AT * T : g > DRS_DOWN_AT * T || late) {
        if (c->cur + 1 >= c->nlevel) return 0;   /* at the minimum */
        int j = c->cur + 1;
        while (j + 1 < c->nlevel && j - c->cur < DRS_MAX_DOWN && g * (c->level[j] / s) * (c->level[j] / s) > DRS_AIM * T) j++;
        if (c->probe_at >= 0 && now - c->probe_at < DRS_PROBE_FAIL_S) {   /* the probe did not hold: back where it was fine */
            c->failed++; c->probe_wait = c->probe_wait * 2 > DRS_PROBE_MAX_S ? DRS_PROBE_MAX_S : c->probe_wait * 2;
            if (c->probe_from > c->cur && c->probe_from < j) j = c->probe_from;
        }
        c->probe_at = -1; c->downs++;
        return drs_move(c, j, now);
    }
    if (c->probe_at >= 0 && now - c->probe_at >= DRS_PROBE_FAIL_S) { c->probe_at = -1; c->probe_wait = DRS_PROBE_S; }   /* it held */
    if (c->cur == 0) { c->up_since = c->probe_since = -1; return 0; }
    const float up = c->level[c->cur - 1] / s, pred = g * up * up;
    const int clean = c->niv >= DRS_FRESH && !miss;
    if (clean && pred <= DRS_UP_AT * T) { if (c->up_since < 0) c->up_since = now; }
    else c->up_since = -1;
    if (!fb && clean && pred <= DRS_DOWN_AT * T) { if (c->probe_since < 0) c->probe_since = now; }
    else c->probe_since = -1;
    if (c->up_since >= 0 && now - c->up_since >= DRS_UP_HOLD_S && now - c->changed_at >= DRS_UP_DWELL_S) {
        c->ups++; c->probe_at = -1;
        return drs_move(c, c->cur - 1, now);
    }
    if (c->probe_since >= 0 && now - c->probe_since >= DRS_PROBE_HOLD_S && now - c->changed_at >= c->probe_wait) {
        c->probes++; c->probe_at = now; c->probe_from = c->cur;
        return drs_move(c, c->cur - 1, now);
    }
    return 0;
}
