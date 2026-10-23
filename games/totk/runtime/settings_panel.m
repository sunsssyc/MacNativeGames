/* The settings window (issue #288; the app menu's "设置…", Command-,): presets that make a steady 60 one click, and every
   option of runtime/settings_file.h in one place instead of number keys and variables only open --env can give.
   - What the runtime can change while playing applies at once: the frame rate cap, dynamic resolution (on / off, its
     lowest scale, its frame-time target = 1000 / cap), edge smoothing (key 5), frame interpolation (key 2), the picture
     mode and canvas (key 3) and the aspect ratio (key 4), through the same functions as the keys (direct setters beside
     their cycles). The render resolution and anisotropic filtering are read at start: their rows say "重启游戏后生效",
     in orange while the choice differs from what this run started with.
   - Every change is written to settings.txt (TOTK_SETTINGS, set by the launcher), which the next start reads; a run
     without TOTK_SETTINGS (a test, a run from the terminal) writes nothing.
   - The window shows the state in force: when it opens and twice a second while it is open, what the game reports wins,
     so a change made with keys 2-5 shows here. Keys keep working; their changes are written only with the next change
     made here.
   - The frame rate cap and the resolution controller are separate features: a build without them leaves their functions
     NULL (weak references the Makefile lets stay undefined, -Wl,-U) and greys their rows out.
   The panel floats above the game window, also in full screen, and takes the keyboard (the game window lets the mouse go
   while it is open); Esc or the close button gives the game window the keyboard back. */
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
int dm_gfx_fps_now(int *generated);   /* gfx/nvn/nvn_mtl.m: the overlay's frame rate */
int taa_enabled(void);                /* gfx/nvn/totk_taa.m: key 5 */
void taa_set(int on);
void mfx_set(int mode);               /* gfx/nvn/totk_mfx.m: key 2 (mfx_enabled: totk_mfx_mode.h) */
int mfxup_output_enabled(void);       /* gfx/nvn/totk_mfx_up.m: key 3's MetalFX 2K */

static Settings model;   /* what the window shows and writes */
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

/* When the window opens: what this run started with (the first time; later, what the window last showed), then
   settings.txt (what the next start will take), then what the game reports now for the keys it can change while playing. */
