/* The player's settings (issue #288): ~/Library/Application Support/MacNativeGames/TOTK/settings.txt, or the file
   TOTK_SETTINGS names. The settings window (runtime/settings_panel.m, Command-,) writes it at every change; app/launcher.m
   checks it before the game starts (an alert names the first bad line, as for controls.txt) and turns it into the
   environment the runtime reads at start. A variable that is already in the environment (open --env) wins over its line.
   Same style as controls.txt: "key = value" lines, '#' starts a comment, names and words are case-insensitive, a later line
   for the same key wins. Every key is optional; for a missing one no variable is set, so the runtime keeps its default.
     preset         performance | balanced | quality | custom: that preset's values for the keys below; a key the file
                    gives itself wins over it, wherever the preset line is
     fps_cap        0 (no cap) or a frame rate from 30 to 120 (the window offers 30 40 60 90 120;  TOTK_FPS_CAP
                    above 120 the game would run fast: 1.4.3's real-time step stops at 1/120 s)
     drs            0 | 1: dynamic resolution                                                     TOTK_DRS
     drs_min        0.5 .. 1.0: the lowest resolution scale it may use                           TOTK_DRS_MIN
     render_res     0 (the game's own, 1600x900 docked) | <w>x<h> up to 1600x900 in pixels,       TOTK_RENDER_RES (1.4.3)
                    1920x1080 or 2560x1440 (the scenes the app has heap layouts for)
     output         1080p | 2k: the canvas the game starts in                                    TOTK_OUTPUT_RES=2560x1440 for 2k
     picture        off | metalfx | native: key 3's modes (MetalFX 2K, native 2K)                metalfx: TOTK_MFX_OUTPUT=1 and
                                                                                                  TOTK_MFX_UPSCALE=1; native:
                                                                                                  TOTK_OUTPUT_RES=2560x1440
     taa            0 | 1: key 5, MetalFX temporal anti-aliasing                                 TOTK_TAA
     aniso          0 (the game's own) to 16 (the window offers 2 4 8 16)                        TOTK_ANISO
     interpolation  off | 30+30 | half | max: key 2                                              TOTK_MFX (0 interp30 interp interpmax)
     aspect         16:9 | fit | 21:9: key 4                                                     TOTK_ASPECT (0 display 21:9)
   output and picture describe one thing from two sides: native 2K is the 2K canvas without MetalFX, the other two modes
   keep the 1080p canvas, so the window keeps them in step; in a file written by hand, 2k or native starts in native 2K.
   render_res and aniso are read only at start; everything else the window also changes while the game runs.
   Pure C: tests/test_settings_file.c covers the parser, the presets, the file the window writes and the environment. */
#ifndef TOTK_SETTINGS_FILE_H
#define TOTK_SETTINGS_FILE_H
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "aspect_math.h"                                   /* ASPECT_STEP_*: key 4's steps */
#include "../third_party/d2r_gfx/gfx/nvn/totk_mfx_mode.h"   /* MFX_*: key 2's modes */

enum { SK_PRESET, SK_FPS_CAP, SK_DRS, SK_DRS_MIN, SK_RENDER_RES, SK_OUTPUT, SK_PICTURE, SK_TAA, SK_ANISO, SK_INTERPOLATION,
       SK_ASPECT, SK_COUNT };
enum { PRESET_PERFORMANCE, PRESET_BALANCED, PRESET_QUALITY, PRESET_CUSTOM };
enum { CANVAS_1080P, CANVAS_2K };
enum { PICTURE_OFF, PICTURE_METALFX, PICTURE_NATIVE };   /* runtime_output_mode_set */
#define SETTINGS_PRESET_KEYS (1u << SK_FPS_CAP | 1u << SK_DRS | 1u << SK_DRS_MIN | 1u << SK_RENDER_RES | 1u << SK_OUTPUT | \
                              1u << SK_PICTURE | 1u << SK_TAA | 1u << SK_ANISO | 1u << SK_INTERPOLATION)

typedef struct {
    unsigned has;                  /* 1u << SK_*: the keys the file gives, itself or through its preset */
    int line[SK_COUNT];            /* the line each key came from; 0: from the preset, or not given */
    int preset;                    /* PRESET_*: the file's preset line */
    int fps_cap, drs;
    float drs_min;
    unsigned render_w, render_h;   /* 0 x 0: the game's own size */
    int output;                    /* CANVAS_* */
    int picture;                   /* PICTURE_* */
    int taa, aniso;
    int interpolation;             /* MFX_* */
    int aspect;                    /* ASPECT_STEP_* */
} Settings;

