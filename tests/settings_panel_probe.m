/* The settings window (games/totk/runtime/settings_panel.m) without the game: the real panel, built but never shown, driven
   through its controls. The key 2 / 3 / 4 / 5 state behind it is the production code (totk_mfx.m, totk_mfx_up.m, totk_taa.m,
   game_patches*.c with a synthetic output page: tests/shortcut_output_fixture.c). The frame-rate cap and the resolution
   controller are other features: tests/settings_panel_optional.c stands in for them, or they are missing (NULL) when it is
   not linked. argv[1]: the settings.txt to write (TOTK_SETTINGS), or "-" for a run without it. */
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
void dm_gfx_set_flag(const char *name, int value) {   /* the flags key 3 and the window's picture modes use */
    if (!strcmp(name, "mfx_output")) mfxup_output_set(value);
    else if (!strcmp(name, "mfx_upscale")) mfxup_set(value);
    else if (!strcmp(name, "mfx_interp")) mfx_set(value);
    else abort();
}
int dm_gfx_fps_now(int *generated) { if (generated) *generated = 0; return 82; }
void runtime_oe_push_message(uint32_t message) { (void)message; }
/* What the window asked of the cap and the resolution controller (tests/settings_panel_optional.c counts, when linked). */
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
static void pick(NSPopUpButton *p, NSInteger tag, TOTKSettings *c) { expect([p selectItemWithTag:tag], "the popup offers it"); [c changed:p]; }
static void segment(NSSegmentedControl *s, NSInteger i, TOTKSettings *c) { s.selectedSegment = i; [c changed:s]; }
static void check(NSButton *b, int on, TOTKSettings *c) { b.state = on ? NSControlStateValueOn : NSControlStateValueOff; [c changed:b]; }
static int canvas_2k(void) { return runtime_output_size_current() == ((uint64_t)1440 << 32 | 2560); }

