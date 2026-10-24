/* The settings behind the in-game settings menu (games/totk/runtime/settings_panel.m) without the game: the menu's own
   calls (settings_quick_step, _value, _status, _preset, _saving). The key 2 / 3 / 4 / 5 state behind it is the production
   code (totk_mfx.m, totk_mfx_up.m, totk_taa.m, game_patches*.c with a synthetic output page: tests/shortcut_output_fixture.c).
   The frame-rate cap and the resolution controller are other features: tests/settings_panel_optional.c stands in for them,
   or they are missing (NULL) when it is not linked. argv[1]: the settings.txt to write (TOTK_SETTINGS), or "-" for a run
   without it. */
#include "../games/totk/runtime/settings_panel.m"
#include <assert.h>

void mfx_set(int mode);
int mfx_latch(void);
void mfxup_set(int on);
int mfxup_enabled(void);
void mfxup_output_set(int on);
void shortcut_test_output_init(void);
void shortcut_test_disable_native(void);
void shortcut_test_aspect_init(double view);
void dm_gfx_set_flag(const char *name, int value) {   /* the flags key 3 and the menu's picture modes use */
    if (!strcmp(name, "mfx_output")) mfxup_output_set(value);
    else if (!strcmp(name, "mfx_upscale")) mfxup_set(value);
    else if (!strcmp(name, "mfx_interp")) mfx_set(value);
    else abort();
}
int dm_gfx_fps_now(int *generated) { if (generated) *generated = 0; return 82; }
void runtime_oe_push_message(uint32_t message) { (void)message; }
/* What the menu asked of the cap and the resolution controller (tests/settings_panel_optional.c counts, when linked). */
int probe_cap_calls, probe_drs_calls;
extern int probe_cap_paused __attribute__((weak_import));
float probe_drs_min = 0.67f, probe_drs_target;

static int failures;
static void expect(int ok, const char *what) { if (!ok) { fprintf(stderr, "FAIL: %s\n", what); failures++; } }
static NSString *file_text(const char *path) { return [NSString stringWithContentsOfFile:@(path) encoding:NSUTF8StringEncoding error:nil]; }
/* settings.txt as the launcher reads it. */
static Settings file_settings(const char *path) {
    Settings s; settings_defaults(&s); const char *error = NULL; NSString *text = file_text(path);
    expect(text && !settings_parse(text.UTF8String, &s, &error), "the written settings.txt parses");
    return s;
}
static int canvas_2k(void) { return runtime_output_size_current() == ((uint64_t)1440 << 32 | 2560); }
/* A row as the menu draws it. */
static NSString *shown(int action, int *flags) { int f = 0; const char *v = settings_quick_value(action, &f); if (flags) *flags = f; return v ? @(v) : nil; }
static int row_flags(int action) { int f; shown(action, &f); return f; }
static int is(int action, NSString *text) { return [shown(action, NULL) isEqualToString:text]; }
/* Steps a row forward until it shows text (at most n clicks). */
static int step_to(int action, NSString *text, int n) {
    for (int i = 0; i < n && !is(action, text); i++) settings_quick_step(action, 1);
    return is(action, text);
}

int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    const char *path = strcmp(argv[1], "-") ? argv[1] : NULL;
    if (path) setenv("TOTK_SETTINGS", path, 1); else unsetenv("TOTK_SETTINGS");
    shortcut_test_output_init();
    int optional = nvn_set_fps_cap != NULL, v143 = (settings_build_caps() & SETTINGS_CAN_RENDER_RES) != 0, zh = totk_ui_zh();
    expect(optional == (runtime_drs_set != NULL) && optional == (runtime_drs_scale != NULL), "the optional features come together here");