/* The runtime's own state without the file: no cap, no dynamic resolution, the game's sizes, MetalFX off. */
static inline void settings_defaults(Settings *s) {
    memset(s, 0, sizeof *s);
    s->preset = PRESET_CUSTOM; s->drs_min = 0.67f; s->output = CANVAS_1080P; s->picture = PICTURE_OFF;
    s->interpolation = MFX_OFF; s->aspect = ASPECT_STEP_GAME;
}

/* The presets (the user, a MacBook Pro M1 Max at 120 Hz, 2026-10-23: a steady 60 in one click). Measured on their save:
   the default 1080p runs 77-82 fps; a 2560x1440 scene with MetalFX temporal anti-aliasing about 50.
   - All three cap at 60: 77-82 fps uncapped is uneven on a 120 Hz screen (one or two refreshes per frame); 60 is every
     second refresh, steady, and leaves the headroom the other choices spend. 16x anisotropic filtering in all three: the
     ground and walls seen at a grazing angle stay sharp, and it only changes the sampler of repeating material textures.
   - 性能 performance: the game's own render size (1600x900 docked) into the 1080p canvas; no temporal anti-aliasing, a
     MetalFX pass over the whole scene every frame.
   - 均衡 balanced: the same render size plus the two MetalFX passes: MetalFX 2K (key 3: the finished 1080p picture
     upscaled to the window at the present) and edge smoothing (key 5). The 77-82 fps headroom pays for them at 60.
   - 画质 quality: a 2560x1440 scene in the native 2K canvas (a sharper scene and UI), about 50 fps by itself, so dynamic
     resolution is on: down to 0.67 (about 1715x965, a little more than the game's own 1600x900) in heavy scenes to hold
     60, back up when there is time.
   Frame interpolation stays off (it changes the pacing the cap is for) and the aspect ratio is not part of a preset: it is
   the shape of the player's display, not a trade of picture for speed. */
static inline void settings_preset(Settings *s, int preset) {
    static const struct { int fps_cap, drs; float drs_min; unsigned w, h; int output, picture, taa, aniso; } p[PRESET_CUSTOM] = {
        [PRESET_PERFORMANCE] = {60, 0, 0.67f, 0, 0, CANVAS_1080P, PICTURE_OFF, 0, 16},
        [PRESET_BALANCED] = {60, 0, 0.67f, 0, 0, CANVAS_1080P, PICTURE_METALFX, 1, 16},
        [PRESET_QUALITY] = {60, 1, 0.67f, 2560, 1440, CANVAS_2K, PICTURE_NATIVE, 1, 16},
    };
    if (preset < 0 || preset > PRESET_CUSTOM) return;
    s->preset = preset; s->has |= 1u << SK_PRESET;
    if (preset == PRESET_CUSTOM) return;
    s->fps_cap = p[preset].fps_cap; s->drs = p[preset].drs; s->drs_min = p[preset].drs_min;
    s->render_w = p[preset].w; s->render_h = p[preset].h; s->output = p[preset].output; s->picture = p[preset].picture;
    s->taa = p[preset].taa; s->aniso = p[preset].aniso; s->interpolation = MFX_OFF;
    s->has |= SETTINGS_PRESET_KEYS;
    for (int k = 0; k < SK_COUNT; k++) if (SETTINGS_PRESET_KEYS >> k & 1) s->line[k] = 0;
}

/* The preset whose values s has (the aspect ratio does not count), else PRESET_CUSTOM. */
static inline int settings_matching_preset(const Settings *s) {
    for (int p = 0; p < PRESET_CUSTOM; p++) {
        Settings t = *s; settings_preset(&t, p);
        if (t.fps_cap == s->fps_cap && t.drs == s->drs && fabsf(t.drs_min - s->drs_min) < 0.005f && t.render_w == s->render_w &&
            t.render_h == s->render_h && t.output == s->output && t.picture == s->picture && t.taa == s->taa &&
            t.aniso == s->aniso && t.interpolation == s->interpolation) return p;
    }
    return PRESET_CUSTOM;
}

