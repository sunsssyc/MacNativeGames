/* The settings behind the in-game settings menu (issue #288; runtime/quick_menu.inc, the app menu's "设置…", Command-,):
   presets that make a steady 60 one click, and every option of runtime/settings_file.h, so the number keys and variables
   only open --env can give are not the only way. The menu draws them in the game's own style; this file keeps the model.
   - What the runtime can change while playing applies at once: the frame rate cap, dynamic resolution (on / off, its
     lowest scale, its frame-time target = 1000 / cap), edge smoothing (key 5), frame interpolation (key 2), the picture
     mode and canvas (key 3) and the aspect ratio (key 4), through the same functions as the keys (direct setters beside
     their cycles). The render resolution and anisotropic filtering are read at start: their rows say "重启后生效" while
     the choice differs from what this run started with.
   - Every change is written to settings.txt (TOTK_SETTINGS, set by the launcher), which the next start reads; a run
     without TOTK_SETTINGS (a test, a run from the terminal) writes nothing.
   - Each step starts from the state in force: what the game reports wins, so a change made with keys 2-5 is where the
     next click starts from. Keys keep working; their changes are written only with the next change made in the menu.
   - The frame rate cap and the resolution controller are separate features: a build without them leaves their functions
     NULL (weak references the Makefile lets stay undefined, -Wl,-U) and the menu greys their rows out. */
#import <Cocoa/Cocoa.h>
#include "runtime.h"
#include "settings_file.h"
#include "totk_ui_lang.h"

extern void nvn_set_fps_cap(int cap) __attribute__((weak_import));
extern int nvn_fps_cap(void) __attribute__((weak_import));
extern int nvn_fps_cap_pacing(void) __attribute__((weak_import));
extern void runtime_drs_set(int on) __attribute__((weak_import));
extern int runtime_drs_enabled(void) __attribute__((weak_import));
extern float runtime_drs_min(void) __attribute__((weak_import));
extern float runtime_drs_scale(void) __attribute__((weak_import));
extern void runtime_drs_set_min(float m) __attribute__((weak_import));
extern void runtime_drs_set_target_ms(float ms) __attribute__((weak_import));
int taa_enabled(void);                /* gfx/nvn/totk_taa.m: key 5 */
void taa_set(int on);
void mfx_set(int mode);               /* gfx/nvn/totk_mfx.m: key 2 (mfx_enabled: totk_mfx_mode.h) */
int mfxup_output_enabled(void);       /* gfx/nvn/totk_mfx_up.m: key 3's MetalFX 2K */

static Settings model;   /* what the menu shows and writes */
static Settings seen;    /* what the game reported at the last look: a key 2-5 press shows as a change of it */
static BOOL settingsSaveFailed;

static NSString *settings_path(void) { const char *p = getenv("TOTK_SETTINGS"); return p && *p ? @(p) : nil; }
static int native_this_run(void) { unsigned w, h; return runtime_output_res(&w, &h); }   /* the 2K swapchain exists */
static int aspect_this_run(void) { return (settings_build_caps() & SETTINGS_CAN_ASPECT) && runtime_aspect_step() >= 0; }

/* The state in force for the keys the game reports; the others keep what s has. */
static void live_read(Settings *s) {
    if (nvn_fps_cap) s->fps_cap = nvn_fps_cap();
    if (runtime_drs_min) s->drs_min = runtime_drs_min();
    if (runtime_drs_enabled) s->drs = runtime_drs_enabled() != 0;
    uint64_t c = runtime_output_size_current();
    int native = (uint32_t)c != 1920 || (uint32_t)(c >> 32) != 1080;   /* key 3's own reading (frontend.m shortcut_text) */
    s->picture = native ? PICTURE_NATIVE : mfxup_output_enabled() ? PICTURE_METALFX : PICTURE_OFF;
    s->output = native ? CANVAS_2K : CANVAS_1080P;
    s->taa = taa_enabled() != 0;
    s->interpolation = mfx_enabled();
    if (aspect_this_run()) s->aspect = runtime_aspect_step();
}

/* This run's start values of the keys read only at start. */
static void started_with(unsigned *w, unsigned *h, int *aniso) {
    const char *r = getenv("TOTK_RENDER_RES"), *a = getenv("TOTK_ANISO");
    *w = *h = 0; if (r && sscanf(r, "%ux%u", w, h) != 2) *w = *h = 0;
    *aniso = a ? atoi(a) : 0;
}

/* Before every look or change: what this run started with (the first time; later, what the menu last showed), then
   settings.txt (what the next start will take), then what the game reports now for the keys it can change while playing.
   Frame interpolation keeps a choice the game has not latched yet (it takes effect at the next game frame). */