#define T(z, e) (zh ? @z : @e)

    /* Looked at without a file: the running game's state, no preset (no cap), nothing written. */
    expect(settings_quick_preset() == -1, "no preset matches the running state");
    expect(is(20, T("关闭", "Off")) && is(23, T("关闭", "Off")) && is(19, T("关闭", "Off")), "the running state");
    expect(!path || ![NSFileManager.defaultManager fileExistsAtPath:@(path)], "looking writes nothing");
    expect(((row_flags(110) & SETTINGS_ROW_ENABLED) != 0) == optional && ((row_flags(111) & SETTINGS_ROW_ENABLED) != 0) == optional,
           "the cap and dynamic resolution rows: greyed out when the build has none");
    expect(!(row_flags(112) & SETTINGS_ROW_ENABLED), "the lowest scale waits for dynamic resolution");
    expect(((row_flags(113) & SETTINGS_ROW_ENABLED) != 0) == v143, "render resolution: 1.4.3");
    expect(!(row_flags(21) & SETTINGS_ROW_ENABLED), "key 4 not installed: aspect greyed out");
    expect(!(row_flags(113) & SETTINGS_ROW_RESTART) && !(row_flags(114) & SETTINGS_ROW_RESTART), "nothing waits for a restart yet");
    expect(strstr(settings_quick_status(), "82 FPS") && strstr(settings_quick_status(), "1920×1080"), "the now line");
    expect(settings_quick_saving() == (path ? 1 : 0), "where changes go");
    expect(shown(22, NULL) == nil && shown(120, NULL) == nil, "rows the menu reads itself are not this file's");

    /* 均衡: MetalFX 2K, edge smoothing, the cap; written as balanced. */
    expect(settings_quick_apply(101), "balanced");
    expect(mfxup_output_enabled() && mfxup_enabled() && !canvas_2k() && taa_enabled(), "balanced in the running game");
    expect(!optional || (nvn_fps_cap() == 60 && probe_cap_calls == 1 && !runtime_drs_enabled()), "balanced: cap 60");
    if (path) {
        Settings f = file_settings(path);
        expect(f.preset == PRESET_BALANCED && f.picture == PICTURE_METALFX && f.taa && f.aniso == 16 && f.fps_cap == 60, "balanced in settings.txt");
        expect([file_text(path) containsString:@"preset = balanced"], "the file names the preset");
    }
    expect(settings_quick_preset() == PRESET_BALANCED && is(20, @"MetalFX 2K") && (row_flags(23) & SETTINGS_ROW_ON), "the menu shows it");
    expect(row_flags(114) & SETTINGS_ROW_RESTART, "16x filtering differs from this run's: restart");

    /* 画质: native 2K canvas without MetalFX, dynamic resolution down to 0.67 aiming at 1000 / 60 ms. */
    expect(settings_quick_apply(102), "quality");
    expect(canvas_2k() && !mfxup_output_enabled() && !mfxup_enabled() && taa_enabled(), "quality: native 2K");
    expect(!optional || (runtime_drs_enabled() && fabsf(probe_drs_min - 0.67f) < 1e-4f && fabsf(probe_drs_target - 1000.0f / 60) < 1e-3f), "quality: dynamic resolution");
    expect(is(20, T("原生 2K", "Native 2K")) && ((row_flags(112) & SETTINGS_ROW_ENABLED) != 0) == optional, "native 2K shows; the lowest scale opens");
    if (path) { Settings f = file_settings(path); expect(f.preset == PRESET_QUALITY && f.render_w == 2560 && f.drs && f.output == CANVAS_2K, "quality in settings.txt"); }
    if (v143) expect((row_flags(113) & SETTINGS_ROW_RESTART) && is(113, @"2560 × 1440"), "render resolution: differs from this run's, restart");

    /* One option changed: custom. */
    expect(settings_quick_step(23, 1) && !taa_enabled() && settings_quick_preset() == -1, "edge smoothing off: custom");
    if (path) expect(file_settings(path).preset == PRESET_CUSTOM && !file_settings(path).taa, "custom in settings.txt");

    /* Key 3 behind the menu (the production cycle): the next look follows and writes nothing. */
    NSString *before = path ? file_text(path) : nil;
    runtime_output_mode_cycle();   /* native 2K -> off */
    expect(is(20, T("关闭", "Off")) && !canvas_2k(), "key 3 shows in the menu");
    expect(!path || [file_text(path) isEqualToString:before], "a key's change is not written by itself");
    runtime_output_mode_cycle();   /* off -> MetalFX 2K */
    expect(is(20, @"MetalFX 2K"), "key 3 again");

    /* Frame interpolation takes effect at the next game frame: the menu keeps the choice meanwhile. */
    expect(settings_quick_step(19, 1) && is(19, @"30 + 30") && mfx_enabled() == MFX_OFF, "requested, not latched yet: the choice stays");
    mfx_latch(); expect(is(19, @"30 + 30") && mfx_enabled() == MFX_30, "latched");
    mfx_set(MFX_MAX); mfx_latch(); expect(is(19, T("不限帧", "Unlimited")), "key 2 shows in the menu");

    /* The picture mode and the canvas in step; MetalFX 2K -> native 2K -> off never leaves them apart. */
    expect(settings_quick_step(20, 1) && canvas_2k() && !mfxup_output_enabled(), "MetalFX 2K -> native 2K");
    if (path) expect(file_settings(path).output == CANVAS_2K && file_settings(path).picture == PICTURE_NATIVE, "native 2K: the 2K canvas");
    expect(settings_quick_step(20, 1) && !canvas_2k() && !mfxup_output_enabled() && !mfxup_enabled(), "native 2K -> off");
    if (path) expect(file_settings(path).output == CANVAS_1080P, "off: the 1080p canvas");

    /* Read at start: written, marked for the next start, and the mark goes when the choice is this run's again. */
    expect(step_to(114, @"8×", 6) && (row_flags(114) & SETTINGS_ROW_RESTART), "anisotropic filtering: restart");
    if (v143) expect(step_to(113, @"1920 × 1080", 3), "render resolution 1920x1080");
    if (path) { Settings f = file_settings(path); expect(f.aniso == 8 && (!v143 || (f.render_w == 1920 && f.render_h == 1080)), "start-only keys in settings.txt"); }
    expect(step_to(114, T("游戏自身", "Game default"), 6) && !(row_flags(114) & SETTINGS_ROW_RESTART), "back to this run's: no restart needed");
    if (v143) expect(step_to(113, T("游戏自身", "Game default"), 3) && !(row_flags(113) & SETTINGS_ROW_RESTART), "render resolution back to the game's own");

    /* The cap and the lowest scale. */
    if (optional) {
        expect(step_to(110, @"40 FPS", 6) && nvn_fps_cap() == 40, "cap 40");
        probe_cap_paused = 1;
        expect(strstr(settings_quick_status(), zh ? "限帧暂停" : "cap paused") && is(110, @"40 FPS"), "paused cap keeps choice and reports actual pacing");
        probe_cap_paused = 0;
        expect(fabsf(probe_drs_target - 25.0f) < 1e-3f, "cap 40: the controller aims at 25 ms");
        expect(is(112, @"67%"), "the quality preset's lowest scale");
        expect(settings_quick_step(112, 1) && is(112, @"70%") && fabsf(probe_drs_min - 0.7f) < 1e-4f, "lowest scale up a stop");
        expect(settings_quick_step(112, -1) && is(112, @"67%"), "and back to the preset's stop");
        expect(settings_quick_step(112, -1) && settings_quick_step(112, -1) && settings_quick_step(112, -1) && is(112, @"50%"), "down to 50%");
        expect(settings_quick_step(112, -1) && is(112, @"50%"), "50% is the floor");
        runtime_drs_set_min(0.62f); expect(settings_quick_step(112, 1) && is(112, @"67%"), "an odd scale steps to the next stop");
        expect(step_to(112, @"80%", 4), "lowest scale 0.8");
        expect(settings_quick_step(111, 1) && !runtime_drs_enabled() && !(row_flags(112) & SETTINGS_ROW_ENABLED), "dynamic resolution off");
        expect(step_to(110, T("不限帧", "Unlimited"), 6) && nvn_fps_cap() == 0, "no cap");
        expect(fabsf(probe_drs_target - 16.7f) < 1e-3f, "uncapped restores the startup target");
        setenv("TOTK_DRS_TARGET_MS", "20", 1);
        expect(step_to(110, @"60 FPS", 6), "cap 60");
        expect(fabsf(probe_drs_target - 20) < 1e-3f, "explicit target wins as it does at startup");
        unsetenv("TOTK_DRS_TARGET_MS");
        expect(step_to(110, T("不限帧", "Unlimited"), 6), "no cap again");
        if (path) { Settings f = file_settings(path); expect(f.fps_cap == 0 && !f.drs && fabsf(f.drs_min - 0.8f) < 1e-4f, "cap and scale in settings.txt"); }
        int drs_calls = probe_drs_calls; settings_quick_value(110, NULL); settings_quick_status(); settings_quick_preset();
        expect(probe_drs_calls == drs_calls, "looking does not set anything");
    } else {
        /* greyed out, but a preset or a file can hold a cap for a build that has one: the quality preset's 60, then 90 */
        expect(is(110, @"60 FPS") && settings_quick_step(110, 1) && is(110, @"90 FPS"), "the cap steps in the model");
        if (path) expect(file_settings(path).fps_cap == 90, "the cap is kept in settings.txt");
    }

    /* Key 4, once the game has it: steps, fit included. */
    shortcut_test_aspect_init(1.6);
    int aspect = (settings_build_caps() & SETTINGS_CAN_ASPECT) != 0;
    expect(((row_flags(21) & SETTINGS_ROW_ENABLED) != 0) == aspect, "aspect: where key 4 is");
    if (aspect) {
        expect(settings_quick_step(21, 1) && runtime_aspect_step() == ASPECT_STEP_FIT && is(21, T("适配窗口", "Fit window")), "fit");
        expect(settings_quick_step(21, 1) && runtime_aspect_step() == ASPECT_STEP_WIDE && is(21, @"21:9"), "21:9");
        runtime_aspect_toggle(); expect(is(21, @"16:9"), "key 4 shows in the menu");
        expect(settings_quick_preset() == -1, "aspect is no preset's");
        expect(settings_quick_step(21, 1), "fit again");
        if (path) expect(file_settings(path).aspect == ASPECT_STEP_FIT, "the menu's last aspect choice is in settings.txt");
    }

    if (path) {
        NSString *blocked = [@(path) stringByAppendingPathComponent:@"settings.txt"];
        setenv("TOTK_SETTINGS", blocked.fileSystemRepresentation, 1);  /* parent is a regular file */
        expect(!settings_quick_step(23, 1) && settings_quick_saving() == -1, "save failure is visible");
        setenv("TOTK_SETTINGS", path, 1);
        expect(settings_quick_step(23, 1) && settings_quick_saving() == 1, "successful retry clears failure");
    }
    if (optional) {
        runtime_drs_set_min(0.8f);
        expect(is(112, @"80%"), "running DRS minimum wins over saved file");
        expect(settings_quick_apply(102) && fabsf(probe_drs_min - 0.67f) < 1e-4f, "preset applies minimum after external change");
        runtime_drs_set_min(0.9f);
        expect(is(112, @"90%"), "minimum follows external changes");
    }
    /* Presets against custom rows. */
    expect(settings_quick_apply(101), "quick balanced preset saves"); mfx_latch();
    expect(mfxup_output_enabled() && taa_enabled(), "quick preset applies to the game");
    expect(settings_quick_preset() == PRESET_BALANCED, "quick preset highlight matches complete balanced settings");
    expect(step_to(114, @"8×", 6), "anisotropic filtering 8x");
    expect(settings_quick_preset() == -1, "custom anisotropic filtering clears quick preset highlight");
    expect(settings_quick_apply(101), "restore balanced preset after custom anisotropic filtering"); mfx_latch();
    if (optional) {
        runtime_drs_set_min(0.8f);
        expect(settings_quick_preset() == -1, "custom DRS floor clears quick preset highlight");
        expect(settings_quick_apply(101), "restore balanced preset after custom DRS floor"); mfx_latch();
        expect(settings_quick_preset() == PRESET_BALANCED, "complete preset restores quick highlight");
    }
    expect(settings_quick_apply(23) && !taa_enabled(), "quick smoothing click applies");
    if (path) expect(!file_settings(path).taa, "quick smoothing click persists");
    expect(settings_quick_apply(19), "quick interpolation click saves before frame latch");
    if (path) expect(file_settings(path).interpolation == MFX_30, "pending interpolation persists correctly");
    mfx_latch(); expect(mfx_enabled() == MFX_30, "quick interpolation reaches next frame");
    if (optional) {
        expect(settings_quick_apply(110) && nvn_fps_cap() == 90, "quick cap cycles from 60 to 90");
        expect(settings_quick_apply(111) && runtime_drs_enabled(), "quick dynamic resolution enables");
        if (path) expect(file_settings(path).fps_cap == 90 && file_settings(path).drs, "cap and DRS persist together");
    }
    /* Previous/next arrows are inverse operations, including wraparound and skipped modes. */
    if (optional) {
        expect(settings_quick_step(110, -1) && nvn_fps_cap() == 60, "reverse cap 90 to 60");
        expect(step_to(110, @"30 FPS", 6), "cap 30");
        expect(settings_quick_step(110, -1) && nvn_fps_cap() == 0, "reverse cap wraps 30 to unlimited");
        expect(settings_quick_step(110, 1) && nvn_fps_cap() == 30, "forward cap reverses wrap");
        if (path) expect(file_settings(path).fps_cap == 30, "reverse/forward cap saves current choice");
    }
    runtime_output_mode_set(PICTURE_OFF);
    expect(settings_quick_step(20, -1) && canvas_2k() && !mfxup_output_enabled(), "reverse picture wraps off to native");
    expect(settings_quick_step(20, -1) && mfxup_output_enabled(), "reverse picture native to MetalFX");
    expect(settings_quick_step(20, -1) && !mfxup_output_enabled() && !canvas_2k(), "reverse picture MetalFX to off");
    if (aspect) {
        const double views[] = {1.6, 16.0 / 9.0, 21.0 / 9.0};
        for (unsigned i = 0; i < sizeof(views) / sizeof(views[0]); i++) {
            shortcut_test_aspect_init(views[i]);
            expect(settings_quick_step(21, -1) && runtime_aspect_step() == ASPECT_STEP_WIDE, "reverse aspect from standard reaches wide");
            expect(settings_quick_step(21, -1) && runtime_aspect_step() == (i ? ASPECT_STEP_GAME : ASPECT_STEP_FIT), "reverse aspect skips duplicate fit");
            expect(settings_quick_step(21, 1) && runtime_aspect_step() == ASPECT_STEP_WIDE, "forward restores reverse aspect");
            if (path) expect(file_settings(path).aspect == ASPECT_STEP_WIDE, "reverse aspect saves actual runtime state");
        }
    }
    /* A 1080p-only runtime must cycle MetalFX back to off, skipping unavailable native 2K. */
    shortcut_test_disable_native(); runtime_output_mode_set(PICTURE_OFF);
    expect(settings_quick_apply(20) && mfxup_output_enabled(), "quick picture enables MetalFX without native 2K");
    expect(settings_quick_apply(20) && !mfxup_output_enabled(), "quick picture can turn MetalFX back off without native 2K");
    expect(settings_quick_step(20, -1) && mfxup_output_enabled(), "reverse picture skips absent native mode");
    expect(settings_quick_step(20, -1) && !mfxup_output_enabled(), "reverse picture returns off without native");
    expect(!settings_quick_step(999, 1), "an unknown row changes nothing");
#undef T
    if (failures) return 1;
    printf("pass: settings menu model (%s, %s, %s, %s)\n", optional ? "with cap and resolution controller" : "without them (greyed out)",
           v143 ? "1.4.3" : "1.0.0 rules", path ? "settings.txt written" : "no settings.txt", zh ? "zh" : "en");
    return 0;
}}