/* The words of each key's value, in the order of its enum (NULL for the numeric keys). */
static inline const char *const *settings_words(int key, int *count) {
    static const char *const keys[SK_COUNT] = {"preset", "fps_cap", "drs", "drs_min", "render_res", "output", "picture", "taa",
                                               "aniso", "interpolation", "aspect"};
    static const char *const presets[] = {"performance", "balanced", "quality", "custom"}, *const canvas[] = {"1080p", "2k"},
                             *const picture[] = {"off", "metalfx", "native"}, *const interp[MFX_NMODES] = {"off", "30+30", "half", "max"},
                             *const aspect[] = {"16:9", "fit", "21:9"};
    switch (key) {
    case -1: *count = SK_COUNT; return keys;
    case SK_PRESET: *count = 4; return presets;
    case SK_OUTPUT: *count = 2; return canvas;
    case SK_PICTURE: *count = 3; return picture;
    case SK_INTERPOLATION: *count = MFX_NMODES; return interp;
    case SK_ASPECT: *count = 3; return aspect;
    default: *count = 0; return NULL;
    }
}
static inline const char *settings_word(int key, int value) {
    int n; const char *const *w = settings_words(key, &n);
    return w && value >= 0 && value < n ? w[value] : "?";
}
static inline int settings_find_word(int key, const char *s, size_t n) {
    int count; const char *const *w = settings_words(key, &count);
    for (int i = 0; i < count; i++) if (strlen(w[i]) == n && !strncasecmp(w[i], s, n)) return i;
    return -1;
}

/* A render size the runtime takes (64 to 4096 a side, as runtime/game_patches_v143.c checks) and that the app has heaps for:
   up to 1600x900 in pixels the game's own heaps do; a bigger scene needs a HeapDef layout of its size (runtime/romfs.c),
   and build_app.py makes the 1920x1080 and 2560x1440 ones. Another size would stop the game at start; open --env
   TOTK_RENDER_RES takes it after make_output_res_overlay.py. 0 x 0 is the game's own size. */
static inline int settings_render_ok(unsigned w, unsigned h) {
    if (!w && !h) return 1;
    if (w < 64 || h < 64 || w > 4096 || h > 4096) return 0;
    return (double)w * h <= 1600.0 * 900.0 || (w == 1920 && h == 1080) || (w == 2560 && h == 1440);
}

/* One value: [v, v + n), one word. 0, or the problem. */
static inline const char *settings_value(Settings *s, int key, const char *v, size_t n) {
    char b[32]; char *end;
    if (n >= sizeof b) return "the value is too long";
    memcpy(b, v, n); b[n] = 0;
    int word = settings_find_word(key, v, n);
    switch (key) {
    case SK_PRESET:
        if (word < 0) return "preset is performance, balanced, quality or custom";
        s->preset = word; return NULL;
    case SK_FPS_CAP: {
        long c = strtol(b, &end, 10);
        if (*end || end == b || c < 0 || (c && c < 30) || c > 120) return "fps_cap is 0 (no cap) or a frame rate from 30 to 120";
        s->fps_cap = (int)c; return NULL; }
    case SK_DRS: case SK_TAA:
        if (strcmp(b, "0") && strcmp(b, "1")) return key == SK_DRS ? "drs is 0 or 1" : "taa is 0 or 1";
        *(key == SK_DRS ? &s->drs : &s->taa) = b[0] == '1'; return NULL;
    case SK_DRS_MIN: {
        double m = strtod(b, &end);
        if (*end || end == b || !(m >= 0.5 - 1e-9 && m <= 1.0 + 1e-9)) return "drs_min is a scale from 0.5 to 1.0, such as 0.67";
        s->drs_min = (float)m; return NULL; }
    case SK_RENDER_RES: {
        unsigned w = 0, h = 0; char rest;
        for (char *c = b; *c; c++) if (*c == 'X') *c = 'x';
        if (strcmp(b, "0") && (sscanf(b, "%ux%u%c", &w, &h, &rest) != 2 || !w || !h || !settings_render_ok(w, h)))
            return "render_res is 0 (the game's own), a size up to 1600x900 in pixels, 1920x1080 or 2560x1440";
        s->render_w = w; s->render_h = h; return NULL; }
    case SK_OUTPUT: if (word < 0) return "output is 1080p or 2k"; s->output = word; return NULL;
    case SK_PICTURE: if (word < 0) return "picture is off, metalfx or native"; s->picture = word; return NULL;
    case SK_ANISO: {
        long a = strtol(b, &end, 10);
        if (*end || end == b || a < 0 || a > 16) return "aniso is 0 (the game's own) to 16, such as 16";
        s->aniso = (int)a; return NULL; }
    case SK_INTERPOLATION: if (word < 0) return "interpolation is off, 30+30, half or max"; s->interpolation = word; return NULL;
    case SK_ASPECT: if (word < 0) return "aspect is 16:9, fit or 21:9"; s->aspect = word; return NULL;
    }
    return "unknown setting";
}