static void model_load(void) {
    static int loaded;
    int first = !loaded;
    if (!loaded) {
        loaded = 1; settings_defaults(&model);
        const char *e;
        if ((e = getenv("TOTK_FPS_CAP"))) model.fps_cap = atoi(e);
        if ((e = getenv("TOTK_DRS"))) model.drs = atoi(e) != 0;
        if ((e = getenv("TOTK_DRS_MIN"))) model.drs_min = (float)atof(e);
        int aniso; started_with(&model.render_w, &model.render_h, &aniso); model.aniso = aniso;
        seen = model; live_read(&seen);
    }
    NSString *path = settings_path();
    NSData *data = path ? [NSData dataWithContentsOfFile:path] : nil;
    if (data) {
        NSString *text = data.length < 16384 ? [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] : nil;
        Settings file = model; const char *error = "not UTF-8 text, or larger than 16 KB";
        int line = text ? settings_parse(text.UTF8String, &file, &error) : 1;
        if (line) fprintf(stderr, "[totk] settings: %s line %d: %s; the menu starts from the running game\n", path.UTF8String, line, error);
        else model = file;
    }
    Settings live = model; live_read(&live);
#define SETTINGS_FOLLOW(f) model.f = live.f;
    SETTINGS_FOLLOW(fps_cap) SETTINGS_FOLLOW(drs_min) SETTINGS_FOLLOW(drs) SETTINGS_FOLLOW(picture) SETTINGS_FOLLOW(output)
    SETTINGS_FOLLOW(taa) SETTINGS_FOLLOW(aspect)
#undef SETTINGS_FOLLOW
    if (first || live.interpolation != seen.interpolation) model.interpolation = live.interpolation;   /* key 2, or the latch */
    seen = live;
    settings_clamp(&model);
}

static void model_save(void) {
    NSString *path = settings_path();
    settingsSaveFailed = NO;
    if (!path) return;
    char text[4096]; Settings s = model; settings_clamp(&s);
    if (settings_format(&s, text, sizeof text) >= (int)sizeof text) return;
    NSError *error = nil;
    if (![@(text) writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:&error]) {
        settingsSaveFailed = YES;
        fprintf(stderr, "[totk] settings: could not write %s (%s); the change holds until the game closes\n", path.UTF8String, error.localizedDescription.UTF8String);
    }
}

/* The running game follows a change from o to n (render size and filtering wait for the next start). */
static void apply_live(const Settings *o, const Settings *n) {
    if (n->fps_cap != o->fps_cap && nvn_set_fps_cap) nvn_set_fps_cap(n->fps_cap);
    /* Match the controller's startup target, including when the cap is removed. */
    if ((n->fps_cap != o->fps_cap || (n->drs && !o->drs)) && runtime_drs_set_target_ms) {
        float target = n->fps_cap > 0 ? 1000.0f / n->fps_cap : 16.7f;
        const char *value = getenv("TOTK_DRS_TARGET_MS");
        if (value) {
            char *end; float explicitTarget = strtof(value, &end);
            if (end != value && !*end && isfinite(explicitTarget) && explicitTarget >= 4 && explicitTarget <= 100)
                target = explicitTarget;
        }
        runtime_drs_set_target_ms(target);
    }
    if ((n->drs_min != o->drs_min || (n->drs && !o->drs)) && runtime_drs_set_min) runtime_drs_set_min(n->drs_min);
    if (n->drs != o->drs && runtime_drs_set) runtime_drs_set(n->drs);
    if ((n->picture != o->picture || n->output != o->output) && !runtime_output_mode_set(n->picture))
        fprintf(stderr, "[totk] settings: picture mode %d is not available in this run; settings.txt keeps it for the next start\n", n->picture);
    if (n->taa != o->taa) taa_set(n->taa);
    if (n->interpolation != o->interpolation) mfx_set(n->interpolation);
    if (n->aspect != o->aspect && !runtime_aspect_set(n->aspect)) fprintf(stderr, "[totk] settings: aspect step %d is not available here\n", n->aspect);
}

/* A change made in the menu: the running game follows, settings.txt keeps it. */
static void settings_commit(Settings next) {
    settings_clamp(&next);
    apply_live(&model, &next);
    model = next;
    Settings live = model; live_read(&live); seen = live;   /* the game's state after this change is the one later keys change */
    model_save();
}

/* One step of a menu row: a preset (100-102), or the row's previous (-1) / next (1) value. The actions are the menu's: 110
   cap, 111 dynamic resolution, 112 its lowest scale, 113 render resolution, 114 anisotropic filtering, and the number keys'
   codes 19 (key 2), 20 (key 3), 21 (key 4), 23 (key 5). */
