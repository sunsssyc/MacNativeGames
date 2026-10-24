/* Production AppKit panel, keyboard dispatch, mode state and output helpers.
   No guest, save files, game window or GPU commands are used. */
#include "../games/totk/runtime/frontend.m"
#include "../games/totk/runtime/input.c"
#include "../games/totk/third_party/d2r_gfx/gfx/nvn/fps_overlay.h"
#include <assert.h>

int dm_gfx_fps_now(int *generated) { if (generated) *generated = 0; return 60; }   /* the settings menu's "当前" line */
static int settingsPause;
void runtime_settings_pause(int paused){settingsPause=paused;}
static int hintClicks;
BOOL totk_hint_key(NSEvent *e, BOOL down) { if(down&&e.keyCode==28){hintClicks++;return YES;}return NO; }
void mfx_set(int mode);
int mfx_latch(void);
void mfxup_set(int on);
void mfxup_output_set(int on);
void shortcut_test_output_init(void);
void shortcut_test_output_size(unsigned w, unsigned h);

void dm_gfx_set_flag(const char *name, int value) {
    if (!strcmp(name, "mfx_interp")) mfx_set(value);
    else if (!strcmp(name, "mfx_output")) mfxup_output_set(value);
    else if (!strcmp(name, "mfx_upscale")) mfxup_set(value);
    else abort();
}
void shortcut_test_aspect_init(double view);
/* runtime/gamepad.m's key 6 state without GameController (gamepad_layout.h's real cycle): a DualSense is connected. */
static int fakePadType = GAMEPAD_TYPE_AUTO, fakePadDetected = GAMEPAD_TYPE_PLAYSTATION;
int runtime_gamepad_type_cycle(void) { return fakePadType = gamepad_type_next(fakePadType); }
int runtime_gamepad_type(int *detected) { if (detected) *detected = fakePadDetected; return fakePadType; }
/* runtime/gamepad.m's mouse mode (key 7) without GameController; the window never has the keyboard here. */
static int fakeMouse;
int runtime_mouse_toggle(void) { return fakeMouse = !fakeMouse; }
int runtime_mouse_enabled(void) { return fakeMouse; }
void runtime_mouse_set_hook(void (*hook)(void)) { (void)hook; }
void runtime_mouse_move(double dx, double dy) { (void)dx; (void)dy; }
void runtime_mouse_button(int button, int down) { (void)button; (void)down; }
void runtime_mouse_release(void) {}
static void press(unsigned key) {
    runtime_input_key_synthetic(key, 1);
    runtime_input_key_synthetic(key, 0);
}
static BOOL menu_key(unsigned key, NSEventModifierFlags modifiers, BOOL down) {
    NSEvent *e=[NSEvent keyEventWithType:down?NSEventTypeKeyDown:NSEventTypeKeyUp location:NSZeroPoint modifierFlags:modifiers timestamp:0 windowNumber:0 context:nil characters:@"" charactersIgnoringModifiers:@"" isARepeat:NO keyCode:key];
    return quick_menu_key(e,down);
}
static void tick(void) {
    [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
    [((TOTKShortcutHelp *)shortcutHelp).timer fire];
}
static void expect(TOTKShortcutHelp *panel, NSString *text) {
    if (![(hud_compact() && fps_overlay_full_hud() ? [shortcut_text() stringByAppendingString:panel.label.stringValue] : panel.label.stringValue) containsString:text]) {
        fprintf(stderr, "expected %s in:\n%s\n", text.UTF8String, panel.label.stringValue.UTF8String);
        abort();
    }
}

int main(int argc, const char **argv) { @autoreleasepool {
    [NSApplication sharedApplication];
    shortcut_test_output_init();
    int initial = mfx_enabled();
    assert(initial == ((!getenv("TOTK_MFX") || !strcmp(getenv("TOTK_MFX"), "0")) ? MFX_OFF : MFX_HALF));
    NSView *host = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 900, 540)];
    TOTKShortcutHelp *panel = [[TOTKShortcutHelp alloc] initWithFrame:NSZeroRect];
    [host addSubview:panel]; shortcutHelp = panel;
    assert(panel.timer && panel.timer.valid);
    assert(panel.timer.timeInterval == 0.5);
    [panel refresh];
    expect(panel, initial ? @"half refresh rate" : @"off");
    expect(panel, mfxup_output_enabled() ? @"MetalFX 2K" : @"Picture: off");

    /* A request is not the current frame's interpolation mode until latched. */
    mfx_set(MFX_OFF); mfx_latch();
    [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.6]];
    expect(panel, @"Interpolation: off");
    press(19); tick(); expect(panel, @"Interpolation: off");
    mfx_latch(); tick(); expect(panel, @"Interpolation: 30+30");
    runtime_input_key_synthetic(19, 1); runtime_input_key_synthetic(19, 1);
    runtime_input_key_synthetic(19, 0); mfx_latch(); tick();
    expect(panel, @"Interpolation: half refresh rate");
    press(19); mfx_latch(); tick(); expect(panel, @"Interpolation: unlimited");
    press(19); mfx_latch(); tick(); expect(panel, @"Interpolation: off");

    mfxup_output_set(0); tick(); expect(panel, @"Picture: off");
    press(20); tick(); expect(panel, @"Picture: MetalFX 2K");
    press(20); tick(); expect(panel, @"Picture: native 2K");
    press(20); tick(); expect(panel, @"Picture: off");
    expect(panel, @"Edge smoothing (MetalFX Temporal): off");
    press(23); tick(); expect(panel, @"Edge smoothing (MetalFX Temporal): on");
    press(23); tick(); expect(panel, @"Edge smoothing (MetalFX Temporal): off");
    /* Key 6: auto (what it takes the controller for) -> Xbox -> PlayStation -> Switch -> auto. */
    expect(panel, @"Controller type: auto (PlayStation) (current; press to cycle)");
    press(22); tick(); expect(panel, @"Controller type: Xbox (current");
    runtime_input_key_synthetic(22, 1); runtime_input_key_synthetic(22, 1); runtime_input_key_synthetic(22, 0); tick();
    expect(panel, @"Controller type: PlayStation (current");   /* a held key acts once */
    press(22); tick(); expect(panel, @"Controller type: Switch (current");
    press(22); tick(); expect(panel, @"Controller type: auto (PlayStation)");
    fakePadDetected = -1; tick(); expect(panel, @"Controller type: auto (no controller)");
    /* Key 7: mouse mode off -> on -> off. */
    expect(panel, @"7  Mouse: off (current; press to switch)");
    press(26); tick(); expect(panel, @"Mouse: on (camera, buttons; Command-Tab frees the pointer)");
    press(26); tick(); expect(panel, @"Mouse: off");
    press(26);   /* on for the Chinese check below */
    expect(panel, @"Aspect ratio: 16:9");
    shortcut_test_aspect_init(1.6);   /* key 4 becomes available; a 16:10 window */
    press(21); tick(); expect(panel, @"Aspect ratio: fit to window 1.60:1");
    press(21); tick(); expect(panel, @"Aspect ratio: 21:9");
    press(21); tick(); expect(panel, @"Aspect ratio: 16:9");
    /* Startup/diagnostic paths can set the canvas without a key press. */
    shortcut_test_output_size(3840, 2160); tick(); expect(panel, @"Picture: native 3840×2160");
    shortcut_test_output_size(2560, 1440);
    mfx_set(MFX_HALF); mfx_latch();
    setenv("TOTK_UI_LANG", "zh", 1); tick();
    expect(panel, @"补帧：当前 刷新率一半"); expect(panel, @"画质：当前 原生 2K");
    expect(panel, @"6  手柄类型：当前 自动（未接手柄）（按键切换）");
    expect(panel, @"7  鼠标操作：当前 开（视角、按键，⌘Tab 释放指针）（按键切换）");
    fakePadDetected = GAMEPAD_TYPE_SWITCH; tick(); expect(panel, @"手柄类型：当前 自动（Switch）");

    if (hud_compact()) {
        assert(NSEqualRects(panel.frame, host.bounds));
        assert(NSWidth(panel.label.frame) >= panel.textSize.width);
    } else {
        NSSize fit = [panel.label sizeThatFits:panel.label.bounds.size];
        assert(fit.height <= panel.label.bounds.size.height);
    }
    if(hud_compact()) {
        CGFloat expandedHeight=NSHeight(panel.frame);
        NSPoint buttonPoint=[panel convertPoint:NSMakePoint(NSMidX(panel.collapseButton.frame),NSMidY(panel.collapseButton.frame)) toView:host];
        assert([panel hitTest:buttonPoint]==panel.collapseButton);
        assert([panel hitTest:[panel convertPoint:NSMakePoint(8,8) toView:host]]!=nil);
        /* Rows (quickSpecs): 0 cap 1 dynamic resolution 2 its lowest scale 3 render resolution 4 picture 5 edge smoothing
           6 anisotropic filtering 7 interpolation 8 aspect | 9 controller 10 mouse | 11 AI channel. */
        assert(panel.quickRows.count==12);
        assert(panel.quickTabs.subviews.count==3 && panel.quickTab==0);
        for (NSUInteger i=0;i<12;i++) assert(panel.quickRows[i].hiddenOrHasHiddenAncestor==(i>=9));
        assert(panel.quickHint.hiddenOrHasHiddenAncestor && !panel.quickStatus.hiddenOrHasHiddenAncestor);
        assert([panel.quickRows[3].title isEqualToString:@"渲染分辨率"] && [panel.quickRows[4].title isEqualToString:@"画面"]);
        assert([((TOTKQuickRow *)panel.quickRows[4]).value isEqualToString:@"原生 2K"]);
        assert([((TOTKQuickRow *)panel.quickRows[7]).value isEqualToString:@"刷新率一半"]);
        assert(!panel.quickRows[2].enabled);   /* the lowest scale waits for dynamic resolution */
        assert([((TOTKQuickRow *)panel.quickRows[6]).value isEqualToString:@"游戏自身"] && !((TOTKQuickRow *)panel.quickRows[6]).note);
        [panel.quickRows[6] performClick:nil];tick();
        assert([((TOTKQuickRow *)panel.quickRows[6]).value isEqualToString:@"2×"] && [((TOTKQuickRow *)panel.quickRows[6]).note isEqualToString:@"重启后生效"]);
        ((TOTKQuickRow *)panel.quickRows[6]).direction=-1;[panel.quickRows[6] performClick:nil];((TOTKQuickRow *)panel.quickRows[6]).direction=1;tick();
        assert(!((TOTKQuickRow *)panel.quickRows[6]).note);   /* back to what this run started with */
        assert([panel.quickStatus.stringValue containsString:@"60 FPS"] && [panel.quickStatus.stringValue containsString:@"2560×1440"]);
        int before=taa_enabled();[panel.quickRows[5] performClick:nil];tick();
        assert(taa_enabled()!=before);
        assert(panel.quickFocused==5);
        ((TOTKQuickRow *)panel.quickRows[7]).hovered=YES;
        [panel focusQuickRow:panel.quickRows[5]];
        assert(!((TOTKQuickRow *)panel.quickRows[7]).hovered);
        assert([panel.quickHelpTitle.stringValue isEqualToString:panel.quickRows[5].title]);
        assert(panel.quickHelpText.stringValue.length>0);
        NSString *taaHelp=[panel.quickHelpText.stringValue copy];
        tick();assert(panel.quickFocused==5 && [panel.quickHelpText.stringValue isEqualToString:taaHelp]);
        assert([((TOTKQuickRow *)panel.quickRows[5]).value isEqualToString:taa_enabled()?@"开启":@"关闭"]);
        [panel.quickRows[5] performClick:nil];tick();assert(taa_enabled()==before);
        NSButton *controlsTab=(NSButton *)[panel.quickTabs viewWithTag:1];
        [controlsTab performClick:nil];tick();assert(panel.quickTab==1);
        for (NSUInteger i=0;i<12;i++) assert(panel.quickRows[i].hiddenOrHasHiddenAncestor==(i!=9&&i!=10));
        assert(panel.quickHint.hiddenOrHasHiddenAncestor && panel.quickStatus.hiddenOrHasHiddenAncestor);
        int padBefore=fakePadType;[panel.quickRows[9] performClick:nil];tick();assert(fakePadType==gamepad_type_next(padBefore));
        int mouseBefore=fakeMouse;[panel.quickRows[10] performClick:nil];tick();assert(fakeMouse!=mouseBefore);
        assert(panel.quickFocused==10);
        assert([panel.quickHelpTitle.stringValue isEqualToString:panel.quickRows[10].title]);
        assert(panel.quickHelpText.stringValue.length>0 && ![panel.quickHelpText.stringValue isEqualToString:taaHelp]);
        NSButton *assistantTab=(NSButton *)[panel.quickTabs viewWithTag:2];
        [assistantTab performClick:nil];tick();assert(panel.quickTab==2);
        for (NSUInteger i=0;i<12;i++) assert(panel.quickRows[i].hiddenOrHasHiddenAncestor==(i!=11));
        assert(!panel.quickHint.hiddenOrHasHiddenAncestor && panel.quickFocused==QUICK_HINT);
        assert(quickMenuOpen);[panel.quickHint performClick:nil];assert(hintClicks==1);
        /* The AI channel: assistant.json "channel", everything else in the file kept; both directions wrap. */
        NSString *assistant=quickAssistantPath(@"assistant.json");
        assert([@"{\"enabled\": true, \"agent\": {\"provider\": \"gemini\", \"model\": \"gemini-4-argon\"}}" writeToFile:assistant atomically:YES encoding:NSUTF8StringEncoding error:nil]);
        tick();TOTKQuickRow *channel=(TOTKQuickRow *)panel.quickRows[11];
        assert([channel.value isEqualToString:@"自动（按顺序）"] && channel.enabled && channel.dropdown);
        [channel performClick:nil];tick();
        assert([quickChannel() isEqualToString:@"claude-code"] && [channel.value isEqualToString:@"Claude Code（本机）"]);
        assert([quickJSONFile(assistant)[@"enabled"] boolValue] && [quickJSONFile(assistant)[@"agent"][@"model"] isEqualToString:@"gemini-4-argon"]);
        [channel performClick:nil];tick();assert([channel.value isEqualToString:@"Gemini 4（Vertex AI）"]);
        assert(panel.quickFocused==11 && [panel.quickChannelList.stringValue containsString:@"打开一次卡关助手后"] && !panel.quickChannelList.hiddenOrHasHiddenAncestor);
        assert([@"{\"backends\": {\"agent\": {\"ok\": true, \"label\": \"Gemini 4（Vertex AI）\"}, \"codex\": {\"ok\": false, \"why\": \"没有安装\"}}}" writeToFile:quickAssistantPath(@"hint-backends.json") atomically:YES encoding:NSUTF8StringEncoding error:nil]);
        tick();
        assert([panel.quickChannelList.stringValue containsString:@"Gemini 4（Vertex AI）　可用 · 当前"] && [panel.quickChannelList.stringValue containsString:@"Codex（本机）　不可用：没有安装"]);
        /* The dropdown: every channel at once, the current one selected, unusable ones marked; one click chooses. */
        [panel quickOpenChoices:channel];TOTKQuickChoices *choices=(TOTKQuickChoices *)panel.quickChoices;
        assert(choices && choices.options.count==6 && choices.options[2].state==NSControlStateValueOn && choices.highlighted==2);
        assert([choices.options[3].title isEqualToString:@"Codex（本机）  · 不可用"] && NSContainsRect(panel.bounds,choices.list));
        [choices.options[4] performClick:nil];tick();
        assert(!panel.quickChoices && [quickChannel() isEqualToString:@"vertex-claude-code"] && panel.quickFocused==11);
        assert(menu_key(36,0,YES) && panel.quickChoices);   /* Return on the row opens it; Up / Down / Return choose */
        assert(menu_key(126,0,YES) && ((TOTKQuickChoices *)panel.quickChoices).highlighted==3);
        assert(menu_key(36,0,YES) && !panel.quickChoices && [quickChannel() isEqualToString:@"codex"]);
        assert(menu_key(49,0,YES) && panel.quickChoices && menu_key(53,0,YES) && !panel.quickChoices && quickMenuOpen);   /* Esc closes only the list */
        [panel quickOpenChoices:channel];[(TOTKQuickChoices *)panel.quickChoices mouseDown:[NSEvent new]];assert(!panel.quickChoices);   /* a click beside it */
        assert(quickChannelSet(@"agent"));tick();
        channel.direction=-1;[channel performClick:nil];channel.direction=1;[channel performClick:nil];   /* back, then forward again */
        channel.direction=-1;[channel performClick:nil];[channel performClick:nil];channel.direction=1;tick();
        assert([quickChannel() isEqualToString:@"auto"]);
        channel.direction=-1;[channel performClick:nil];channel.direction=1;tick();assert([quickChannel() isEqualToString:@"vertex"]);
        assert([@"{ broken" writeToFile:assistant atomically:YES encoding:NSUTF8StringEncoding error:nil]);
        [channel performClick:nil];assert([[NSString stringWithContentsOfFile:assistant encoding:NSUTF8StringEncoding error:nil] isEqualToString:@"{ broken"]);
        /* Find tag zero among children, since viewWithTag:0 can return the container. */
        NSButton *pictureTab=nil;
        for (NSButton *tab in panel.quickTabs.subviews) if(tab.tag==0)pictureTab=tab;
        assert(pictureTab);[pictureTab performClick:nil];tick();assert(panel.quickTab==0);
        /* A resized window keeps both columns and every navigation target in bounds. */
        const NSSize sizes[]={ {640,360}, {1280,720}, {900,540} };
        for(NSUInteger i=0;i<sizeof(sizes)/sizeof(sizes[0]);i++) {
            [host setFrameSize:sizes[i]];[panel position];tick();
            assert(NSEqualRects(panel.frame,host.bounds));
            for(NSView *v in @[panel.quickTabs,panel.quickScroll,panel.quickHelpTitle,panel.quickHelpText,panel.collapseButton]) {
                NSRect r=[v convertRect:v.bounds toView:panel];
                assert(NSWidth(r)>0 && NSHeight(r)>0 && NSContainsRect(panel.bounds,r));
            }
        }
        NSPoint rowPoint=[panel.quickRows[5] convertPoint:NSMakePoint(40,15) toView:host];
        assert([panel hitTest:rowPoint]==panel.quickRows[5]);
        /* A gameplay key held before opening settings must be released through the menu. */
        [panel.collapseButton performClick:nil];assert(!quickMenuOpen);assert(!settingsPause);
        runtime_input_key_synthetic(49,1);assert(keys[49]);
        [panel.collapseButton performClick:nil];assert(quickMenuOpen);
        assert(menu_key(49,0,NO) && !keys[49]);
        /* Navigation consumes its events and follows displayed row order, not storage order. */
        [pictureTab performClick:nil];assert(panel.quickFocused==0);
        assert(menu_key(125,0,YES) && panel.quickFocused==1);
        assert(menu_key(125,0,NO) && panel.quickFocused==1);
        assert(menu_key(125,0,YES) && panel.quickFocused==2);
        assert(menu_key(126,0,YES) && panel.quickFocused==1);
        assert(menu_key(126,0,YES) && menu_key(126,0,YES) && panel.quickFocused==8);   /* wraps to the last row */
        assert(menu_key(125,0,YES) && panel.quickFocused==0);
        assert(menu_key(48,0,YES) && panel.quickTab==1 && panel.quickFocused==9);
        int keyboardPad=fakePadType;
        assert(menu_key(124,0,YES) && fakePadType==gamepad_type_next(keyboardPad));
        assert(menu_key(123,0,YES) && fakePadType==keyboardPad);
        assert(menu_key(125,0,YES) && panel.quickFocused==10);
        assert(menu_key(125,0,YES) && panel.quickFocused==9);
        assert(menu_key(48,0,YES) && panel.quickTab==2 && panel.quickFocused==QUICK_HINT);
        int clicks=hintClicks;assert(menu_key(36,0,YES) && hintClicks==clicks+1);
        assert(menu_key(125,0,YES) && panel.quickFocused==11);
        assert(menu_key(126,0,YES) && panel.quickFocused==QUICK_HINT);
        assert(menu_key(48,NSEventModifierFlagShift,YES) && panel.quickTab==1);
        assert(menu_key(48,NSEventModifierFlagShift,YES) && panel.quickTab==0);
        assert(!menu_key(48,NSEventModifierFlagCommand,YES) && panel.quickTab==0);
        assert(!menu_key(0,0,YES));
        assert(menu_key(53,0,YES));
        assert(!menu_key(125,0,YES));
        assert(!panel.hidden&&!fps_overlay_full_hud()&&fps_overlay_hints_enabled());
        assert(NSHeight(panel.frame)<expandedHeight);assert(!quickMenuOpen);assert(!settingsPause);
        assert(panel.quickTabs.hiddenOrHasHiddenAncestor && panel.quickHelpTitle.hiddenOrHasHiddenAncestor && panel.quickHelpText.hiddenOrHasHiddenAncestor);
        NSPoint outside=NSMakePoint(NSMinX(panel.frame)-5,NSMinY(panel.frame)-5);
        assert([panel hitTest:outside]==nil);
        assert([panel.collapseButton.title containsString:@"设置"]);
        [panel.collapseButton performClick:nil];
        assert(fps_overlay_full_hud() && quickMenuOpen);assert(settingsPause);
        assert(!panel.quickTabs.hiddenOrHasHiddenAncestor && !panel.quickHelpTitle.hiddenOrHasHiddenAncestor);
        assert([panel.collapseButton.title containsString:@"收起"]);
    }
    /* Key 1: all -> minimal (FPS only) -> off -> all. */
    hud_publish(HUD_FPS, "FPS 60  2560x1440", 0); hud_publish(HUD_SHADER, "New shaders 3 / total 9", 0);
    press(18); tick(); assert(fps_overlay_hints_enabled() && !fps_overlay_full_hud());
    if (hud_compact()) {
        assert(!panel.hidden); expect(panel, @"60 FPS");
        assert([panel.label.toolTip containsString:@"2560x1440"]);
        assert(![panel.label.stringValue containsString:@"2560x1440"]);
        hud_publish(HUD_FPS,"FPS 60+30（上限 60）  2560x1440",0);tick();
        assert([panel.label.stringValue isEqualToString:@"60+30 FPS"]);
        assert([panel.label.toolTip containsString:@"上限 60"]);
        assert(![panel.label.stringValue containsString:@"New shaders"] && ![panel.label.stringValue containsString:@"快捷键"]);
    } else assert(panel.hidden);   // corners: the FPS corner stays in the picture, the shortcut box goes
    press(18); tick(); assert(panel.hidden && !fps_overlay_hints_enabled());
    if(hud_compact())assert(!quickMenuOpen);assert(!settingsPause);
    mfx_set(MFX_MAX); mfx_latch(); tick();
    press(18); tick(); assert(!panel.hidden && fps_overlay_full_hud());
    expect(panel, @"补帧：当前 不限帧");
    hud_publish(0, "60 FPS (30 + 30)", 0); tick();
    if (hud_compact()) expect(panel, @"60 FPS");

    if (argc == 2) {
        NSBitmapImageRep *rep = [panel bitmapImageRepForCachingDisplayInRect:panel.bounds];
        [panel cacheDisplayInRect:panel.bounds toBitmapImageRep:rep];
        assert([[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}]
                writeToFile:@(argv[1]) atomically:YES]);
    }
    [panel.timer invalidate];
    puts("pass: current modes, keyboard cycling, frame latch, localization, both layouts, key 1 all/minimal/off, key 6 controller type and key 7 mouse");
    return 0;
}}