/* Applies settings.txt's text to s (start from settings_defaults). Returns 0, or the 1-based number of the first bad line with
   *error naming the problem; s is then unchanged. The preset goes first and the keys the file gives over it, so the order
   of the lines does not matter. */
static inline int settings_parse(const char *text, Settings *s, const char **error) {
    Settings given; settings_defaults(&given);
    int line = 0;
    for (const char *p = text; p && *p;) {
        line++;
        const char *end = strchr(p, '\n'), *stop = end ? end : p + strlen(p), *hash = memchr(p, '#', (size_t)(stop - p));
        if (hash) stop = hash;
        while (p < stop && (*p == ' ' || *p == '\t' || *p == '\r')) p++;
        while (stop > p && (stop[-1] == ' ' || stop[-1] == '\t' || stop[-1] == '\r')) stop--;
        if (p < stop) {
            const char *eq = memchr(p, '=', (size_t)(stop - p));
            if (!eq) { *error = "expected \"key = value\""; return line; }
            const char *key_end = eq, *value = eq + 1, *value_end;
            while (key_end > p && (key_end[-1] == ' ' || key_end[-1] == '\t')) key_end--;
            while (value < stop && (*value == ' ' || *value == '\t')) value++;
            int count, key = -1;
            const char *const *keys = settings_words(-1, &count);
            const char *bad = NULL;
            for (int k = 0; k < count; k++) if (strlen(keys[k]) == (size_t)(key_end - p) && !strncasecmp(keys[k], p, (size_t)(key_end - p))) key = k;
            for (value_end = value; value_end < stop && *value_end != ' ' && *value_end != '\t'; value_end++) {}
            if (key < 0) bad = "unknown setting (preset fps_cap drs drs_min render_res output picture taa aniso interpolation aspect)";
            else if (value == stop) bad = "the value is missing";
            else if (value_end != stop) bad = "one value per line";
            else bad = settings_value(&given, key, value, (size_t)(value_end - value));
            if (bad) { *error = bad; return line; }
            given.has |= 1u << key; given.line[key] = line;
        }
        p = end ? end + 1 : NULL;
    }
    Settings next = *s;
    if (given.has & 1u << SK_PRESET) { settings_preset(&next, given.preset); next.line[SK_PRESET] = given.line[SK_PRESET]; }
#define SETTINGS_TAKE(k, ...) if (given.has & 1u << (k)) { __VA_ARGS__; next.has |= 1u << (k); next.line[k] = given.line[k]; }
    SETTINGS_TAKE(SK_FPS_CAP, next.fps_cap = given.fps_cap)
    SETTINGS_TAKE(SK_DRS, next.drs = given.drs)
    SETTINGS_TAKE(SK_DRS_MIN, next.drs_min = given.drs_min)
    SETTINGS_TAKE(SK_RENDER_RES, next.render_w = given.render_w; next.render_h = given.render_h)
    SETTINGS_TAKE(SK_OUTPUT, next.output = given.output)
    SETTINGS_TAKE(SK_PICTURE, next.picture = given.picture)
    SETTINGS_TAKE(SK_TAA, next.taa = given.taa)
    SETTINGS_TAKE(SK_ANISO, next.aniso = given.aniso)
    SETTINGS_TAKE(SK_INTERPOLATION, next.interpolation = given.interpolation)
    SETTINGS_TAKE(SK_ASPECT, next.aspect = given.aspect)
#undef SETTINGS_TAKE
    *s = next;
    return 0;
}

/* Values the parser takes, whatever s holds (the window fills keys the file does not give from the running game, which a
   test run may have started with any variable). */