BOOL settings_quick_step(int action, int direction) {
    direction = direction < 0 ? -1 : 1;
    model_load();
    Settings next = model;
    if (action >= 100 && action <= 102) settings_preset(&next, action - 100);
    else if (action == 110) {
        const int caps[] = {30, 40, 60, 90, 120, 0};
        int i = 0; while (i < 6 && caps[i] != next.fps_cap) i++;
        next.fps_cap = caps[(i + 6 + direction) % 6];
    } else if (action == 111) next.drs = !next.drs;
    else if (action == 112) {   /* the stops include 0.67, the quality preset's */
        const float stops[] = {0.5f, 0.55f, 0.6f, 0.67f, 0.7f, 0.75f, 0.8f, 0.85f, 0.9f, 0.95f, 1.0f};
        int i = 0; while (i < 10 && stops[i] + 0.005f < next.drs_min) i++;   /* the first stop at or above it */
        if (direction < 0 || fabsf(stops[i] - next.drs_min) < 0.005f) i += direction;
        next.drs_min = stops[i < 0 ? 0 : i > 10 ? 10 : i];
    }
    else if (action == 113) {
        const unsigned sizes[][2] = {{0, 0}, {1920, 1080}, {2560, 1440}};
        int i = 0; while (i < 3 && (sizes[i][0] != next.render_w || sizes[i][1] != next.render_h)) i++;
        i = (i % 3 + 3 + direction) % 3; next.render_w = sizes[i][0]; next.render_h = sizes[i][1];
    } else if (action == 114) {
        const int levels[] = {0, 2, 4, 8, 16};
        int i = 0; while (i < 5 && levels[i] != next.aniso) i++;
        next.aniso = levels[(i % 5 + 5 + direction) % 5];
    }
    else if (action == 19) next.interpolation = (next.interpolation + MFX_NMODES + direction) % MFX_NMODES;
    else if (action == 20) {
        next.picture = (next.picture + 3 + direction) % 3;
        if (next.picture == PICTURE_NATIVE && !native_this_run()) next.picture = (next.picture + 3 + direction) % 3;
        next.output = next.picture == PICTURE_NATIVE ? CANVAS_2K : CANVAS_1080P;
    }
    else if (action == 21) {
        if (direction > 0) runtime_aspect_toggle();
        else {
            /* Discover the runtime cycle: fit may be skipped when it duplicates another ratio. */
            int start = runtime_aspect_step(), previous = start;
            if (start >= 0) {
                for (int i = 0; i < 3; i++) {
                    if (!runtime_aspect_toggle()) break;
                    int current = runtime_aspect_step();
                    if (current == start) { runtime_aspect_set(previous); break; }
                    previous = current;
                    if (i == 2) runtime_aspect_set(start);
                }
            }
        }
        live_read(&next);
    }
    else if (action == 23) next.taa = !next.taa;
    else return NO;
    settings_commit(next);
    return !settingsSaveFailed;
}
BOOL settings_quick_apply(int action) { return settings_quick_step(action, 1); }
int settings_quick_preset(void) {
    model_load();
    int preset = settings_matching_preset(&model);
    return preset == PRESET_CUSTOM ? -1 : preset;
}

/* What a row shows (UTF-8, valid until the next call) and flags: SETTINGS_ROW_ENABLED when this build and run can change
   it, SETTINGS_ROW_ON for a switch that is on, SETTINGS_ROW_RESTART when the choice waits for the next start. Row actions
   as settings_quick_step's; NULL for one this file does not own. */
