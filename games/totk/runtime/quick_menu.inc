/* Native, mouse-operated options screen. Values always come from live runtime state. */
extern BOOL settings_quick_apply(int action) __attribute__((weak_import));
extern BOOL settings_quick_step(int action,int direction) __attribute__((weak_import));
extern int settings_quick_preset(void) __attribute__((weak_import));
extern void settings_quick_open(void) __attribute__((weak_import));
extern int nvn_fps_cap(void) __attribute__((weak_import));
extern int runtime_drs_enabled(void) __attribute__((weak_import));
extern float runtime_drs_min(void) __attribute__((weak_import));
static NSString *pad_type_text(void);
void runtime_input_key_synthetic(unsigned code,int down);
@interface TOTKShortcutHelp (QuickMenu)
-(void)buildQuickMenu;
-(void)refreshQuickMenu;
-(void)layoutQuickMenu;
-(void)quickAction:(NSButton *)sender;
-(void)quickTabAction:(NSButton *)sender;
-(void)focusQuickRow:(NSButton *)sender;
@end
static NSColor *quickAccent(void){return [NSColor colorWithCalibratedRed:0.88 green:0.40 blue:0.015 alpha:1];}
static NSColor *quickGold(void){return [NSColor colorWithCalibratedRed:1 green:0.9 blue:0.50 alpha:1];}
static NSColor *quickInk(void){return [NSColor colorWithCalibratedRed:0.99 green:0.975 blue:0.85 alpha:1];}
static NSFont *quickFont(CGFloat size){return [NSFont fontWithName:@"PingFangSC-Regular" size:size]?:[NSFont systemFontOfSize:size];}
@interface TOTKQuickDecoration:NSView
@end
@implementation TOTKQuickDecoration
-(NSView *)hitTest:(NSPoint)p{(void)p;return nil;}
-(void)drawRect:(NSRect)dirty{[(TOTKShortcutHelp *)self.superview drawRect:dirty];}
@end
static void quickText(NSString *text,NSRect r,CGFloat size,NSColor *ink,NSTextAlignment alignment){
 NSMutableParagraphStyle *p=[NSMutableParagraphStyle new];p.alignment=alignment;p.lineBreakMode=NSLineBreakByTruncatingTail;
 [text drawInRect:r withAttributes:@{NSFontAttributeName:quickFont(size),NSForegroundColorAttributeName:ink,NSParagraphStyleAttributeName:p}];
}
@interface TOTKQuickRow:NSButton
@property(copy) NSString *value;
@property BOOL hovered,focused,binary,on;
@property NSInteger direction;
@property(strong) NSTrackingArea *hoverArea;
@end
@implementation TOTKQuickRow
-(BOOL)isOpaque{return NO;}
-(BOOL)acceptsFirstResponder{return NO;}
-(void)updateTrackingAreas{
 [super updateTrackingAreas];if(self.hoverArea)[self removeTrackingArea:self.hoverArea];
 self.hoverArea=[[NSTrackingArea alloc] initWithRect:NSZeroRect options:NSTrackingMouseEnteredAndExited|NSTrackingActiveInKeyWindow|NSTrackingInVisibleRect owner:self userInfo:nil];[self addTrackingArea:self.hoverArea];
}
-(void)mouseEntered:(NSEvent *)e{(void)e;self.hovered=YES;self.needsDisplay=YES;if([self.target respondsToSelector:@selector(focusQuickRow:)])[(TOTKShortcutHelp *)self.target focusQuickRow:self];}
-(void)mouseExited:(NSEvent *)e{(void)e;self.hovered=NO;self.needsDisplay=YES;}
-(void)mouseDown:(NSEvent *)e{
 NSPoint p=[self convertPoint:e.locationInWindow fromView:nil];CGFloat split=NSWidth(self.bounds)*0.51;
 self.direction=p.x>=split&&p.x<split+(NSWidth(self.bounds)-split)/2?-1:1;
 if(self.binary&&p.x>=split){BOOL requested=p.x<split+(NSWidth(self.bounds)-split)/2;if(requested==self.on){[(TOTKShortcutHelp *)self.target focusQuickRow:self];return;}}
 [super mouseDown:e];self.direction=1;
}
-(void)drawRect:(NSRect)dirty{
 (void)dirty;CGFloat w=NSWidth(self.bounds),h=NSHeight(self.bounds),split=w*0.51;
 BOOL hot=self.enabled&&(self.focused||self.hovered||self.highlighted);CGFloat font=h>=44?17:14;
 [[NSColor colorWithCalibratedRed:0.68 green:0.65 blue:0.57 alpha:0.24] setFill];
 [[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(self.bounds,0,2) xRadius:3 yRadius:3] fill];
 NSRect box=NSMakeRect(split,4,w-split-4,h-8);
 [[NSColor colorWithCalibratedWhite:0.015 alpha:0.87] setFill];[[NSBezierPath bezierPathWithRoundedRect:box xRadius:3 yRadius:3] fill];
 [[quickInk() colorWithAlphaComponent:0.23] setStroke];[[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(box,1,1) xRadius:2 yRadius:2] stroke];
 NSColor *ink=self.enabled?quickInk():[quickInk() colorWithAlphaComponent:0.4];
 quickText(self.title,NSMakeRect(18,(h-font-5)/2,split-28,font+7),font,ink,NSTextAlignmentLeft);
 NSRect choice=NSInsetRect(box,4,4);
 if(self.binary){CGFloat half=choice.size.width/2;NSRect selected=choice;selected.size.width=half;if(!self.on)selected.origin.x+=half;
  [[quickAccent() colorWithAlphaComponent:self.enabled?1:0.25] setFill];[[NSBezierPath bezierPathWithRoundedRect:selected xRadius:2 yRadius:2] fill];
  quickText(@(TOTK_UI("开启","On")),NSMakeRect(choice.origin.x,(h-font-5)/2,half,font+7),font,self.on?ink:[ink colorWithAlphaComponent:0.5],NSTextAlignmentCenter);
  quickText(@(TOTK_UI("关闭","Off")),NSMakeRect(choice.origin.x+half,(h-font-5)/2,half,font+7),font,!self.on?ink:[ink colorWithAlphaComponent:0.5],NSTextAlignmentCenter);
 }else{
  if(hot){[quickAccent() setFill];[[NSBezierPath bezierPathWithRoundedRect:choice xRadius:2 yRadius:2] fill];}
  quickText(self.value?:@"",NSMakeRect(split+27,(h-font-5)/2,w-split-58,font+7),font,ink,NSTextAlignmentCenter);
  for(int i=0;i<2;i++){CGFloat x=i?NSMaxX(box)-14:NSMinX(box)+14,y=h/2;NSBezierPath *arrow=[NSBezierPath bezierPath];
   [arrow moveToPoint:NSMakePoint(x+(i?-3:3),y+5)];[arrow lineToPoint:NSMakePoint(x+(i?3:-3),y)];[arrow lineToPoint:NSMakePoint(x+(i?-3:3),y-5)];[arrow closePath];[ink setFill];[arrow fill];}
 }
 if(hot){[NSGraphicsContext saveGraphicsState];NSShadow *glow=[NSShadow new];glow.shadowColor=[quickGold() colorWithAlphaComponent:0.5];glow.shadowBlurRadius=5;[glow set];[quickGold() setStroke];NSBezierPath *edge=[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(box,-1,-1) xRadius:4 yRadius:4];edge.lineWidth=2;[edge stroke];[NSGraphicsContext restoreGraphicsState];}
}
@end
@interface TOTKQuickPreset:TOTKQuickRow
@end
@implementation TOTKQuickPreset
-(void)drawRect:(NSRect)dirty{
 (void)dirty;BOOL hot=self.enabled&&(self.hovered||self.highlighted);BOOL selected=self.state==NSControlStateValueOn;
 [(selected?quickAccent():[NSColor colorWithCalibratedWhite:0.025 alpha:0.65]) setFill];NSRect r=NSInsetRect(self.bounds,1,2);[[NSBezierPath bezierPathWithRoundedRect:r xRadius:2 yRadius:2] fill];
 [[quickInk() colorWithAlphaComponent:hot?0.9:0.25] setStroke];NSBezierPath *edge=[NSBezierPath bezierPathWithRoundedRect:r xRadius:2 yRadius:2];edge.lineWidth=hot?2:0.6;[edge stroke];
 CGFloat font=NSHeight(self.bounds)>=40?16:13;quickText(self.title,NSMakeRect(5,(NSHeight(self.bounds)-font-5)/2,NSWidth(self.bounds)-10,font+7),font,self.enabled?quickInk():[quickInk() colorWithAlphaComponent:0.4],NSTextAlignmentCenter);
}
@end
@implementation TOTKShortcutHelp (QuickMenu)
-(void)buildQuickMenu{
 self.appearance=[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];self.quickTab=0;self.quickFocused=0;
 self.material=NSVisualEffectMaterialHUDWindow;self.blendingMode=NSVisualEffectBlendingModeWithinWindow;self.state=NSVisualEffectStateActive;
 self.quickBackdrop=[TOTKQuickDecoration new];[self addSubview:self.quickBackdrop positioned:NSWindowBelow relativeTo:self.label];
 self.quickTitle=[NSTextField labelWithString:@(TOTK_UI("游戏设置","Game settings"))];self.quickTitle.font=quickFont(27);self.quickTitle.textColor=quickInk();self.quickTitle.alignment=NSTextAlignmentCenter;[self addSubview:self.quickTitle];
 self.quickTabs=[NSView new];[self addSubview:self.quickTabs];
 NSArray *tabs=@[@(TOTK_UI("画面","Graphics")),@(TOTK_UI("操作","Controls")),@(TOTK_UI("辅助","Assistance"))];
 for(int i=0;i<3;i++){NSButton *b=[TOTKQuickPreset buttonWithTitle:tabs[i] target:self action:@selector(quickTabAction:)];b.tag=i;b.bordered=NO;[self.quickTabs addSubview:b];}
 self.quickScroll=[NSScrollView new];self.quickScroll.drawsBackground=NO;self.quickScroll.hasVerticalScroller=YES;self.quickScroll.scrollerStyle=NSScrollerStyleOverlay;self.quickScroll.autohidesScrollers=YES;
 self.quickBody=[NSView new];self.quickScroll.documentView=self.quickBody;[self addSubview:self.quickScroll];
 self.quickPresetLabel=[NSTextField labelWithString:@(TOTK_UI("画面预设","Graphics preset"))];self.quickPresetLabel.textColor=quickInk();[self.quickBody addSubview:self.quickPresetLabel];
 self.quickPresets=[NSView new];[self.quickBody addSubview:self.quickPresets];
 NSArray *presets=@[@(TOTK_UI("性能","Performance")),@(TOTK_UI("均衡","Balanced")),@(TOTK_UI("画质","Quality"))];
 for(int i=0;i<3;i++){NSButton *b=[TOTKQuickPreset buttonWithTitle:presets[i] target:self action:@selector(quickPreset:)];b.tag=i;b.bordered=NO;b.enabled=settings_quick_apply!=NULL;[self.quickPresets addSubview:b];}
 NSArray *titles=@[@(TOTK_UI("帧率上限","Frame limit")),@(TOTK_UI("动态分辨率","Dynamic resolution")),@(TOTK_UI("补帧","Frame generation")),@(TOTK_UI("渲染分辨率","Render resolution")),@(TOTK_UI("画面比例","Aspect ratio")),@(TOTK_UI("边缘平滑","Edge smoothing")),@(TOTK_UI("手柄类型","Controller")),@(TOTK_UI("鼠标视角","Mouse camera"))];
 const int actions[]={110,111,19,20,21,23,22,26};self.quickRows=[NSMutableArray new];
 for(int i=0;i<8;i++){TOTKQuickRow *b=[TOTKQuickRow new];b.title=titles[i];b.tag=actions[i];b.target=self;b.action=@selector(quickAction:);b.bordered=NO;b.direction=1;b.binary=i==1||i==5||i==7;[self.quickBody addSubview:b];[self.quickRows addObject:b];}
 self.quickHelpTitle=[NSTextField labelWithString:@""];self.quickHelpTitle.textColor=quickInk();self.quickHelpTitle.font=[NSFont systemFontOfSize:24 weight:NSFontWeightMedium];[self addSubview:self.quickHelpTitle];
 self.quickHelpText=[NSTextField wrappingLabelWithString:@""];self.quickHelpText.textColor=quickInk();self.quickHelpText.font=[NSFont systemFontOfSize:16];self.quickHelpText.maximumNumberOfLines=0;[self addSubview:self.quickHelpText];
 self.quickHint=[TOTKQuickPreset buttonWithTitle:@(TOTK_UI("卡关助手 · 逐级提示","Hint assistant")) target:self action:@selector(quickHint:)];self.quickHint.bordered=NO;[self.quickBody addSubview:self.quickHint];
 self.quickSettings=[TOTKQuickPreset buttonWithTitle:@(TOTK_UI("全部设置…  ⌘,","All settings…  ⌘,")) target:self action:@selector(quickSettings:)];self.quickSettings.bordered=NO;self.quickSettings.enabled=settings_quick_open!=NULL;[self.quickBody addSubview:self.quickSettings];
 self.quickReturn=[TOTKQuickPreset buttonWithTitle:@(TOTK_UI("返回游戏  Esc","Return to game  Esc")) target:self action:@selector(toggleCollapsed:)];self.quickReturn.bordered=NO;[self addSubview:self.quickReturn];
 self.quickNote=[NSTextField labelWithString:@(TOTK_UI("鼠标点击调整 · 方向键选择 · Tab 切换分类","Click to adjust · Arrow keys select · Tab changes category"))];self.quickNote.textColor=[quickInk() colorWithAlphaComponent:0.7];self.quickNote.font=[NSFont systemFontOfSize:11];[self addSubview:self.quickNote];
 [self focusQuickRow:self.quickRows[0]];
}
-(void)focusQuickRow:(NSButton *)sender{
 NSUInteger index=[self.quickRows indexOfObject:sender];if(index==NSNotFound)return;self.quickFocused=(NSInteger)index;
 NSArray *help=@[@(TOTK_UI("限制最高帧率，兼顾流畅度与功耗。\n\n显示器刷新率可整除时，帧间隔会与显示节拍对齐。","Limit frame rate to balance smoothness and power consumption.")),@(TOTK_UI("根据运行负载调整渲染分辨率，优先保持画面流畅。\n\n最低比例 67%","Adjust rendering resolution to preserve smooth gameplay.\n\nMinimum scale: 67%")),@(TOTK_UI("生成中间帧以改善观感。部分模式需要重启；实际状态以运行时显示为准。","Generate intermediate frames. Some modes require a restart; the displayed value reflects runtime state.")),@(TOTK_UI("较高的分辨率让画面更清晰，也会增加图形负载。","Higher resolution improves clarity and increases graphics load.")),@(TOTK_UI("调整游戏画面比例。可选择标准比例、适配窗口或宽屏。","Choose standard, fit-to-window or widescreen presentation.")),@(TOTK_UI("使用 MetalFX 时间性抗锯齿平滑画面边缘。","Smooth edges with MetalFX temporal antialiasing.")),@(TOTK_UI("选择手柄按键布局，或自动识别连接的手柄。","Choose a controller layout or detect the connected controller automatically.")),@(TOTK_UI("用鼠标控制视角。收起设置后生效；⌘Tab 可释放指针。","Control the camera with the mouse after closing settings. Command-Tab releases the pointer."))];
 self.quickHelpTitle.stringValue=sender.title;self.quickHelpText.stringValue=help[index];
 if(index==1&&runtime_drs_min)self.quickHelpText.stringValue=[NSString stringWithFormat:@(TOTK_UI("根据运行负载调整渲染分辨率，优先保持画面流畅。\n\n最低比例 %.0f%%","Adjust rendering resolution to preserve smooth gameplay.\n\nMinimum scale: %.0f%%")),runtime_drs_min()*100.0];
 for(NSUInteger i=0;i<self.quickRows.count;i++){TOTKQuickRow *b=(id)self.quickRows[i];b.hovered=NO;b.focused=i==index;b.needsDisplay=YES;}
}
-(void)quickTabAction:(NSButton *)sender{
 self.quickTab=sender.tag;[self refreshQuickMenu];
 if(self.quickTab<2)[self focusQuickRow:self.quickRows[self.quickTab?6:0]];
 else{self.quickFocused=8;self.quickHint.state=NSControlStateValueOn;self.quickSettings.state=NSControlStateValueOff;self.quickHelpTitle.stringValue=@(TOTK_UI("辅助","Assistance"));self.quickHelpText.stringValue=@(TOTK_UI("需要线索时打开卡关助手，按需查看逐级提示。\n\n全部设置包含启动选项与更多说明。","Open the hint assistant for progressive clues.\n\nAll settings includes startup options and additional details."));}
 [self.quickBody scrollPoint:NSMakePoint(0,NSHeight(self.quickBody.bounds))];[self.window makeFirstResponder:self.window.contentView];
}
-(void)layoutQuickMenu{
 CGFloat w=NSWidth(self.bounds),h=NSHeight(self.bounds);BOOL full=fps_overlay_full_hud();
 self.collapseButton.frame=NSMakeRect(w-80,h-35,70,25);if(!full)return;
 self.quickBackdrop.frame=self.bounds;
 self.quickTitle.frame=NSMakeRect(80,h*0.89,w-160,36);
 CGFloat tw=MIN(420,w-80);self.quickTabs.frame=NSMakeRect((w-tw)/2,h*0.795,tw,40);
 for(NSView *v in self.quickTabs.subviews)v.frame=NSMakeRect(v.tag*tw/3,0,tw/3,40);
 BOOL wide=w>=820;CGFloat x=w*0.065,bw=wide?w*0.55:w*0.87,helpHeight=wide?0:66;
 CGFloat available=MAX(80,h*0.52-helpHeight),row=MAX(38,available/7);
 self.quickScroll.frame=NSMakeRect(x,h*0.20+helpHeight,bw,available);
 CGFloat content=MAX(available,self.quickTab==0?row*7:self.quickTab==1?row*2:row*2);
 [self.quickBody setFrameSize:NSMakeSize(bw,content)];
 self.quickPresets.frame=NSMakeRect(bw*0.51,content-row,bw*0.49-4,row);
 self.quickPresetLabel.frame=NSMakeRect(18,content-row+(row-22)/2,bw*0.51-28,24);self.quickPresetLabel.font=quickFont(row>=44?17:14);
 for(NSView *v in self.quickPresets.subviews)v.frame=NSMakeRect(v.tag*NSWidth(self.quickPresets.bounds)/3,0,NSWidth(self.quickPresets.bounds)/3,row);
 const int order[]={0,1,3,4,5,2,6,7};
 for(int i=0;i<8;i++){NSButton *b=self.quickRows[order[i]];CGFloat y=content-row*(i<6?i+2:i-5);b.frame=NSMakeRect(0,y,bw,row);}
 self.quickHint.frame=NSMakeRect(0,content-row,bw,row);self.quickSettings.frame=NSMakeRect(0,content-row*2,bw,row);
 if(wide){self.quickHelpTitle.frame=NSMakeRect(w*0.63+24,h*0.715-62,w*0.33-48,38);self.quickHelpText.frame=NSMakeRect(w*0.63+24,h*0.24+24,w*0.33-48,MAX(50,h*0.475-126));}
 else{self.quickHelpTitle.frame=NSMakeRect(x,111,bw,24);self.quickHelpText.frame=NSMakeRect(x,71,bw,40);}
 self.quickHelpTitle.font=quickFont(wide?24:15);self.quickHelpText.font=quickFont(wide?16:12);
 self.quickReturn.frame=NSMakeRect(w-202,15,180,32);self.quickNote.frame=NSMakeRect(x,22,MAX(40,w-250-x),20);
}
-(void)quickPreset:(NSButton *)sender{
 BOOL ok=settings_quick_apply&&settings_quick_apply(100+(int)sender.tag);
 self.quickNote.stringValue=ok?@(TOTK_UI("预设已应用 · 部分选项需重启","Preset applied · Some options require restart")):@(TOTK_UI("已应用，但未能保存设置","Applied; settings could not be saved"));[self refresh];
}
-(void)quickAction:(NSButton *)sender{
 [self focusQuickRow:sender];int direction=(int)((TOTKQuickRow *)sender).direction;if(!direction)direction=1;
 if(sender.tag==22||sender.tag==26||!settings_quick_apply){int count=direction<0&&sender.tag==22?GAMEPAD_TYPE_COUNT-1:1;for(int i=0;i<count;i++){runtime_input_key_synthetic((unsigned)sender.tag,1);runtime_input_key_synthetic((unsigned)sender.tag,0);}}
 else{BOOL ok=settings_quick_step?settings_quick_step((int)sender.tag,direction):settings_quick_apply((int)sender.tag);
  self.quickNote.stringValue=ok?(getenv("TOTK_SETTINGS")&&*getenv("TOTK_SETTINGS")?@(TOTK_UI("已应用并保存","Applied and saved")):@(TOTK_UI("已应用 · 仅本次会话","Applied · This session only"))):@(TOTK_UI("已应用，但未能保存设置","Applied; settings could not be saved"));}
 [self refresh];[self.window makeFirstResponder:self.window.contentView];
}
-(void)quickSettings:(id)sender{(void)sender;if(settings_quick_open)settings_quick_open();}
-(void)quickHint:(id)sender{(void)sender;NSEvent *e=[NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:self.window.windowNumber context:nil characters:@"8" charactersIgnoringModifiers:@"8" isARepeat:NO keyCode:28];totk_hint_key(e,YES);}
-(void)refreshQuickMenu {
 BOOL full=fps_overlay_full_hud();quickMenuOpen=full&&!self.hidden;
 if(window&&[window.contentView isKindOfClass:TOTKInputView.class]){
  BOOL hide=!quickMenuOpen&&window.isKeyWindow&&(window.styleMask&NSWindowStyleMaskFullScreen);
  TOTKInputView *input=(TOTKInputView *)window.contentView;
  if(input.cursorAutoHideActive!=hide)[input setCursorAutoHideEnabled:hide];front_mouse_update();
 }
 self.collapseButton.contentTintColor=quickInk();
 self.quickTitle.hidden=self.quickScroll.hidden=self.quickNote.hidden=self.quickTabs.hidden=self.quickHelpTitle.hidden=self.quickHelpText.hidden=self.quickReturn.hidden=self.quickBackdrop.hidden=!full;
 self.label.hidden=full;
 self.layer.backgroundColor=[NSColor colorWithCalibratedRed:0.04 green:0.045 blue:0.03 alpha:full?0.62:0.8].CGColor;
 self.state=full?NSVisualEffectStateActive:NSVisualEffectStateInactive;self.layer.cornerRadius=full?0:6;self.layer.borderWidth=full?0:1;
 self.quickPresets.hidden=self.quickPresetLabel.hidden=self.quickTab!=0;
 self.quickHint.hidden=self.quickSettings.hidden=self.quickTab!=2;
 for(NSUInteger i=0;i<self.quickRows.count;i++)self.quickRows[i].hidden=self.quickTab!=(i<6?0:1);
 for(NSButton *b in self.quickTabs.subviews){b.state=b.tag==self.quickTab?NSControlStateValueOn:NSControlStateValueOff;b.needsDisplay=YES;}
 int preset=settings_quick_preset?settings_quick_preset():-1;
 for(NSButton *b in self.quickPresets.subviews){b.state=b.tag==preset?NSControlStateValueOn:NSControlStateValueOff;b.needsDisplay=YES;}
 char line[128];int highlight=0;NSString *fps=hud_snapshot(0,line,sizeof line,&highlight)?@(line):@"FPS --";
 self.label.stringValue=fps;self.label.font=[NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightMedium];self.label.textColor=quickInk();
 NSMutableArray *details=[NSMutableArray new];for(int i=1;i<4;i++){char t[128];int hl;if(hud_snapshot(i,t,sizeof t,&hl))[details addObject:@(t)];}self.label.toolTip=[details componentsJoinedByString:@"\n"];
 self.textSize=NSMakeSize(0,16);
 if(full){
  NSArray *names=@[@(TOTK_UI("帧率上限","Frame limit")),@(TOTK_UI("动态分辨率","Dynamic resolution")),@(TOTK_UI("补帧","Frame generation")),@(TOTK_UI("渲染分辨率","Render resolution")),@(TOTK_UI("画面比例","Aspect ratio")),@(TOTK_UI("边缘平滑","Edge smoothing")),@(TOTK_UI("手柄类型","Controller")),@(TOTK_UI("鼠标视角","Mouse camera"))];
  for(NSUInteger i=0;i<self.quickRows.count;i++)self.quickRows[i].title=names[i];
  int cap=nvn_fps_cap?nvn_fps_cap():0;
  uint64_t size=runtime_output_size_current();unsigned w=(uint32_t)size,h=(uint32_t)(size>>32);
  NSString *picture=mfxup_output_enabled()?@"MetalFX 2K":w==1920&&h==1080?@(TOTK_UI("标准","Standard")):[NSString stringWithFormat:@"%u × %u",w,h];
  int mode=mfx_enabled();NSString *interp=mode==MFX_30?@"30 + 30":mode==MFX_HALF?@(TOTK_UI("半刷新率","Half refresh")):mode==MFX_MAX?@(TOTK_UI("不限帧","Unlimited")):@(TOTK_UI("关闭","Off"));
  int aspect=runtime_aspect_step();float ratio=runtime_aspect_now();
  NSString *wide=fabsf(ratio*9-21)<0.05f?@"21:9":[NSString stringWithFormat:@"%.2f:1",ratio];
  NSArray *values=@[cap?[NSString stringWithFormat:@"%d FPS",cap]:@(TOTK_UI("不限帧","Unlimited")),runtime_drs_enabled&&runtime_drs_enabled()?@(TOTK_UI("开启","On")):@(TOTK_UI("关闭","Off")),interp,picture,aspect==1?@(TOTK_UI("适配窗口","Fit window")):aspect==2?wide:@"16:9",taa_enabled()?@(TOTK_UI("开启","On")):@(TOTK_UI("关闭","Off")),pad_type_text(),runtime_mouse_enabled()?@(TOTK_UI("开启 · 收起后生效","On · collapse to play")):@(TOTK_UI("关闭","Off"))];
  for(NSUInteger i=0;i<self.quickRows.count;i++) {TOTKQuickRow *b=(TOTKQuickRow *)self.quickRows[i];b.value=values[i];b.on=i==1?(runtime_drs_enabled&&runtime_drs_enabled()):i==5?taa_enabled():i==7?runtime_mouse_enabled():NO;b.accessibilityLabel=[NSString stringWithFormat:@"%@：%@",b.title,b.value];b.needsDisplay=YES;}
  self.quickRows[0].enabled=nvn_fps_cap&&settings_quick_apply;self.quickRows[1].enabled=runtime_drs_enabled&&settings_quick_apply;self.quickRows[4].enabled=aspect>=0;
 }
 self.needsDisplay=YES;[self position];
}
@end