static inline void settings_clamp(Settings *s) {
    if (s->fps_cap < 0) s->fps_cap = 0;
    if (s->fps_cap > 0 && s->fps_cap < 30) s->fps_cap = 30;
    if (s->fps_cap > 120) s->fps_cap = 120;
    s->drs = s->drs != 0; s->taa = s->taa != 0;
    if (!(s->drs_min >= 0.5f)) s->drs_min = 0.5f;   /* NaN too */
    if (s->drs_min > 1.0f) s->drs_min = 1.0f;
    s->drs_min = roundf(s->drs_min * 100) / 100;
    if (!settings_render_ok(s->render_w, s->render_h) || !s->render_w || !s->render_h) s->render_w = s->render_h = 0;
    if (s->output != CANVAS_2K) s->output = CANVAS_1080P;
    if (s->picture < PICTURE_OFF || s->picture > PICTURE_NATIVE) s->picture = PICTURE_OFF;
    if (s->aniso < 0) s->aniso = 0;
    if (s->aniso > 16) s->aniso = 16;
    if (s->interpolation < MFX_OFF || s->interpolation >= MFX_NMODES) s->interpolation = MFX_OFF;
    if (s->aspect < ASPECT_STEP_GAME || s->aspect > ASPECT_STEP_WIDE) s->aspect = ASPECT_STEP_GAME;
    if (s->preset < PRESET_PERFORMANCE || s->preset > PRESET_CUSTOM) s->preset = PRESET_CUSTOM;
}

/* settings.txt as the window writes it: every key, and the preset the values match. The length, as snprintf. */
static inline int settings_format(const Settings *s, char *out, size_t n) {
    char res[32];
    if (s->render_w && s->render_h) snprintf(res, sizeof res, "%ux%u", s->render_w, s->render_h); else snprintf(res, sizeof res, "0");
    return snprintf(out, n,
        "# Tears of the Kingdom on the Mac: the game's settings window (Command-,) writes this file at every change and the app\n"
        "# reads it before the game starts. key = value; '#' starts a comment. A variable given with open --env wins over its line.\n"
        "preset = %s\n"
        "fps_cap = %d          # 0 (no cap) or a frame rate: 30, 40, 60, 90, 120\n"
        "drs = %d              # dynamic resolution: 0 off, 1 on\n"
        "drs_min = %.2f        # its lowest resolution scale, 0.5 to 1.0\n"
        "render_res = %s       # 0 (the game's own), 1920x1080 or 2560x1440; read at start\n"
        "output = %s           # the canvas: 1080p or 2k\n"
        "picture = %s          # key 3: off, metalfx (MetalFX 2K) or native (native 2K)\n"
        "taa = %d              # key 5, edge smoothing (MetalFX temporal anti-aliasing): 0 or 1\n"
        "aniso = %d            # anisotropic filtering: 0 (the game's own), 2, 4, 8 or 16; read at start\n"
        "interpolation = %s    # key 2, frame interpolation: off, 30+30, half or max\n"
        "aspect = %s           # key 4: 16:9, fit or 21:9\n",
        settings_word(SK_PRESET, settings_matching_preset(s)), s->fps_cap, s->drs, (double)s->drs_min, res,
        settings_word(SK_OUTPUT, s->output), settings_word(SK_PICTURE, s->picture), s->taa, s->aniso,
        settings_word(SK_INTERPOLATION, s->interpolation), settings_word(SK_ASPECT, s->aspect));
}

/* What this build does with the keys that depend on the game version. The launcher and the window are compiled for each
   version, and one settings.txt serves every TOTK version (they share the data folder), so a key the build cannot use
   sets nothing rather than stopping the start:
   - render_res: 1.4.3, which grows the heaps for a scene above 1600x900 (Breath of the Wild's TOTK_RENDER_RES means
     something else);
   - native 2K (output 2k, picture native): TOTK; Breath of the Wild has no output-size patch yet;
   - aspect: 1.2.1, 1.4.3 and Breath of the Wild 1.9.0, whose key 4 has no fit step (1.0.0 and 1.1.2 stop at start on
     TOTK_ASPECT, Breath of the Wild 1.6.0 has no key 4). */
enum { SETTINGS_CAN_RENDER_RES = 1, SETTINGS_CAN_NATIVE_2K = 2, SETTINGS_CAN_ASPECT = 4, SETTINGS_CAN_ASPECT_FIT = 8 };
static inline unsigned settings_build_caps(void) {
#if defined(GAME_BOTW160)
    return 0;
#elif defined(GAME_BOTW190)
    return SETTINGS_CAN_ASPECT;
#elif defined(TOTK_GAME_V143)
    return SETTINGS_CAN_RENDER_RES | SETTINGS_CAN_NATIVE_2K | SETTINGS_CAN_ASPECT | SETTINGS_CAN_ASPECT_FIT;
#elif defined(TOTK_GAME_V121)
    return SETTINGS_CAN_NATIVE_2K | SETTINGS_CAN_ASPECT | SETTINGS_CAN_ASPECT_FIT;
#else
    return SETTINGS_CAN_NATIVE_2K;
#endif
}