const char *settings_quick_value(int action, int *flags) {
    static char text[96];
    unsigned caps = settings_build_caps(), rw, rh; int aniso, f = SETTINGS_ROW_ENABLED;
    model_load(); started_with(&rw, &rh, &aniso);
    switch (action) {
    case 110:
        if (model.fps_cap) snprintf(text, sizeof text, "%d FPS", model.fps_cap); else snprintf(text, sizeof text, "%s", TOTK_UI("不限帧", "Unlimited"));
        if (!nvn_set_fps_cap) f = 0;
        break;
    case 111:
        snprintf(text, sizeof text, "%s", model.drs ? TOTK_UI("开启", "On") : TOTK_UI("关闭", "Off"));
        f = (runtime_drs_set ? SETTINGS_ROW_ENABLED : 0) | (model.drs ? SETTINGS_ROW_ON : 0);
        break;
    case 112:
        snprintf(text, sizeof text, "%.0f%%", model.drs_min * 100);
        if (!runtime_drs_set_min || !model.drs) f = 0;
        break;
    case 113:
        if (model.render_w) snprintf(text, sizeof text, "%u × %u", model.render_w, model.render_h);
        else snprintf(text, sizeof text, "%s", TOTK_UI("游戏自身", "Game default"));
        f = (caps & SETTINGS_CAN_RENDER_RES ? SETTINGS_ROW_ENABLED : 0) | (model.render_w != rw || model.render_h != rh ? SETTINGS_ROW_RESTART : 0);
        break;
    case 114:
        if (model.aniso) snprintf(text, sizeof text, "%d×", model.aniso); else snprintf(text, sizeof text, "%s", TOTK_UI("游戏自身", "Game default"));
        if (model.aniso != aniso) f |= SETTINGS_ROW_RESTART;
        break;
    case 20:
        snprintf(text, sizeof text, "%s", model.picture == PICTURE_NATIVE ? TOTK_UI("原生 2K", "Native 2K") : model.picture == PICTURE_METALFX ? "MetalFX 2K" : TOTK_UI("关闭", "Off"));
        break;
    case 23:
        snprintf(text, sizeof text, "%s", model.taa ? TOTK_UI("开启", "On") : TOTK_UI("关闭", "Off"));
        f |= model.taa ? SETTINGS_ROW_ON : 0;
        break;
    case 19:
        snprintf(text, sizeof text, "%s", model.interpolation == MFX_30 ? "30 + 30" : model.interpolation == MFX_HALF ? TOTK_UI("刷新率一半", "Half refresh")
                 : model.interpolation == MFX_MAX ? TOTK_UI("不限帧", "Unlimited") : TOTK_UI("关闭", "Off"));
        break;
    case 21: {
        float ratio = runtime_aspect_now();
        if (model.aspect == ASPECT_STEP_FIT) snprintf(text, sizeof text, "%s", TOTK_UI("适配窗口", "Fit window"));
        else if (model.aspect == ASPECT_STEP_WIDE && ratio && fabsf(ratio * 9 - 21) >= 0.05f) snprintf(text, sizeof text, "%.2f:1", ratio);
        else snprintf(text, sizeof text, "%s", model.aspect == ASPECT_STEP_WIDE ? "21:9" : "16:9");
        if (!aspect_this_run()) f = 0;
        break;
    }
    default:
        return NULL;
    }
    if (flags) *flags = f;
    return text;
}

/* The menu's status line: the frame rate the game ran at when the menu opened (the menu pauses the game, so the rate
   measured while it is open says nothing; fps < 0: unknown), the cap and the resolution scale in force, the canvas. */
const char *settings_quick_status(int fps, int generated) {
    static char text[160];
    int n = 0;
    if (fps < 0) n = snprintf(text, sizeof text, "%s", TOTK_UI("暂停前 -- FPS", "-- FPS before the pause"));
    else if (generated > 0) n = snprintf(text, sizeof text, TOTK_UI("暂停前 %d+%d FPS", "%d+%d FPS before the pause"), fps, generated);
    else n = snprintf(text, sizeof text, TOTK_UI("暂停前 %d FPS", "%d FPS before the pause"), fps);
    if (nvn_fps_cap && n < (int)sizeof text) {
        int cap = nvn_fps_cap();
        n += cap > 0 ? snprintf(text + n, sizeof text - n, TOTK_UI(" · 上限 %d", " · cap %d"), cap) : snprintf(text + n, sizeof text - n, "%s", TOTK_UI(" · 不限帧率", " · no cap"));
        if (cap > 0 && nvn_fps_cap_pacing && !nvn_fps_cap_pacing() && n < (int)sizeof text) n += snprintf(text + n, sizeof text - n, "%s", TOTK_UI(" · 限帧暂停", " · cap paused"));
    }
    if (runtime_drs_scale && n < (int)sizeof text) n += snprintf(text + n, sizeof text - n, TOTK_UI(" · 分辨率 %.0f%%", " · resolution %.0f%%"), runtime_drs_scale() * 100.0);
    uint64_t c = runtime_output_size_current();
    if (n < (int)sizeof text) snprintf(text + n, sizeof text - n, TOTK_UI(" · 画布 %u×%u", " · canvas %u×%u"), (unsigned)(uint32_t)c, (unsigned)(c >> 32));
    return text;
}

/* Where the menu's changes go: 1 settings.txt, 0 this run only (no TOTK_SETTINGS), -1 the last save failed. */
int settings_quick_saving(void) { return settingsSaveFailed ? -1 : settings_path() ? 1 : 0; }