static BOOL quick_menu_key(NSEvent *e,BOOL down){
 if(!quickMenuOpen||!hud_compact()||(e.modifierFlags&NSEventModifierFlagCommand))return NO;
 BOOL navigation=e.keyCode==53||e.keyCode==48||e.keyCode==36||e.keyCode==49||(e.keyCode>=123&&e.keyCode<=126);
 if(!navigation)return NO;if(!down){runtime_input_key_synthetic(e.keyCode,0);return YES;}
 TOTKShortcutHelp *panel=(TOTKShortcutHelp *)shortcutHelp;if(!panel)return NO;
 if(e.keyCode==53){[panel toggleCollapsed:nil];return YES;}
 if(e.keyCode==48){NSInteger next=(panel.quickTab+((e.modifierFlags&NSEventModifierFlagShift)?2:1))%3;[panel quickTabAction:(id)panel.quickTabs.subviews[next]];return YES;}
 if(panel.quickTab==2){
  if(e.keyCode>=123&&e.keyCode<=126){panel.quickFocused=panel.quickFocused==8?9:8;panel.quickHint.state=panel.quickFocused==8?NSControlStateValueOn:NSControlStateValueOff;panel.quickSettings.state=panel.quickFocused==9?NSControlStateValueOn:NSControlStateValueOff;panel.quickHint.needsDisplay=panel.quickSettings.needsDisplay=YES;}
  else if(e.keyCode==36||e.keyCode==49){if(panel.quickFocused==9)[panel quickSettings:nil];else[panel quickHint:nil];}return YES;
 }
 NSArray *order=panel.quickTab==0?@[@0,@1,@3,@4,@5,@2]:@[@6,@7];NSUInteger i=[order indexOfObject:@(panel.quickFocused)];if(i==NSNotFound)i=0;
 if(e.keyCode==125||e.keyCode==126){i=(i+order.count+(e.keyCode==125?1:-1))%order.count;NSButton *row=panel.quickRows[[order[i] integerValue]];[panel focusQuickRow:row];[panel.quickBody scrollRectToVisible:row.frame];}
 else{TOTKQuickRow *row=(id)panel.quickRows[panel.quickFocused];row.direction=e.keyCode==123?-1:1;if(row.enabled)[panel quickAction:row];row.direction=1;}
 return YES;
}