/* The environment for the keys s gives: set(name, value, line, ctx) once per variable (line: the line it comes from, 0 for
   the preset). 1080p and picture off set no TOTK_OUTPUT_RES: unset is auto, the 2K-capable swapchain starting at 1080p,
   as without the file. */
typedef void (*settings_env_fn)(const char *name, const char *value, int line, void *ctx);
static inline void settings_env(const Settings *s, unsigned caps, settings_env_fn set, void *ctx) {
    char v[32];
#define SETTINGS_GIVEN(k) (s->has >> (k) & 1)
    if (SETTINGS_GIVEN(SK_FPS_CAP)) { snprintf(v, sizeof v, "%d", s->fps_cap); set("TOTK_FPS_CAP", v, s->line[SK_FPS_CAP], ctx); }
    if (SETTINGS_GIVEN(SK_DRS)) set("TOTK_DRS", s->drs ? "1" : "0", s->line[SK_DRS], ctx);
    if (SETTINGS_GIVEN(SK_DRS_MIN)) { snprintf(v, sizeof v, "%.2f", (double)s->drs_min); set("TOTK_DRS_MIN", v, s->line[SK_DRS_MIN], ctx); }
    if (SETTINGS_GIVEN(SK_RENDER_RES) && caps & SETTINGS_CAN_RENDER_RES) {
        if (s->render_w && s->render_h) snprintf(v, sizeof v, "%ux%u", s->render_w, s->render_h); else snprintf(v, sizeof v, "0");
        set("TOTK_RENDER_RES", v, s->line[SK_RENDER_RES], ctx);
    }
    int native = SETTINGS_GIVEN(SK_PICTURE) && s->picture == PICTURE_NATIVE, wide = SETTINGS_GIVEN(SK_OUTPUT) && s->output == CANVAS_2K;
    if ((native || wide) && caps & SETTINGS_CAN_NATIVE_2K) set("TOTK_OUTPUT_RES", "2560x1440", s->line[native ? SK_PICTURE : SK_OUTPUT], ctx);
    if (SETTINGS_GIVEN(SK_PICTURE)) {
        const char *on = s->picture == PICTURE_METALFX ? "1" : "0";
        set("TOTK_MFX_OUTPUT", on, s->line[SK_PICTURE], ctx); set("TOTK_MFX_UPSCALE", on, s->line[SK_PICTURE], ctx);
    }
    if (SETTINGS_GIVEN(SK_TAA)) set("TOTK_TAA", s->taa ? "1" : "0", s->line[SK_TAA], ctx);
    if (SETTINGS_GIVEN(SK_ANISO)) { snprintf(v, sizeof v, "%d", s->aniso); set("TOTK_ANISO", v, s->line[SK_ANISO], ctx); }
    if (SETTINGS_GIVEN(SK_INTERPOLATION) && s->interpolation >= MFX_OFF && s->interpolation < MFX_NMODES) {
        static const char *const modes[MFX_NMODES] = {"0", "interp30", "interp", "interpmax"};   /* totk_mfx.m mfx_init */
        set("TOTK_MFX", modes[s->interpolation], s->line[SK_INTERPOLATION], ctx);
    }
    if (SETTINGS_GIVEN(SK_ASPECT) && caps & SETTINGS_CAN_ASPECT && s->aspect >= ASPECT_STEP_GAME && s->aspect <= ASPECT_STEP_WIDE &&
        (s->aspect != ASPECT_STEP_FIT || caps & SETTINGS_CAN_ASPECT_FIT)) {
        static const char *const steps[] = {"0", "display", "21:9"};   /* aspect_patch.h: the game's own, fit, the wide step */
        set("TOTK_ASPECT", steps[s->aspect], s->line[SK_ASPECT], ctx);
    }
#undef SETTINGS_GIVEN
}

/* The launcher's setter: name = value unless the environment has it already (open --env wins). The value in force. */
static inline const char *settings_setenv(const char *name, const char *value) {
    const char *had = getenv(name);
    if (had) return had;
    setenv(name, value, 0);
    return getenv(name);
}
#endif
