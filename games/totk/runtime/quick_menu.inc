/* AppKit quick settings, included after TOTKShortcutHelp's declaration. */
extern BOOL settings_quick_apply(int action) __attribute__((weak_import));
extern void settings_quick_open(void) __attribute__((weak_import));
extern int nvn_fps_cap(void) __attribute__((weak_import));
extern int runtime_drs_enabled(void) __attribute__((weak_import));
static NSString *pad_type_text(void);
void runtime_input_key_synthetic(unsigned code,int down);
@interface TOTKShortcutHelp (QuickMenu)
-(void)buildQuickMenu;
-(void)refreshQuickMenu;
-(void)quickAction:(NSButton *)sender;
@end
static NSColor *quickAccent(void) { return [NSColor colorWithCalibratedRed:1 green:0.97 blue:0.82 alpha:1]; }
static NSColor *quickGold(void) { return [NSColor colorWithCalibratedRed:1 green:0.86 blue:0.32 alpha:1]; }
static NSColor *quickInk(void) { return [NSColor colorWithCalibratedRed:1 green:0.985 blue:0.87 alpha:1]; }
@interface TOTKQuickRow : NSButton
@property(copy) NSString *value;
@property BOOL hovered;
@property(strong) NSTrackingArea *hoverArea;
@end
@implementation TOTKQuickRow
-(BOOL)isOpaque { return NO; }
-(BOOL)acceptsFirstResponder { return NO; } // Leave gameplay shortcuts with the input view.
-(void)updateTrackingAreas {
 [super updateTrackingAreas];if(self.hoverArea)[self removeTrackingArea:self.hoverArea];
 self.hoverArea=[[NSTrackingArea alloc] initWithRect:NSZeroRect options:NSTrackingMouseEnteredAndExited|NSTrackingActiveInKeyWindow|NSTrackingInVisibleRect owner:self userInfo:nil];[self addTrackingArea:self.hoverArea];
}
-(void)mouseEntered:(NSEvent *)e {(void)e;self.hovered=YES;self.needsDisplay=YES;}
-(void)mouseExited:(NSEvent *)e {(void)e;self.hovered=NO;self.needsDisplay=YES;}
-(void)drawRect:(NSRect)dirty {
 (void)dirty;BOOL hot=self.enabled&&(self.hovered||self.highlighted);
 CGFloat w=NSWidth(self.bounds),split=w*0.49;
 [[NSColor colorWithCalibratedWhite:0.85 alpha:0.13] setFill];
 [[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(self.bounds,0,1) xRadius:2 yRadius:2] fill];
 NSRect valueBox=NSMakeRect(split,3,w-split-3,NSHeight(self.bounds)-6);
 [[NSColor colorWithCalibratedWhite:0.035 alpha:0.85] setFill];[[NSBezierPath bezierPathWithRoundedRect:valueBox xRadius:2 yRadius:2] fill];
 NSRect choice=NSInsetRect(valueBox,3,3);
 [[NSColor colorWithCalibratedRed:0.82 green:0.36 blue:0.015 alpha:self.enabled?0.96:0.12] setFill];[[NSBezierPath bezierPathWithRect:choice] fill];
 if(hot){[NSGraphicsContext saveGraphicsState];NSShadow *glow=[NSShadow new];glow.shadowColor=[quickGold() colorWithAlphaComponent:0.6];glow.shadowBlurRadius=5;[glow set];
  [quickGold() setStroke];NSBezierPath *edge=[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(valueBox,0.5,0.5) xRadius:2 yRadius:2];edge.lineWidth=2;[edge stroke];[NSGraphicsContext restoreGraphicsState];}
 NSColor *ink=self.enabled?quickInk():NSColor.disabledControlTextColor;
 NSMutableParagraphStyle *style=[NSMutableParagraphStyle new];style.lineBreakMode=NSLineBreakByTruncatingTail;
 [self.title drawInRect:NSMakeRect(12,10,split-22,20) withAttributes:@{NSFontAttributeName:[NSFont systemFontOfSize:14],NSForegroundColorAttributeName:ink,NSParagraphStyleAttributeName:style}];
 style.alignment=NSTextAlignmentCenter;
 [(self.value?:@"") drawInRect:NSMakeRect(split+10,10,w-split-34,20) withAttributes:@{NSFontAttributeName:[NSFont systemFontOfSize:13 weight:NSFontWeightMedium],NSForegroundColorAttributeName:ink,NSParagraphStyleAttributeName:style}];
 [@"▸" drawAtPoint:NSMakePoint(w-20,10) withAttributes:@{NSFontAttributeName:[NSFont systemFontOfSize:13],NSForegroundColorAttributeName:ink}];
}
@end
@interface TOTKQuickPreset : TOTKQuickRow
@end
@implementation TOTKQuickPreset
-(void)drawRect:(NSRect)dirty {
 (void)dirty;BOOL hot=self.enabled&&(self.hovered||self.highlighted);
 [[NSColor colorWithCalibratedWhite:0.025 alpha:0.8] setFill];
 NSRect rect=NSInsetRect(self.bounds,0.5,1.5);[[NSBezierPath bezierPathWithRect:rect] fill];
 [[quickGold() colorWithAlphaComponent:hot?1:0.25] setStroke];NSBezierPath *edge=[NSBezierPath bezierPathWithRect:rect];edge.lineWidth=hot?2.5:0.8;[edge stroke];
 NSMutableParagraphStyle *center=[NSMutableParagraphStyle new];center.alignment=NSTextAlignmentCenter;
 [self.title drawInRect:NSInsetRect(self.bounds,2,7) withAttributes:@{NSFontAttributeName:[NSFont systemFontOfSize:12 weight:NSFontWeightMedium],NSForegroundColorAttributeName:self.enabled?quickInk():NSColor.disabledControlTextColor,NSParagraphStyleAttributeName:center}];
}
@end
@implementation TOTKShortcutHelp (QuickMenu)
-(NSTextField *)quickCaption:(NSString *)text y:(CGFloat)y {
 NSTextField *v=[NSTextField labelWithString:text];v.font=[NSFont systemFontOfSize:10 weight:NSFontWeightSemibold];v.textColor=[quickInk() colorWithAlphaComponent:0.7];v.frame=NSMakeRect(4,y,300,18);[self.quickBody addSubview:v];return v;
}
-(void)buildQuickMenu {
 self.appearance=[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
 self.layer.backgroundColor=[NSColor colorWithCalibratedRed:0.11 green:0.12 blue:0.13 alpha:0.88].CGColor;self.layer.cornerRadius=4;
 self.layer.borderColor=[quickInk() colorWithAlphaComponent:0.18].CGColor;
 self.quickTitle=[NSTextField labelWithString:@(TOTK_UI("游戏设置","Game settings"))];self.quickTitle.font=[NSFont systemFontOfSize:20 weight:NSFontWeightMedium];self.quickTitle.textColor=[NSColor colorWithCalibratedWhite:0.07 alpha:1];self.quickTitle.alignment=NSTextAlignmentCenter;[self addSubview:self.quickTitle];
 self.quickScroll=[[NSScrollView alloc] initWithFrame:NSZeroRect];self.quickScroll.drawsBackground=NO;self.quickScroll.hasVerticalScroller=YES;self.quickScroll.scrollerStyle=NSScrollerStyleOverlay;self.quickScroll.autohidesScrollers=YES;
 self.quickBody=[[NSView alloc] initWithFrame:NSMakeRect(0,0,336,414)];self.quickScroll.documentView=self.quickBody;[self addSubview:self.quickScroll];
 self.quickPresets=[[NSView alloc] initWithFrame:NSMakeRect(0,380,334,30)];
 NSArray *presets=@[@(TOTK_UI("性能","Performance")),@(TOTK_UI("均衡","Balanced")),@(TOTK_UI("画质","Quality"))];
 for(int i=0;i<3;i++){TOTKQuickPreset *b=[[TOTKQuickPreset alloc] initWithFrame:NSMakeRect(i*112,0,108,30)];b.title=presets[i];b.tag=i;b.target=self;b.action=@selector(quickPreset:);b.bordered=NO;b.enabled=settings_quick_apply!=NULL;[self.quickPresets addSubview:b];}
 [self.quickBody addSubview:self.quickPresets];
 [self quickCaption:@(TOTK_UI("画面  /  点击切换","PICTURE  /  CLICK TO CYCLE")) y:355];
 self.quickRows=[NSMutableArray new];
 NSArray *titles=@[@(TOTK_UI("帧率上限","Frame limit")),@(TOTK_UI("动态分辨率","Auto resolution")),@(TOTK_UI("补帧","Frame generation")),@(TOTK_UI("画质","Picture")),@(TOTK_UI("画面比例","Aspect ratio")),@(TOTK_UI("边缘平滑","Edge smoothing")),@(TOTK_UI("手柄类型","Controller")),@(TOTK_UI("鼠标视角","Mouse camera"))];
 const int actions[]={110,111,19,20,21,23,22,26};
 for(int i=0;i<8;i++) {
  TOTKQuickRow *b=[[TOTKQuickRow alloc] initWithFrame:NSMakeRect(0,316-i*39-(i>=6?18:0),334,38)];b.title=titles[i];b.tag=actions[i];b.target=self;b.action=@selector(quickAction:);b.bordered=NO;
  b.toolTip=@(TOTK_UI("点击切换；也可使用原有数字快捷键","Click to cycle; number shortcuts still work"));
  [self.quickBody addSubview:b];[self.quickRows addObject:b];
 }
 [self quickCaption:@(TOTK_UI("操作","CONTROLS")) y:103];
 self.quickHint=[TOTKQuickPreset buttonWithTitle:@(TOTK_UI("✦  卡关助手","✦  Hint assistant")) target:self action:@selector(quickHint:)];self.quickHint.bordered=NO;self.quickHint.font=[NSFont systemFontOfSize:11 weight:NSFontWeightMedium];self.quickHint.contentTintColor=quickAccent();[self addSubview:self.quickHint];
 self.quickSettings=[TOTKQuickPreset buttonWithTitle:@(TOTK_UI("全部设置…  ⌘,","All settings…  ⌘,")) target:self action:@selector(quickSettings:)];self.quickSettings.bordered=NO;self.quickSettings.font=[NSFont systemFontOfSize:11];self.quickSettings.enabled=settings_quick_open!=NULL;[self addSubview:self.quickSettings];
 self.quickNote=[NSTextField labelWithString:@(TOTK_UI("即时调整 · 按 1 收起 / 隐藏","Live controls · 1 to collapse / hide"))];self.quickNote.font=[NSFont systemFontOfSize:10];self.quickNote.textColor=[NSColor colorWithCalibratedWhite:0.15 alpha:1];[self addSubview:self.quickNote];
 [self.quickBody scrollPoint:NSMakePoint(0,NSHeight(self.quickBody.bounds))];
}
-(void)quickPreset:(NSButton *)sender {
 BOOL ok=settings_quick_apply&&settings_quick_apply(100+(int)sender.tag);
 self.quickNote.stringValue=ok?@(TOTK_UI("预设已应用 · 部分选项需重启，详见全部设置","Preset applied · Some options need restart; see settings")):@(TOTK_UI("本次已应用，但未能保存设置","Applied for this session; could not save"));
 [self refresh];[self.window makeFirstResponder:self.window.contentView];
}
-(void)quickAction:(NSButton *)sender {
 if(sender.tag==22||sender.tag==26||!settings_quick_apply) {
  runtime_input_key_synthetic((unsigned)sender.tag,1);runtime_input_key_synthetic((unsigned)sender.tag,0);
 }else{
  BOOL ok=settings_quick_apply((int)sender.tag);
  self.quickNote.stringValue=ok?(getenv("TOTK_SETTINGS")&&*getenv("TOTK_SETTINGS")?@(TOTK_UI("已应用并保存","Applied and saved")):@(TOTK_UI("已应用 · 仅本次会话","Applied · This session only"))):@(TOTK_UI("本次已应用，但未能保存设置","Applied for this session; could not save"));
 }
 if(sender.tag==26)self.quickNote.stringValue=@(TOTK_UI("收起面板后用鼠标控制视角","Collapse the panel to control the camera"));
 [self refresh];[self.window makeFirstResponder:self.window.contentView];
}
-(void)quickSettings:(id)sender {(void)sender;if(settings_quick_open)settings_quick_open();}
-(void)quickHint:(id)sender {
 (void)sender;NSEvent *e=[NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:self.window.windowNumber context:nil characters:@"8" charactersIgnoringModifiers:@"8" isARepeat:NO keyCode:28];totk_hint_key(e,YES);
}
-(void)refreshQuickMenu {
 BOOL full=fps_overlay_full_hud();quickMenuOpen=full&&!self.hidden;
 if(window&&[window.contentView isKindOfClass:TOTKInputView.class]){
  BOOL hide=!quickMenuOpen&&window.isKeyWindow&&(window.styleMask&NSWindowStyleMaskFullScreen);
  TOTKInputView *input=(TOTKInputView *)window.contentView;
  if(input.cursorAutoHideActive!=hide)[input setCursorAutoHideEnabled:hide];front_mouse_update();
 }
 self.collapseButton.contentTintColor=full?[NSColor colorWithCalibratedWhite:0.1 alpha:1]:quickInk();
 self.quickTitle.hidden=self.quickScroll.hidden=self.quickSettings.hidden=self.quickHint.hidden=self.quickNote.hidden=!full;
 char line[128];int highlight=0;NSString *fps=hud_snapshot(0,line,sizeof line,&highlight)?@(line):@"FPS --";
 self.label.stringValue=fps;self.label.font=[NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightMedium];self.label.textColor=quickAccent();
 NSMutableArray *details=[NSMutableArray new];for(int i=1;i<4;i++){char t[128];int hl;if(hud_snapshot(i,t,sizeof t,&hl))[details addObject:@(t)];}self.label.toolTip=[details componentsJoinedByString:@"\n"];
 self.textSize=NSMakeSize(0,16);
 if(full){
  int cap=nvn_fps_cap?nvn_fps_cap():0;
  uint64_t size=runtime_output_size_current();unsigned w=(uint32_t)size,h=(uint32_t)(size>>32);
  NSString *picture=mfxup_output_enabled()?@"MetalFX 2K":w==1920&&h==1080?@(TOTK_UI("标准","Standard")):[NSString stringWithFormat:@"%u × %u",w,h];
  int mode=mfx_enabled();NSString *interp=mode==MFX_30?@"30 + 30":mode==MFX_HALF?@(TOTK_UI("半刷新率","Half refresh")):mode==MFX_MAX?@(TOTK_UI("不限帧","Unlimited")):@(TOTK_UI("关闭","Off"));
  int aspect=runtime_aspect_step();float ratio=runtime_aspect_now();
  NSString *wide=fabsf(ratio*9-21)<0.05f?@"21:9":[NSString stringWithFormat:@"%.2f:1",ratio];
  NSArray *values=@[cap?[NSString stringWithFormat:@"%d FPS",cap]:@(TOTK_UI("不限帧","Unlimited")),runtime_drs_enabled&&runtime_drs_enabled()?@(TOTK_UI("开启","On")):@(TOTK_UI("关闭","Off")),interp,picture,aspect==1?@(TOTK_UI("适配窗口","Fit window")):aspect==2?wide:@"16:9",taa_enabled()?@(TOTK_UI("开启","On")):@(TOTK_UI("关闭","Off")),pad_type_text(),runtime_mouse_enabled()?@(TOTK_UI("开启 · 收起后生效","On · collapse to play")):@(TOTK_UI("关闭","Off"))];
  for(NSUInteger i=0;i<self.quickRows.count;i++) {TOTKQuickRow *b=(TOTKQuickRow *)self.quickRows[i];b.value=values[i];b.accessibilityLabel=[NSString stringWithFormat:@"%@：%@",b.title,b.value];b.needsDisplay=YES;}
  self.quickRows[0].enabled=nvn_fps_cap&&settings_quick_apply;self.quickRows[1].enabled=runtime_drs_enabled&&settings_quick_apply;self.quickRows[4].enabled=aspect>=0;
 }
 self.needsDisplay=YES;[self position];
}
@end