int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];   /* nothing on screen */
    const char *path = strcmp(argv[1], "-") ? argv[1] : NULL;
    if (path) setenv("TOTK_SETTINGS", path, 1); else unsetenv("TOTK_SETTINGS");
    shortcut_test_output_init();
    int optional = nvn_set_fps_cap != NULL, v143 = (settings_build_caps() & SETTINGS_CAN_RENDER_RES) != 0, zh = totk_ui_zh();
    expect(optional == (runtime_drs_set != NULL) && optional == (runtime_drs_scale != NULL), "the optional features come together here");

    /* The app menu's item: Command-, opens the window. */
    NSMenu *menu = [NSMenu new]; settings_panel_menu(menu);
    NSMenuItem *item = menu.itemArray.firstObject;
    expect(menu.numberOfItems == 2 && menu.itemArray[1].isSeparatorItem, "the item and a separator");
    expect([item.keyEquivalent isEqualToString:@","] && item.keyEquivalentModifierMask == NSEventModifierFlagCommand, "Command-,");
    expect(item.target == settingsController && item.action == @selector(open:), "it opens the window");
    expect([item.title isEqualToString:zh ? @"设置…" : @"Settings…"], "its title");

    /* Opened without a file: the running game's state, no preset (no cap), nothing written. */
    TOTKSettings *c = settingsController; [c prepare];
    expect(c.panel && !c.panel.visible, "built, not shown");
    expect(c.preset.selectedSegment == PRESET_CUSTOM && c.picture.selectedSegment == PICTURE_OFF && c.output.selectedSegment == CANVAS_1080P &&
           c.taa.state == NSControlStateValueOff && c.interp.selectedTag == MFX_OFF, "the running state");
    expect(!path || ![NSFileManager.defaultManager fileExistsAtPath:@(path)], "opening writes nothing");
    expect(c.fpsCap.enabled == optional && c.drs.enabled == optional && (optional || (c.fpsCap.toolTip.length && c.drs.toolTip.length)),
           "the cap and dynamic resolution rows: greyed out with a reason when the build has none");
    expect(!c.drsMin.enabled, "the lowest scale waits for dynamic resolution");
    expect(c.renderRes.enabled == v143 && (v143 || c.renderRes.toolTip.length), "render resolution: 1.4.3");
    expect(c.output.enabled && [c.picture isEnabledForSegment:PICTURE_NATIVE], "native 2K: the 2K swapchain is there");
    expect(!c.aspect.enabled, "key 4 not installed: aspect greyed out");
    expect([c.now.stringValue containsString:@"82 FPS"] && [c.now.stringValue containsString:@"1920×1080"], "the now line");
    expect([[c.preset labelForSegment:PRESET_BALANCED] isEqualToString:zh ? @"均衡" : @"Balanced"], "preset labels");

    /* 均衡: MetalFX 2K, edge smoothing, the cap; written as balanced. */
    c.preset.selectedSegment = PRESET_BALANCED; [c presetChanged:c.preset];
    expect(mfxup_output_enabled() && mfxup_enabled() && !canvas_2k() && taa_enabled(), "balanced in the running game");
    expect(!optional || (nvn_fps_cap() == 60 && probe_cap_calls == 1 && !runtime_drs_enabled()), "balanced: cap 60");
    if (path) {
        Settings f = file_settings(path);
        expect(f.preset == PRESET_BALANCED && f.picture == PICTURE_METALFX && f.taa && f.aniso == 16 && f.fps_cap == 60, "balanced in settings.txt");
        expect([file_text(path) containsString:@"preset = balanced"], "the file names the preset");
    }
    expect(c.preset.selectedSegment == PRESET_BALANCED && c.picture.selectedSegment == PICTURE_METALFX && c.taa.state == NSControlStateValueOn, "the window shows it");

    /* 画质: native 2K canvas without MetalFX, dynamic resolution down to 0.67 aiming at 1000 / 60 ms. */
    c.preset.selectedSegment = PRESET_QUALITY; [c presetChanged:c.preset];
    expect(canvas_2k() && !mfxup_output_enabled() && !mfxup_enabled() && taa_enabled(), "quality: native 2K");
    expect(!optional || (runtime_drs_enabled() && fabsf(probe_drs_min - 0.67f) < 1e-4f && fabsf(probe_drs_target - 1000.0f / 60) < 1e-3f), "quality: dynamic resolution");
    expect(c.output.selectedSegment == CANVAS_2K && c.drsMin.enabled == optional, "the canvas follows; the lowest scale opens");
    if (path) { Settings f = file_settings(path); expect(f.preset == PRESET_QUALITY && f.render_w == 2560 && f.drs, "quality in settings.txt"); }
    if (v143) expect([c.renderNote.textColor isEqual:NSColor.systemOrangeColor], "render resolution: differs from this run's, restart");

    /* One option changed: custom. */
    check(c.taa, 0, c);
    expect(!taa_enabled() && c.preset.selectedSegment == PRESET_CUSTOM, "edge smoothing off: custom");
    if (path) expect(file_settings(path).preset == PRESET_CUSTOM && !file_settings(path).taa, "custom in settings.txt");

    /* Key 3 behind the window (the production cycle): the window follows at its next look and writes nothing. */
    NSString *before = path ? file_text(path) : nil;
    runtime_output_mode_cycle();   /* native 2K -> off */
    [c tick];
    expect(c.picture.selectedSegment == PICTURE_OFF && c.output.selectedSegment == CANVAS_1080P && !canvas_2k(), "key 3 shows in the window");
    expect(!path || [file_text(path) isEqualToString:before], "a key's change is not written by itself");
    runtime_output_mode_cycle();   /* off -> MetalFX 2K */
    [c tick];
    expect(c.picture.selectedSegment == PICTURE_METALFX, "key 3 again");

    /* Frame interpolation takes effect at the next game frame: the window keeps the choice meanwhile. */
    pick(c.interp, MFX_30, c);
    [c tick]; expect(c.interp.selectedTag == MFX_30 && mfx_enabled() == MFX_OFF, "requested, not latched yet: the choice stays");
    mfx_latch(); [c tick]; expect(c.interp.selectedTag == MFX_30 && mfx_enabled() == MFX_30, "latched");
    mfx_set(MFX_MAX); mfx_latch(); [c tick]; expect(c.interp.selectedTag == MFX_MAX, "key 2 shows in the window");

    /* Canvas and picture mode in step, from either control; MetalFX 2K -> off never lays out in 2K. */
    segment(c.output, CANVAS_2K, c);
    expect(canvas_2k() && c.picture.selectedSegment == PICTURE_NATIVE && !mfxup_output_enabled(), "2K canvas: native 2K");
    segment(c.output, CANVAS_1080P, c);
    expect(!canvas_2k() && c.picture.selectedSegment == PICTURE_OFF, "1080p canvas: off");
    segment(c.picture, PICTURE_METALFX, c);
    expect(!canvas_2k() && mfxup_output_enabled() && c.output.selectedSegment == CANVAS_1080P, "MetalFX 2K keeps the 1080p canvas");
    segment(c.picture, PICTURE_OFF, c);
    expect(!canvas_2k() && !mfxup_output_enabled() && !mfxup_enabled(), "off directly");

    /* Read at start: written, marked for the next start. */
    pick(c.aniso, 8, c);
    expect([c.anisoNote.textColor isEqual:NSColor.systemOrangeColor], "anisotropic filtering: restart");
    if (v143) { pick(c.renderRes, 1920 << 16 | 1080, c); }
    if (path) { Settings f = file_settings(path); expect(f.aniso == 8 && (!v143 || (f.render_w == 1920 && f.render_h == 1080)), "start-only keys in settings.txt"); }
    pick(c.aniso, 0, c);
    expect([c.anisoNote.textColor isEqual:NSColor.secondaryLabelColor], "back to this run's: no restart needed");

    /* The cap and the lowest scale. */
    if (optional) {
        pick(c.fpsCap, 40, c);
        probe_cap_paused = 1; [c tick];
        expect([c.now.stringValue containsString:zh ? @"限帧暂停" : @"cap paused"] && c.fpsCap.selectedTag == 40, "paused cap keeps choice and reports actual pacing");
        probe_cap_paused = 0; [c tick];
        expect(nvn_fps_cap() == 40 && fabsf(probe_drs_target - 25.0f) < 1e-3f, "cap 40: the controller aims at 25 ms");
        c.drsMin.doubleValue = 0.8; [c changed:c.drsMin];
        expect(fabsf(probe_drs_min - 0.8f) < 1e-4f && [c.drsMinValue.stringValue isEqualToString:@"80%"], "lowest scale 0.8");
        check(c.drs, 0, c); expect(!runtime_drs_enabled() && !c.drsMin.enabled, "dynamic resolution off");
        pick(c.fpsCap, 0, c); expect(nvn_fps_cap() == 0, "no cap");
        expect(fabsf(probe_drs_target - 16.7f) < 1e-3f, "uncapped restores the startup target");
        setenv("TOTK_DRS_TARGET_MS", "20", 1);
        pick(c.fpsCap, 60, c);
        expect(fabsf(probe_drs_target - 20) < 1e-3f, "explicit target wins as it does at startup");
        unsetenv("TOTK_DRS_TARGET_MS");
        pick(c.fpsCap, 0, c);
        if (path) { Settings f = file_settings(path); expect(f.fps_cap == 0 && !f.drs && fabsf(f.drs_min - 0.8f) < 1e-4f, "cap and scale in settings.txt"); }
        int drs_calls = probe_drs_calls; [c tick]; expect(probe_drs_calls == drs_calls, "looking does not set anything");
    } else {
        pick(c.fpsCap, 40, c);   /* greyed out, but a preset or a file can still hold a cap for a build that has one */
        if (path) expect(file_settings(path).fps_cap == 40, "the cap is kept in settings.txt");
    }

    /* Key 4, once the game has it: steps directly, fit included. */
    shortcut_test_aspect_init(1.6);
    [c prepare];
    int aspect = (settings_build_caps() & SETTINGS_CAN_ASPECT) != 0;
    expect(c.aspect.enabled == aspect, "aspect: where key 4 is");
    if (aspect) {
        segment(c.aspect, ASPECT_STEP_WIDE, c); expect(runtime_aspect_step() == ASPECT_STEP_WIDE && runtime_aspect_now() > 2.3f, "21:9");
        segment(c.aspect, ASPECT_STEP_FIT, c); expect(runtime_aspect_step() == ASPECT_STEP_FIT && fabsf(runtime_aspect_now() - 1.6f) < 1e-3f, "fit");
        runtime_aspect_toggle(); [c tick]; expect(c.aspect.selectedSegment == ASPECT_STEP_WIDE, "key 4 shows in the window");
        expect(c.preset.selectedSegment == PRESET_CUSTOM, "aspect is no preset's");
        if (path) expect(file_settings(path).aspect == ASPECT_STEP_FIT, "the window's last aspect choice is in settings.txt");
    }

    /* Reopened: settings.txt and the running game agree with what the window showed. */
    Settings shown = model; [c prepare];
    expect(model.picture == shown.picture && model.taa == shown.taa && model.interpolation == shown.interpolation &&
           model.aniso == shown.aniso && model.render_w == shown.render_w && model.fps_cap == shown.fps_cap, "reopened: the same state");

    if (path) {
        NSString *blocked = [@(path) stringByAppendingPathComponent:@"settings.txt"];
        setenv("TOTK_SETTINGS", blocked.fileSystemRepresentation, 1);  /* parent is a regular file */
        check(c.taa, !model.taa, c);
        expect(settingsSaveFailed && [c.footer.textColor isEqual:NSColor.systemOrangeColor], "save failure is visible");
        setenv("TOTK_SETTINGS", path, 1);
        check(c.taa, !model.taa, c);
        expect(!settingsSaveFailed && [c.footer.textColor isEqual:NSColor.secondaryLabelColor], "successful retry clears failure");
    }
    if (optional) {
        runtime_drs_set_min(0.8f);
        [c prepare];
        expect(fabsf(model.drs_min - 0.8f) < 1e-4f, "running DRS minimum wins over saved file");
        c.preset.selectedSegment = PRESET_QUALITY; [c presetChanged:c.preset];
        expect(fabsf(probe_drs_min - 0.67f) < 1e-4f, "preset applies minimum after external change");
        runtime_drs_set_min(0.9f); [c tick];
        expect(fabsf(model.drs_min - 0.9f) < 1e-4f, "minimum follows external changes while open");
    }
    /* The in-game mouse menu uses the same persisted/live model. */
    expect(settings_quick_apply(101), "quick balanced preset saves"); mfx_latch();
    expect(mfxup_output_enabled() && taa_enabled(), "quick preset applies to the game");
    expect(settings_quick_apply(23) && !taa_enabled(), "quick smoothing click applies");
    if(path) expect(!file_settings(path).taa, "quick smoothing click persists");
    expect(settings_quick_apply(19), "quick interpolation click saves before frame latch");
    if(path) expect(file_settings(path).interpolation == MFX_30, "pending interpolation persists correctly");
    mfx_latch();expect(mfx_enabled()==MFX_30, "quick interpolation reaches next frame");
    if(optional) {
        expect(settings_quick_apply(110) && nvn_fps_cap()==90, "quick cap cycles from 60 to 90");
        expect(settings_quick_apply(111) && runtime_drs_enabled(), "quick dynamic resolution enables");
        if(path) expect(file_settings(path).fps_cap==90 && file_settings(path).drs, "cap and DRS persist together");
    }
    /* A 1080p-only runtime must cycle MetalFX back to off, skipping unavailable native 2K. */
    shortcut_test_disable_native();runtime_output_mode_set(PICTURE_OFF);
    expect(settings_quick_apply(20) && mfxup_output_enabled(), "quick picture enables MetalFX without native 2K");
    expect(settings_quick_apply(20) && !mfxup_output_enabled(), "quick picture can turn MetalFX back off without native 2K");
    [c.panel close];
    if (failures) return 1;
    printf("pass: settings window (%s, %s, %s, %s)\n", optional ? "with cap and resolution controller" : "without them (greyed out)",
           v143 ? "1.4.3" : "1.0.0 rules", path ? "settings.txt written" : "no settings.txt", zh ? "zh" : "en");
    return 0;
}}