static void model_load(void) {
    static int loaded;
    if (!loaded) {
        loaded = 1; settings_defaults(&model);
        const char *e;
        if ((e = getenv("TOTK_FPS_CAP"))) model.fps_cap = atoi(e);
        if ((e = getenv("TOTK_DRS"))) model.drs = atoi(e) != 0;
        if ((e = getenv("TOTK_DRS_MIN"))) model.drs_min = (float)atof(e);
        int aniso; started_with(&model.render_w, &model.render_h, &aniso); model.aniso = aniso;
    }
    NSString *path = settings_path();
    NSData *data = path ? [NSData dataWithContentsOfFile:path] : nil;
    if (data) {
        NSString *text = data.length < 16384 ? [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] : nil;
        Settings file = model; const char *error = "not UTF-8 text, or larger than 16 KB";
        int line = text ? settings_parse(text.UTF8String, &file, &error) : 1;
        if (line) fprintf(stderr, "[totk] settings: %s line %d: %s; the window starts from the running game\n", path.UTF8String, line, error);
        else model = file;
    }
    seen = model; live_read(&seen);
    model.fps_cap = seen.fps_cap; model.drs = seen.drs; model.drs_min = seen.drs_min; model.picture = seen.picture; model.output = seen.output;
    model.taa = seen.taa; model.interpolation = seen.interpolation; model.aspect = seen.aspect;
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

static NSTextField *settings_note(NSString *text) {
    NSTextField *t = [NSTextField labelWithString:text];
    t.font = [NSFont systemFontOfSize:NSFont.smallSystemFontSize]; t.textColor = NSColor.secondaryLabelColor;
    return t;
}
static NSPopUpButton *settings_popup(NSArray<NSString *> *titles, const int *tags, id target, SEL action) {
    NSPopUpButton *p = [[NSPopUpButton alloc] initWithFrame:NSZeroRect pullsDown:NO];
    for (NSUInteger i = 0; i < titles.count; i++) { [p addItemWithTitle:titles[i]]; p.lastItem.tag = tags[i]; }
    p.target = target; p.action = action;
    return p;
}
/* Selects the item with tag, added with title first when the value is none of the offered ones (a file written by hand). */
static void settings_popup_show(NSPopUpButton *p, NSInteger tag, NSString *title) {
    if ([p selectItemWithTag:tag]) return;
    [p addItemWithTitle:title]; p.lastItem.tag = tag; [p selectItemWithTag:tag];
}
static NSStackView *settings_row(NSArray<NSView *> *views) {
    NSStackView *s = [NSStackView stackViewWithViews:views];
    s.orientation = NSUserInterfaceLayoutOrientationHorizontal; s.spacing = 8; s.alignment = NSLayoutAttributeCenterY;
    return s;
}
/* A label whose text changes while the window is open: it is truncated rather than resizing the window. */
static void settings_changing(NSTextField *t) {
    t.lineBreakMode = NSLineBreakByTruncatingTail;
    [t setContentCompressionResistancePriority:NSLayoutPriorityDefaultLow forOrientation:NSLayoutConstraintOrientationHorizontal];
}
static const char *const settings_preset_notes[][2] = {
    {"帧率上限 60 · 游戏自身渲染分辨率 · 1080p · 不开边缘平滑 · 16× 各向异性过滤", "60 fps cap · the game's own render size · 1080p · no edge smoothing · 16x anisotropic filtering"},
    {"帧率上限 60 · MetalFX 2K（1080p 渲染后放大）· 边缘平滑 · 16× 各向异性过滤", "60 fps cap · MetalFX 2K (1080p upscaled) · edge smoothing · 16x anisotropic filtering"},
    {"帧率上限 60 · 2560×1440 渲染 · 原生 2K · 动态分辨率（最低 67%）· 边缘平滑 · 16× 各向异性", "60 fps cap · 2560×1440 render · native 2K · dynamic resolution (down to 67%) · edge smoothing · 16x aniso"},
    {"你自己的组合；点一个预设可一键换回", "Your own combination; click a preset to go back to one"}};

@interface TOTKSettingsPanel : NSPanel
@end
@implementation TOTKSettingsPanel
-(void)cancelOperation:(id)sender { (void)sender; [self performClose:nil]; }   /* Esc */
@end

@interface TOTKSettings : NSObject <NSWindowDelegate>
@property(strong) TOTKSettingsPanel *panel;
@property(strong) NSSegmentedControl *preset, *output, *picture, *aspect;
@property(strong) NSPopUpButton *fpsCap, *renderRes, *aniso, *interp;
@property(strong) NSButton *drs, *taa;
@property(strong) NSSlider *drsMin;
@property(strong) NSTextField *presetNote, *drsMinValue, *renderNote, *anisoNote, *now, *footer;
@property(strong) NSTimer *timer;
-(void)open:(id)sender;                                /* the menu item: fills the window and shows it */
-(void)prepare;                                        /* builds it if needed and fills it, without showing it */
-(void)presetChanged:(NSSegmentedControl *)control;   /* the controls' actions */
-(void)changed:(id)control;
-(void)tick;                                           /* twice a second while open */
@end

@implementation TOTKSettings
-(void)build {
    if (self.panel) return;
    self.preset = [NSSegmentedControl segmentedControlWithLabels:@[@(TOTK_UI("性能", "Performance")), @(TOTK_UI("均衡", "Balanced")),
        @(TOTK_UI("画质", "Quality")), @(TOTK_UI("自定义", "Custom"))] trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(presetChanged:)];
    self.presetNote = settings_note(@"");
    static const int caps[] = {0, 30, 40, 60, 90, 120};
    self.fpsCap = settings_popup(@[@(TOTK_UI("不限", "No cap")), @"30", @"40", @"60", @"90", @"120"], caps, self, @selector(changed:));
    self.drs = [NSButton checkboxWithTitle:@(TOTK_UI("开启（帧时间超过上限时降低渲染分辨率）", "On (lowers the render resolution when a frame takes longer than the cap)")) target:self action:@selector(changed:)];
    self.drsMin = [NSSlider sliderWithValue:0.67 minValue:0.5 maxValue:1.0 target:self action:@selector(changed:)];
    self.drsMin.continuous = YES; [self.drsMin.widthAnchor constraintEqualToConstant:180].active = YES;
    self.drsMinValue = [NSTextField labelWithString:@"67%"];
    static const int renders[] = {0, 1920 << 16 | 1080, 2560 << 16 | 1440};
    self.renderRes = settings_popup(@[@(TOTK_UI("游戏自身（1600×900）", "The game's own (1600×900)")), @"1920×1080", @"2560×1440"], renders, self, @selector(changed:));
    self.renderNote = settings_note(@(TOTK_UI("重启游戏后生效", "After a restart")));
    self.output = [NSSegmentedControl segmentedControlWithLabels:@[@"1080p", @"2K"] trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(changed:)];
    self.picture = [NSSegmentedControl segmentedControlWithLabels:@[@(TOTK_UI("关闭", "Off")), @"MetalFX 2K", @(TOTK_UI("原生 2K", "Native 2K"))]
                                                     trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(changed:)];
    self.taa = [NSButton checkboxWithTitle:@(TOTK_UI("MetalFX 时间性抗锯齿", "MetalFX temporal anti-aliasing")) target:self action:@selector(changed:)];
    static const int anisos[] = {0, 2, 4, 8, 16};
    self.aniso = settings_popup(@[@(TOTK_UI("关闭（游戏自身）", "Off (the game's own)")), @"2×", @"4×", @"8×", @"16×"], anisos, self, @selector(changed:));
    self.anisoNote = settings_note(@(TOTK_UI("重启游戏后生效", "After a restart")));
    static const int interps[] = {MFX_OFF, MFX_30, MFX_HALF, MFX_MAX};
    self.interp = settings_popup(@[@(TOTK_UI("关闭", "Off")), @"30+30", @(TOTK_UI("刷新率一半", "Half refresh rate")), @(TOTK_UI("不限帧", "Unlimited"))], interps, self, @selector(changed:));
    self.aspect = [NSSegmentedControl segmentedControlWithLabels:@[@"16:9", @(TOTK_UI("适配窗口", "Fit window")), @"21:9"]
                                                    trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(changed:)];
    /* the window is sized once, for the longest texts of these labels (the notes of the quality preset, a busy "当前") */
    self.presetNote.stringValue = @(TOTK_UI(settings_preset_notes[PRESET_QUALITY][0], settings_preset_notes[PRESET_QUALITY][1]));
    self.now = [NSTextField labelWithString:@(TOTK_UI("120+120 FPS · 上限 120 · 分辨率 100% · 画布 2560×1440", "120+120 FPS · cap 120 · resolution 100% · canvas 2560×1440"))];
    self.now.font = [NSFont monospacedDigitSystemFontOfSize:NSFont.systemFontSize weight:NSFontWeightRegular];
    settings_changing(self.presetNote); settings_changing(self.now);
    self.footer = settings_note(@(TOTK_UI("这次启动没有 settings.txt（不是从 App 启动）：改动只在游戏关闭前有效。",
                                          "This run has no settings.txt (not started from the app): changes last until the game closes.")));
    NSArray *rows = @[
        @[[NSTextField labelWithString:@(TOTK_UI("预设", "Preset"))], self.preset],
        @[NSGridCell.emptyContentView, self.presetNote],
        @[[NSTextField labelWithString:@(TOTK_UI("帧率上限", "Frame rate cap"))], self.fpsCap],
        @[[NSTextField labelWithString:@(TOTK_UI("动态分辨率", "Dynamic resolution"))], self.drs],
        @[[NSTextField labelWithString:@(TOTK_UI("最低分辨率", "Lowest resolution"))], settings_row(@[self.drsMin, self.drsMinValue])],
        @[[NSTextField labelWithString:@(TOTK_UI("渲染分辨率", "Render resolution"))], settings_row(@[self.renderRes, self.renderNote])],
        @[[NSTextField labelWithString:@(TOTK_UI("输出画布", "Output canvas"))], self.output],
        @[[NSTextField labelWithString:@(TOTK_UI("画面（3 键）", "Picture (key 3)"))], self.picture],
        @[[NSTextField labelWithString:@(TOTK_UI("边缘平滑（5 键）", "Edge smoothing (key 5)"))], self.taa],
        @[[NSTextField labelWithString:@(TOTK_UI("各向异性过滤", "Anisotropic filtering"))], settings_row(@[self.aniso, self.anisoNote])],
        @[[NSTextField labelWithString:@(TOTK_UI("补帧（2 键）", "Frame interpolation (key 2)"))], self.interp],
        @[[NSTextField labelWithString:@(TOTK_UI("画面比例（4 键）", "Aspect ratio (key 4)"))], self.aspect],
        @[[NSTextField labelWithString:@(TOTK_UI("当前", "Now"))], self.now],
    ];
    NSGridView *grid = [NSGridView gridViewWithViews:rows];
    grid.rowSpacing = 10; grid.columnSpacing = 12; grid.yPlacement = NSGridCellPlacementCenter;
    [grid columnAtIndex:0].xPlacement = NSGridCellPlacementTrailing;
    NSStackView *content = [NSStackView stackViewWithViews:@[grid, self.footer]];
    content.orientation = NSUserInterfaceLayoutOrientationVertical; content.alignment = NSLayoutAttributeLeading; content.spacing = 14;
    content.edgeInsets = NSEdgeInsetsMake(18, 20, 18, 20);
    self.footer.preferredMaxLayoutWidth = grid.fittingSize.width; self.footer.lineBreakMode = NSLineBreakByWordWrapping; self.footer.maximumNumberOfLines = 0;
    NSSize size = content.fittingSize;
    TOTKSettingsPanel *p = [[TOTKSettingsPanel alloc] initWithContentRect:NSMakeRect(0, 0, size.width, size.height)
                                                                styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                                                                  backing:NSBackingStoreBuffered defer:YES];
    p.title = @(TOTK_UI("设置", "Settings")); p.contentView = content; p.releasedWhenClosed = NO; p.delegate = self;
    p.floatingPanel = YES; p.hidesOnDeactivate = YES;   /* above the game window; away with the app, back with it */
    p.collectionBehavior = NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorMoveToActiveSpace;   /* over a full-screen game */
    self.panel = p;
}
/* Every control from the model, what this build and run allow, and the restart notes. */
-(void)show {
    unsigned caps = settings_build_caps();
    int preset = settings_matching_preset(&model);
    self.preset.selectedSegment = preset;
    self.presetNote.stringValue = @(TOTK_UI(settings_preset_notes[preset][0], settings_preset_notes[preset][1]));

    settings_popup_show(self.fpsCap, model.fps_cap, [NSString stringWithFormat:@"%d", model.fps_cap]);
    self.fpsCap.enabled = nvn_set_fps_cap != NULL;
    self.fpsCap.toolTip = nvn_set_fps_cap ? nil : @(TOTK_UI("这个版本还没有帧率上限功能；预设的上限会存进 settings.txt", "This build has no frame rate cap yet; a preset's cap is kept in settings.txt"));
    self.drs.state = model.drs ? NSControlStateValueOn : NSControlStateValueOff;
    self.drs.enabled = runtime_drs_set != NULL;
    self.drs.toolTip = runtime_drs_set ? nil : @(TOTK_UI("这个版本还没有动态分辨率功能", "This build has no dynamic resolution yet"));
    self.drsMin.doubleValue = model.drs_min; self.drsMinValue.stringValue = [NSString stringWithFormat:@"%.0f%%", model.drs_min * 100];
    self.drsMin.enabled = runtime_drs_set_min != NULL && model.drs;
    self.drsMin.toolTip = runtime_drs_set_min ? @(TOTK_UI("动态分辨率可以降到的最低比例", "How far dynamic resolution may go down")) : self.drs.toolTip;

    unsigned rw, rh; int aniso; started_with(&rw, &rh, &aniso);
    settings_popup_show(self.renderRes, (NSInteger)(model.render_w << 16 | model.render_h), [NSString stringWithFormat:@"%u×%u", model.render_w, model.render_h]);
    self.renderRes.enabled = (caps & SETTINGS_CAN_RENDER_RES) != 0;
    self.renderRes.toolTip = caps & SETTINGS_CAN_RENDER_RES ? nil : @(TOTK_UI("只有 1.4.3 能改渲染分辨率", "Only 1.4.3 can change the render resolution"));
    self.renderNote.textColor = model.render_w != rw || model.render_h != rh ? NSColor.systemOrangeColor : NSColor.secondaryLabelColor;
    settings_popup_show(self.aniso, model.aniso, [NSString stringWithFormat:@"%d×", model.aniso]);
    self.anisoNote.textColor = model.aniso != aniso ? NSColor.systemOrangeColor : NSColor.secondaryLabelColor;

    int native = (caps & SETTINGS_CAN_NATIVE_2K) && native_this_run();
    NSString *noNative = !(caps & SETTINGS_CAN_NATIVE_2K) ? @(TOTK_UI("这个游戏还没有原生 2K", "No native 2K in this game yet"))
                       : native ? nil : @(TOTK_UI("这次启动没有 2K 画布（TOTK_OUTPUT_RES=0，或缺少 2K 堆布局）", "This run has no 2K canvas (TOTK_OUTPUT_RES=0, or the 2K heap layout is missing)"));
    self.output.selectedSegment = model.output; self.output.enabled = native; self.output.toolTip = noNative;
    self.picture.selectedSegment = model.picture; [self.picture setEnabled:native forSegment:PICTURE_NATIVE];
    [self.picture setToolTip:noNative forSegment:PICTURE_NATIVE];
    self.taa.state = model.taa ? NSControlStateValueOn : NSControlStateValueOff;
    [self.interp selectItemWithTag:model.interpolation];
    int aspects = aspect_this_run();
    self.aspect.selectedSegment = model.aspect; self.aspect.enabled = aspects;
    self.aspect.toolTip = aspects ? nil : @(TOTK_UI("这个版本没有 4 键画面比例", "This version has no key-4 aspect ratio"));
    int fit = aspects && (caps & SETTINGS_CAN_ASPECT_FIT);
    [self.aspect setEnabled:fit forSegment:ASPECT_STEP_FIT];
    [self.aspect setToolTip:fit || !aspects ? nil : @(TOTK_UI("这个游戏的 4 键只有 16:9 和 21:9", "Key 4 has only 16:9 and 21:9 in this game")) forSegment:ASPECT_STEP_FIT];

    self.footer.textColor = settingsSaveFailed ? NSColor.systemOrangeColor : NSColor.secondaryLabelColor;
    self.footer.stringValue = settingsSaveFailed ? @(TOTK_UI("无法保存 settings.txt；本次改动未保存，下一次修改时会重试。",
                                                          "Could not save settings.txt; this change was not saved. The next change will retry."))
                               : settings_path() ? @(TOTK_UI("每次改动立即保存到 settings.txt，下次启动沿用。数字键 1–7 照常可用。",
                                                          "Every change is saved to settings.txt at once and used at the next start. Keys 1–7 work as before."))
                                              : @(TOTK_UI("这次启动没有 settings.txt（不是从 App 启动）：改动只在游戏关闭前有效。",
                                                          "This run has no settings.txt (not started from the app): changes last until the game closes."));
    [self showNow];
}
/* "当前": the frame rate the overlay shows, the cap and the resolution scale in force, the canvas. */
-(void)showNow {
    int generated = 0, fps = dm_gfx_fps_now(&generated);
    NSMutableArray<NSString *> *parts = [NSMutableArray array];
    [parts addObject:fps < 0 ? @"-- FPS" : generated > 0 ? [NSString stringWithFormat:@"%d+%d FPS", fps, generated] : [NSString stringWithFormat:@"%d FPS", fps]];
    if (nvn_fps_cap) { int cap = nvn_fps_cap(); [parts addObject:cap > 0 ? [NSString stringWithFormat:@(TOTK_UI("上限 %d", "cap %d")), cap] : @(TOTK_UI("不限帧率", "no cap"))]; }
    if (nvn_fps_cap && nvn_fps_cap() > 0 && nvn_fps_cap_pacing && !nvn_fps_cap_pacing())
        [parts addObject:@(TOTK_UI("限帧暂停", "cap paused"))];
    if (runtime_drs_scale) [parts addObject:[NSString stringWithFormat:@(TOTK_UI("分辨率 %.0f%%", "resolution %.0f%%")), runtime_drs_scale() * 100.0]];
    uint64_t c = runtime_output_size_current();
    [parts addObject:[NSString stringWithFormat:@(TOTK_UI("画布 %u×%u", "canvas %u×%u")), (unsigned)(uint32_t)c, (unsigned)(c >> 32)]];
    NSString *text = [parts componentsJoinedByString:@" · "];
    if (![self.now.stringValue isEqualToString:text]) self.now.stringValue = text;
}
/* A change made here: the running game follows, settings.txt keeps it. */
-(void)commit:(Settings)next save:(BOOL)save {
    settings_clamp(&next);
    apply_live(&model, &next);
    model = next;
    seen = model; live_read(&seen);   /* the game's state after this change is the one later key presses change */
    if (save) model_save();
    [self show];
}
-(void)presetChanged:(NSSegmentedControl *)control {
    if (control.selectedSegment < 0 || control.selectedSegment >= PRESET_CUSTOM) { [self show]; return; }   /* 自定义: the values as they are */
    Settings next = model; settings_preset(&next, (int)control.selectedSegment);
    [self commit:next save:YES];
}
-(void)changed:(id)control {
    Settings next = model; BOOL save = YES;
    if (control == self.fpsCap) next.fps_cap = (int)self.fpsCap.selectedTag;
    else if (control == self.drs) next.drs = self.drs.state == NSControlStateValueOn;
    else if (control == self.drsMin) {
        next.drs_min = (float)(round(self.drsMin.doubleValue * 100) / 100);
        save = NSApp.currentEvent.type != NSEventTypeLeftMouseDragged;   /* written when the knob is let go */
    } else if (control == self.renderRes) { next.render_w = (unsigned)self.renderRes.selectedTag >> 16; next.render_h = (unsigned)self.renderRes.selectedTag & 0xffff; }
    else if (control == self.output) {   /* the canvas and key 3's mode in step: 2K is native 2K, 1080p keeps MetalFX 2K */
        next.output = (int)self.output.selectedSegment;
        if (next.output == CANVAS_2K) next.picture = PICTURE_NATIVE; else if (next.picture == PICTURE_NATIVE) next.picture = PICTURE_OFF;
    } else if (control == self.picture) {
        next.picture = (int)self.picture.selectedSegment; next.output = next.picture == PICTURE_NATIVE ? CANVAS_2K : CANVAS_1080P;
    } else if (control == self.taa) next.taa = self.taa.state == NSControlStateValueOn;
    else if (control == self.aniso) next.aniso = (int)self.aniso.selectedTag;
    else if (control == self.interp) next.interpolation = (int)self.interp.selectedTag;
    else if (control == self.aspect) next.aspect = (int)self.aspect.selectedSegment;
    [self commit:next save:save];
}
/* Twice a second while open: a value the game reports differently from the last look was changed behind the window (keys
   2-5, another path), and wins. */
-(void)tick {
    Settings live = model; live_read(&live);
    BOOL changed = NO;
#define SETTINGS_FOLLOW(f) if (live.f != seen.f) { model.f = live.f; changed = YES; }
    SETTINGS_FOLLOW(fps_cap) SETTINGS_FOLLOW(drs_min) SETTINGS_FOLLOW(drs) SETTINGS_FOLLOW(picture) SETTINGS_FOLLOW(output) SETTINGS_FOLLOW(taa)
    SETTINGS_FOLLOW(interpolation) SETTINGS_FOLLOW(aspect)
#undef SETTINGS_FOLLOW
    seen = live;
    if (changed) [self show]; else [self showNow];
}
/* Builds the window if needed and fills it with the state in force (without showing it: the tests use this). */
-(void)prepare { [self build]; model_load(); [self show]; }
-(void)open:(id)sender {
    (void)sender;
    BOOL visible = self.panel.visible;
    [self prepare];
    if (!visible) {   /* over the middle of the game window, full screen or not */
        NSWindow *game = NSApp.mainWindow; NSRect f = self.panel.frame;
        if (game) [self.panel setFrameOrigin:NSMakePoint(round(NSMidX(game.frame) - f.size.width / 2), round(NSMidY(game.frame) - f.size.height / 2))];
        else [self.panel center];
    }
    [self.panel makeKeyAndOrderFront:nil];
    [self.timer invalidate];
    __weak TOTKSettings *weak = self;
    self.timer = [NSTimer scheduledTimerWithTimeInterval:0.5 repeats:YES block:^(NSTimer *t) { (void)t; [weak tick]; }];
}
-(void)windowWillClose:(NSNotification *)n {
    (void)n; [self.timer invalidate]; self.timer = nil;
    [NSApp.mainWindow makeKeyWindow];   /* the game window takes the keyboard (and, in mouse mode, the pointer) again */
}
@end

static TOTKSettings *settingsController;
/* frontend.m front_install_menu: "设置…" (Command-,) at the top of the app menu. */
void settings_panel_menu(NSMenu *appMenu) {
    if (!settingsController) settingsController = [TOTKSettings new];
    NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:@(TOTK_UI("设置…", "Settings…")) action:@selector(open:) keyEquivalent:@","];
    item.keyEquivalentModifierMask = NSEventModifierFlagCommand; item.target = settingsController;
    [appMenu addItem:item]; [appMenu addItem:NSMenuItem.separatorItem];
}

/* The in-game card shares the settings window's model, live setters and atomic save. */
BOOL settings_quick_apply(int action) {
    if (!settingsController) settingsController = [TOTKSettings new];
    [settingsController prepare];
    Settings next = model;
    if (action >= 100 && action <= 102) settings_preset(&next, action - 100);
    else if (action == 110) {
        const int caps[] = {30, 40, 60, 90, 120, 0};
        int i = 0; while (i < 6 && caps[i] != next.fps_cap) i++;
        next.fps_cap = caps[(i + 1) % 6];
    } else if (action == 111) next.drs = !next.drs;
    else if (action == 19) next.interpolation = (next.interpolation + 1) % MFX_NMODES;
    else if (action == 20) {
        next.picture = (next.picture + 1) % 3;
        if (next.picture == PICTURE_NATIVE && !native_this_run()) next.picture = PICTURE_OFF;
        next.output = next.picture == PICTURE_NATIVE ? CANVAS_2K : CANVAS_1080P;
    }
    else if (action == 21) { runtime_aspect_toggle(); live_read(&next); }
    else if (action == 23) next.taa = !next.taa;
    [settingsController commit:next save:YES];
    return !settingsSaveFailed;
}
void settings_quick_open(void) {
    if (!settingsController) settingsController = [TOTKSettings new];
    [settingsController open:nil];
}
