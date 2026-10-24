/* Native, mouse-operated options screen: every setting, drawn in the game's own style (QUICK_MENU_DESIGN.md). Values
   always come from live runtime state: settings_panel.m holds the model behind the graphics rows and writes settings.txt;
   the assistant's AI channel is assistant.json "channel", which the hint service reads before each question. */
#include "settings_file.h"
extern BOOL settings_quick_apply(int action) __attribute__((weak_import));
extern BOOL settings_quick_step(int action,int direction) __attribute__((weak_import));
extern int settings_quick_preset(void) __attribute__((weak_import));
extern const char *settings_quick_value(int action,int *flags) __attribute__((weak_import));
extern const char *settings_quick_status(int fps,int generated) __attribute__((weak_import));
extern int dm_gfx_fps_now(int *generated) __attribute__((weak_import));   // gfx/nvn/nvn_mtl.m (absent in tests)
static int quickFpsAtOpen=-1,quickGeneratedAtOpen;   // the frame rate when the menu opened: it pauses the game
extern int settings_quick_saving(void) __attribute__((weak_import));
extern void runtime_settings_pause(int paused) __attribute__((weak_import));
static NSString *pad_type_text(void);
void runtime_input_key_synthetic(unsigned code,int down);
@class TOTKQuickRow;
@interface TOTKShortcutHelp (QuickMenu)
-(void)buildQuickMenu;
-(void)refreshQuickMenu;
-(void)layoutQuickMenu;
-(void)quickAction:(NSButton *)sender;
-(void)quickTabAction:(NSButton *)sender;
-(void)focusQuickRow:(NSButton *)sender;
-(void)focusQuickHint;
-(NSArray<NSNumber *> *)quickOrder;
-(void)quickOpenChoices:(TOTKQuickRow *)row;
-(void)quickCloseChoices;
-(void)quickChoose:(NSButton *)sender;
@end
static NSColor *quickAccent(void){return [NSColor colorWithCalibratedRed:0.88 green:0.40 blue:0.015 alpha:1];}
static NSColor *quickGold(void){return [NSColor colorWithCalibratedRed:1 green:0.9 blue:0.50 alpha:1];}
static NSColor *quickInk(void){return [NSColor colorWithCalibratedRed:0.99 green:0.975 blue:0.85 alpha:1];}
static NSFont *quickFont(CGFloat size){return [NSFont fontWithName:@"PingFangSC-Regular" size:size]?:[NSFont systemFontOfSize:size];}

/* The rows, in the order each tab shows them: tab 0 画面 (below the presets), 1 操作, 2 辅助 (below the hint assistant).
   kind 0 is a value with previous / next arrows, 1 an on / off switch, 2 a value whose choices drop down (the arrow keys
   still step through them). Actions 1xx and the number keys' codes are
   settings_quick_step's; 22 and 26 press keys 6 and 7; 120 is the AI channel. */
enum { QUICK_CHANNEL=120, QUICK_HINT=-1 };
typedef struct { int action,tab,kind; const char *zh,*en,*help_zh,*help_en; } QuickRowSpec;
static const QuickRowSpec quickSpecs[]={
 {110,0,0,"帧率上限","Frame limit","限制最高帧率，兼顾流畅度与功耗。\n\n显示器刷新率可整除时，帧间隔会与显示节拍对齐。","Limit the frame rate to balance smoothness and power.\n\nWhen the display's refresh rate divides evenly, frames follow its beat."},
 {111,0,1,"动态分辨率","Dynamic resolution","帧时间超过上限时降低渲染分辨率，优先保持画面流畅。","Lowers the render resolution when a frame takes longer than the cap, to keep the game smooth."},
 {112,0,0,"最低分辨率","Lowest resolution","动态分辨率最多降到这个比例。打开动态分辨率后才能调整。","How far dynamic resolution may go down. Adjustable while dynamic resolution is on."},
 {113,0,0,"渲染分辨率","Render resolution","游戏实际渲染的画面大小。越高越清晰，也越吃显卡。\n\n重启游戏后生效。","The size the game renders at: sharper when higher, and heavier on the GPU.\n\nTakes effect after a restart."},
 {20,0,0,"画面","Picture","1080p 画面、MetalFX 放大到 2K，或原生 2K 画布（3 键）。","1080p, MetalFX upscaled to 2K, or the native 2K canvas (key 3)."},
 {23,0,1,"边缘平滑","Edge smoothing","使用 MetalFX 时间性抗锯齿平滑画面边缘（5 键）。","Smooth edges with MetalFX temporal anti-aliasing (key 5)."},
 {114,0,0,"各向异性过滤","Anisotropic filtering","让斜着看到的地面和远处的贴图更清楚。\n\n重启游戏后生效。","Sharper textures on ground and surfaces seen at an angle.\n\nTakes effect after a restart."},
 {19,0,0,"补帧","Frame generation","生成中间帧以改善观感（2 键）。部分模式在下一帧才生效，显示的是实际状态。","Generate intermediate frames (key 2). Some modes take effect at the next frame; the value shows the state in force."},
 {21,0,0,"画面比例","Aspect ratio","标准 16:9、适配窗口或宽屏（4 键）。","Standard 16:9, fit to the window, or widescreen (key 4)."},
 {22,1,0,"手柄类型","Controller","选择手柄按键布局，或自动识别连接的手柄。","Choose a controller layout or detect the connected controller automatically."},
 {26,1,1,"鼠标视角","Mouse camera","用鼠标控制视角。收起设置后生效；⌘Tab 可释放指针。","Control the camera with the mouse after closing settings. Command-Tab releases the pointer."},
 {QUICK_CHANNEL,2,2,"AI 渠道","AI channel","卡关助手先问哪个模型。它不可用或出错时，按顺序换下一个。\n\n下一个问题就用新的渠道，不用重启游戏。","Which model the hint assistant asks first. When it is unavailable or fails, the next one in order answers.\n\nThe next question uses the new channel; no restart needed."},
};
enum { QUICK_ROWS=sizeof(quickSpecs)/sizeof(quickSpecs[0]) };

/* The assistant's settings and the channels' state, next to the game's other files (TOTK_ASSISTANT_FOLDER: tests only). */
static NSString *quickAssistantPath(NSString *name){
 const char *folder=getenv("TOTK_ASSISTANT_FOLDER");
 NSString *base=folder&&*folder?@(folder):[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/MacNativeGames/TOTK"];
 return [base stringByAppendingPathComponent:name];
}
static NSDictionary *quickJSONFile(NSString *path){
 NSData *data=[NSData dataWithContentsOfFile:path];id value=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
 return [value isKindOfClass:NSDictionary.class]?value:nil;
}
static NSArray<NSString *> *quickChannels(void){return @[@"auto",@"claude-code",@"agent",@"codex",@"vertex-claude-code",@"vertex"];}
static NSString *quickChannel(void){
 id channel=quickJSONFile(quickAssistantPath(@"assistant.json"))[@"channel"];
 return [channel isKindOfClass:NSString.class]&&[quickChannels() containsObject:channel]?channel:@"auto";
}
/* What the hint service last found about each channel (tools/hint_assistant: hint-backends.json), or nil. */
static NSDictionary *quickChannelState(NSString *name){
 id all=quickJSONFile(quickAssistantPath(@"hint-backends.json"))[@"backends"];id one=[all isKindOfClass:NSDictionary.class]?all[name]:nil;
 return [one isKindOfClass:NSDictionary.class]?one:nil;
}
/* A channel as the menu names it: the model, and in brackets the way it is reached (this Mac's own sign-in, Vertex AI). The
   hint service writes the same names (backends.label); these are for before it first ran. */
static NSString *quickChannelLabel(NSString *name){
 if([name isEqual:@"auto"])return @(TOTK_UI("自动（按顺序）","Automatic (in order)"));
 id label=quickChannelState(name)[@"label"];if([label isKindOfClass:NSString.class]&&[label length])return label;
 if([name isEqual:@"claude-code"])return @(TOTK_UI("Claude Code（本机）","Claude Code (this Mac)"));
 if([name isEqual:@"codex"])return @(TOTK_UI("Codex（本机）","Codex (this Mac)"));
 if([name isEqual:@"vertex-claude-code"])return @"Claude Code（Vertex AI）";
 if([name isEqual:@"vertex"])return @"Claude（Vertex AI）";
 id agent=quickJSONFile(quickAssistantPath(@"assistant.json"))[@"agent"];
 NSString *provider=[agent isKindOfClass:NSDictionary.class]&&[agent[@"provider"] isKindOfClass:NSString.class]?agent[@"provider"]:@"";
 NSString *model=[agent isKindOfClass:NSDictionary.class]&&[agent[@"model"] isKindOfClass:NSString.class]?agent[@"model"]:@"";
 if([provider isEqual:@"gemini"])return [NSString stringWithFormat:@"%@（Vertex AI）",[model hasPrefix:@"gemini-4"]||!model.length?@"Gemini 4":model];
 return model.length?model:@(TOTK_UI("内置智能体","Built-in agent"));
}
/* A channel written into assistant.json with everything else the file holds. */
static BOOL quickChannelSet(NSString *name){
 NSString *path=quickAssistantPath(@"assistant.json");
 NSDictionary *existing=quickJSONFile(path);
 if(!existing&&[NSFileManager.defaultManager fileExistsAtPath:path])return NO;   // a file being edited by hand: leave it alone
 NSMutableDictionary *next=existing?[existing mutableCopy]:[NSMutableDictionary new];
 next[@"channel"]=name;
 NSData *data=[NSJSONSerialization dataWithJSONObject:next options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:nil];
 [NSFileManager.defaultManager createDirectoryAtPath:path.stringByDeletingLastPathComponent withIntermediateDirectories:YES attributes:nil error:nil];
 return data&&[data writeToFile:path options:NSDataWritingAtomic error:nil];
}
/* The next channel in either direction (the arrow keys). */
static BOOL quickChannelStep(int direction){
 NSArray *names=quickChannels();NSUInteger i=[names indexOfObject:quickChannel()];
 return quickChannelSet(names[(i+names.count+(direction<0?-1:1))%names.count]);
}
/* Each channel and whether it can answer here, as the hint service last found (below the AI channel row). */
static NSString *quickChannelList(void){
 NSMutableArray *lines=[NSMutableArray arrayWithObject:@(TOTK_UI("各渠道状态","Channels"))];NSString *current=quickChannel();
 for(NSString *name in quickChannels()){if([name isEqual:@"auto"])continue;NSDictionary *state=quickChannelState(name);if(!state)continue;
  id why=state[@"why"];NSString *mark=[name isEqual:current]?@(TOTK_UI(" · 当前"," · current")):@"";
  [lines addObject:[NSString stringWithFormat:@"%@　%@%@",quickChannelLabel(name),[state[@"ok"] boolValue]?@(TOTK_UI("可用","available"))
   :[why isKindOfClass:NSString.class]&&[why length]?[NSString stringWithFormat:@(TOTK_UI("不可用：%@","unavailable: %@")),why]:@(TOTK_UI("不可用","unavailable")),mark]];}
 if(lines.count==1)[lines addObject:@(TOTK_UI("打开一次卡关助手后，这里会显示各渠道是否可用。","Whether each channel works shows here after the hint assistant has been opened once."))];
 return [lines componentsJoinedByString:@"\n"];
}

// Shared text metrics keep the compact label and settings title on one baseline.
static NSDictionary *compactAttributes(void){return @{NSFontAttributeName:quickFont(12),NSForegroundColorAttributeName:quickInk()};}
@interface TOTKCompactLabel:NSTextField
@end
@implementation TOTKCompactLabel
-(void)drawRect:(NSRect)dirty{
 if(!hud_compact()||fps_overlay_full_hud()){[super drawRect:dirty];return;}
 NSDictionary *a=compactAttributes();NSSize size=[self.stringValue sizeWithAttributes:a];
 [self.stringValue drawAtPoint:NSMakePoint(NSWidth(self.bounds)-size.width,(NSHeight(self.bounds)-size.height)/2) withAttributes:a];
}
@end
@interface TOTKCollapseButton:NSButton
@end
@implementation TOTKCollapseButton
-(void)drawRect:(NSRect)dirty{
 if(fps_overlay_full_hud()){[super drawRect:dirty];return;}
 NSDictionary *a=compactAttributes();NSSize size=[self.title sizeWithAttributes:a];CGFloat h=NSHeight(self.bounds);
 [self.title drawAtPoint:NSMakePoint(27,(h-size.height)/2) withAttributes:a];
 NSImage *gear=[NSImage imageWithSystemSymbolName:@"gearshape" accessibilityDescription:nil];
 NSImageSymbolConfiguration *cfg=[NSImageSymbolConfiguration configurationWithPaletteColors:@[quickInk()]];
 gear=[gear imageWithSymbolConfiguration:cfg];[gear drawInRect:NSMakeRect(5,(h-14)/2,14,14) fromRect:NSZeroRect operation:NSCompositingOperationSourceOver fraction:self.highlighted?0.65:1 respectFlipped:YES hints:nil];
}
@end
@interface TOTKQuickBlur:NSVisualEffectView
@end
@implementation TOTKQuickBlur
-(NSView *)hitTest:(NSPoint)p{(void)p;return nil;}
@end
@interface TOTKQuickDecoration:NSView
@end
@implementation TOTKQuickDecoration
-(NSView *)hitTest:(NSPoint)p{(void)p;return nil;}
-(void)drawRect:(NSRect)dirty{[(TOTKShortcutHelp *)self.superview drawQuickDecoration:dirty];}
@end
static void quickText(NSString *text,NSRect r,CGFloat size,NSColor *ink,NSTextAlignment alignment){
 NSMutableParagraphStyle *p=[NSMutableParagraphStyle new];p.alignment=alignment;p.lineBreakMode=NSLineBreakByTruncatingTail;
 [text drawInRect:r withAttributes:@{NSFontAttributeName:quickFont(size),NSForegroundColorAttributeName:ink,NSParagraphStyleAttributeName:p}];
}
@interface TOTKQuickRow:NSButton
@property(copy) NSString *value,*note;   // note: a short remark beside the name, in gold ("重启后生效")
@property BOOL hovered,focused,binary,on,dropdown;
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
 if(self.dropdown&&p.x>=split&&self.enabled){[(TOTKShortcutHelp *)self.target focusQuickRow:self];[(TOTKShortcutHelp *)self.target quickOpenChoices:self];return;}
 self.direction=p.x>=split&&p.x<split+(NSWidth(self.bounds)-split)/2?-1:1;
 if(self.binary&&p.x>=split){BOOL requested=p.x<split+(NSWidth(self.bounds)-split)/2;if(requested==self.on){[(TOTKShortcutHelp *)self.target focusQuickRow:self];return;}}
 [super mouseDown:e];self.direction=1;
}
-(void)drawRect:(NSRect)dirty{
 (void)dirty;CGFloat w=NSWidth(self.bounds),h=NSHeight(self.bounds),split=w*0.51;
 BOOL hot=self.enabled&&(self.focused||self.hovered||self.highlighted);CGFloat font=h>=44?17:h>=34?14:13;
 [[NSColor colorWithCalibratedRed:0.68 green:0.65 blue:0.57 alpha:0.24] setFill];
 [[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(self.bounds,0,2) xRadius:3 yRadius:3] fill];
 NSRect box=NSMakeRect(split,4,w-split-4,h-8);
 [[NSColor colorWithCalibratedWhite:0.015 alpha:0.87] setFill];[[NSBezierPath bezierPathWithRoundedRect:box xRadius:3 yRadius:3] fill];
 [[quickInk() colorWithAlphaComponent:0.23] setStroke];[[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(box,1,1) xRadius:2 yRadius:2] stroke];
 NSColor *ink=self.enabled?quickInk():[quickInk() colorWithAlphaComponent:0.4];
 CGFloat noteWidth=self.note.length?MIN(split*0.45,[self.note sizeWithAttributes:@{NSFontAttributeName:quickFont(font-3)}].width+4):0;
 quickText(self.title,NSMakeRect(18,(h-font-5)/2,split-28-noteWidth,font+7),font,ink,NSTextAlignmentLeft);
 if(noteWidth)quickText(self.note,NSMakeRect(split-10-noteWidth,(h-font+1)/2,noteWidth,font+4),font-3,quickGold(),NSTextAlignmentRight);
 NSRect choice=NSInsetRect(box,4,4);
 if(self.binary){CGFloat half=choice.size.width/2;NSRect selected=choice;selected.size.width=half;if(!self.on)selected.origin.x+=half;
  [[quickAccent() colorWithAlphaComponent:self.enabled?1:0.25] setFill];[[NSBezierPath bezierPathWithRoundedRect:selected xRadius:2 yRadius:2] fill];
  quickText(@(TOTK_UI("开启","On")),NSMakeRect(choice.origin.x,(h-font-5)/2,half,font+7),font,self.on?ink:[ink colorWithAlphaComponent:0.5],NSTextAlignmentCenter);
  quickText(@(TOTK_UI("关闭","Off")),NSMakeRect(choice.origin.x+half,(h-font-5)/2,half,font+7),font,!self.on?ink:[ink colorWithAlphaComponent:0.5],NSTextAlignmentCenter);
 }else{
  if(hot){[quickAccent() setFill];[[NSBezierPath bezierPathWithRoundedRect:choice xRadius:2 yRadius:2] fill];}
  quickText(self.value?:@"",NSMakeRect(split+27,(h-font-5)/2,w-split-58,font+7),font,ink,NSTextAlignmentCenter);
  if(self.dropdown){CGFloat x=NSMaxX(box)-16,y=h/2;NSBezierPath *caret=[NSBezierPath bezierPath];   // ▾: the choices open below
   CGFloat down=self.isFlipped?1:-1;   // a button draws flipped: +y is down
   [caret moveToPoint:NSMakePoint(x-5,y-3*down)];[caret lineToPoint:NSMakePoint(x+5,y-3*down)];[caret lineToPoint:NSMakePoint(x,y+3*down)];[caret closePath];[ink setFill];[caret fill];}
  else for(int i=0;i<2;i++){CGFloat x=i?NSMaxX(box)-14:NSMinX(box)+14,y=h/2;NSBezierPath *arrow=[NSBezierPath bezierPath];
   [arrow moveToPoint:NSMakePoint(x+(i?-3:3),y+5)];[arrow lineToPoint:NSMakePoint(x+(i?3:-3),y)];[arrow lineToPoint:NSMakePoint(x+(i?-3:3),y-5)];[arrow closePath];[ink setFill];[arrow fill];}
 }
 if(hot){[NSGraphicsContext saveGraphicsState];NSShadow *glow=[NSShadow new];glow.shadowColor=[quickGold() colorWithAlphaComponent:0.5];glow.shadowBlurRadius=5;[glow set];[quickGold() setStroke];NSBezierPath *edge=[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(box,-1,-1) xRadius:4 yRadius:4];edge.lineWidth=2;[edge stroke];[NSGraphicsContext restoreGraphicsState];}
}
@end
@interface TOTKQuickPreset:TOTKQuickRow
@end
@implementation TOTKQuickPreset
-(void)drawRect:(NSRect)dirty{
 (void)dirty;BOOL hot=self.enabled&&(self.hovered||self.highlighted||self.focused);BOOL selected=self.state==NSControlStateValueOn;
 [(selected?quickAccent():[NSColor colorWithCalibratedWhite:0.025 alpha:0.65]) setFill];NSRect r=NSInsetRect(self.bounds,1,2);[[NSBezierPath bezierPathWithRoundedRect:r xRadius:2 yRadius:2] fill];
 [[quickInk() colorWithAlphaComponent:hot?0.9:0.25] setStroke];NSBezierPath *edge=[NSBezierPath bezierPathWithRoundedRect:r xRadius:2 yRadius:2];edge.lineWidth=hot?2:0.6;[edge stroke];
 CGFloat font=NSHeight(self.bounds)>=40?16:NSHeight(self.bounds)>=34?13:12;quickText(self.title,NSMakeRect(5,(NSHeight(self.bounds)-font-5)/2,NSWidth(self.bounds)-10,font+7),font,self.enabled?quickInk():[quickInk() colorWithAlphaComponent:0.4],NSTextAlignmentCenter);
}
@end
/* A row's choices, dropped down over the menu: the whole menu catches the click that closes them, the list sits under (or
   above) the row's value box. Esc closes, Up / Down move, Return or Space choose. */
@interface TOTKQuickChoices:NSView
@property NSRect list;
@property(strong) NSMutableArray<TOTKQuickRow *> *options;
@property NSInteger highlighted;
@end
@implementation TOTKQuickChoices
-(BOOL)isOpaque{return NO;}
-(void)mouseDown:(NSEvent *)e{(void)e;[(TOTKShortcutHelp *)self.superview quickCloseChoices];}   // outside every option
-(void)drawRect:(NSRect)dirty{
 (void)dirty;NSRect box=NSInsetRect(self.list,-6,-6);
 [NSGraphicsContext saveGraphicsState];NSShadow *shade=[NSShadow new];shade.shadowColor=[NSColor colorWithWhite:0 alpha:0.7];shade.shadowBlurRadius=14;shade.shadowOffset=NSMakeSize(0,-4);[shade set];
 [[NSColor colorWithCalibratedRed:0.03 green:0.035 blue:0.025 alpha:0.97] setFill];[[NSBezierPath bezierPathWithRoundedRect:box xRadius:5 yRadius:5] fill];[NSGraphicsContext restoreGraphicsState];
 [[quickGold() colorWithAlphaComponent:0.55] setStroke];NSBezierPath *edge=[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(box,0.5,0.5) xRadius:5 yRadius:5];edge.lineWidth=1;[edge stroke];
}
-(void)highlight:(NSInteger)i{self.highlighted=(i+(NSInteger)self.options.count)%(NSInteger)self.options.count;for(NSUInteger k=0;k<self.options.count;k++){self.options[k].focused=(NSInteger)k==self.highlighted;self.options[k].needsDisplay=YES;}}
@end
@implementation TOTKShortcutHelp (QuickMenu)
-(void)buildQuickMenu{
 self.appearance=[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];self.quickTab=0;self.quickFocused=0;
 self.quickBlur=[TOTKQuickBlur new];self.quickBlur.material=NSVisualEffectMaterialHUDWindow;self.quickBlur.blendingMode=NSVisualEffectBlendingModeWithinWindow;self.quickBlur.state=NSVisualEffectStateActive;[self addSubview:self.quickBlur positioned:NSWindowBelow relativeTo:self.label];
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
 self.quickRows=[NSMutableArray new];
 for(int i=0;i<QUICK_ROWS;i++){TOTKQuickRow *b=[TOTKQuickRow new];b.title=@(TOTK_UI(quickSpecs[i].zh,quickSpecs[i].en));b.tag=quickSpecs[i].action;b.target=self;b.action=@selector(quickAction:);b.bordered=NO;b.direction=1;b.binary=quickSpecs[i].kind==1;b.dropdown=quickSpecs[i].kind==2;[self.quickBody addSubview:b];[self.quickRows addObject:b];}
 self.quickHelpTitle=[NSTextField labelWithString:@""];self.quickHelpTitle.textColor=quickInk();self.quickHelpTitle.font=[NSFont systemFontOfSize:24 weight:NSFontWeightMedium];[self addSubview:self.quickHelpTitle];
 self.quickHelpText=[NSTextField wrappingLabelWithString:@""];self.quickHelpText.textColor=quickInk();self.quickHelpText.font=[NSFont systemFontOfSize:16];self.quickHelpText.maximumNumberOfLines=0;[self addSubview:self.quickHelpText];
 self.quickStatus=[NSTextField labelWithString:@""];self.quickStatus.textColor=[quickInk() colorWithAlphaComponent:0.7];self.quickStatus.lineBreakMode=NSLineBreakByTruncatingTail;self.quickStatus.alignment=NSTextAlignmentRight;[self addSubview:self.quickStatus];
 self.quickChannelList=[NSTextField wrappingLabelWithString:@""];self.quickChannelList.textColor=[quickInk() colorWithAlphaComponent:0.8];self.quickChannelList.maximumNumberOfLines=0;[self.quickBody addSubview:self.quickChannelList];
 self.quickHint=[TOTKQuickPreset buttonWithTitle:@(TOTK_UI("打开卡关助手 · 逐级提示  8","Open the hint assistant  8")) target:self action:@selector(quickHint:)];self.quickHint.bordered=NO;[self.quickBody addSubview:self.quickHint];
 self.quickReturn=[TOTKQuickPreset buttonWithTitle:@(TOTK_UI("返回游戏  Esc","Return to game  Esc")) target:self action:@selector(toggleCollapsed:)];self.quickReturn.bordered=NO;[self addSubview:self.quickReturn];
 self.quickNote=[NSTextField labelWithString:@(TOTK_UI("鼠标点击调整 · 方向键选择 · Tab 切换分类","Click to adjust · Arrow keys select · Tab changes category"))];self.quickNote.textColor=[quickInk() colorWithAlphaComponent:0.7];self.quickNote.font=[NSFont systemFontOfSize:11];[self addSubview:self.quickNote];
 [self focusQuickRow:self.quickRows[0]];
}
/* The rows the current tab shows, top to bottom (QUICK_HINT: the hint assistant button above 辅助's rows). */
-(NSArray<NSNumber *> *)quickOrder{
 NSMutableArray *order=[NSMutableArray array];if(self.quickTab==2)[order addObject:@(QUICK_HINT)];
 for(int i=0;i<QUICK_ROWS;i++)if(quickSpecs[i].tab==self.quickTab)[order addObject:@(i)];
 return order;
}
-(void)focusQuickRow:(NSButton *)sender{
 if(sender==self.quickHint){[self focusQuickHint];return;}
 NSUInteger index=[self.quickRows indexOfObject:sender];if(index==NSNotFound)return;self.quickFocused=(NSInteger)index;
 const QuickRowSpec *spec=&quickSpecs[index];
 self.quickHelpTitle.stringValue=sender.title;
 self.quickHelpText.stringValue=@(TOTK_UI(spec->help_zh,spec->help_en));
 self.quickHint.state=NSControlStateValueOff;((TOTKQuickRow *)self.quickHint).focused=NO;self.quickHint.needsDisplay=YES;
 for(NSUInteger i=0;i<self.quickRows.count;i++){TOTKQuickRow *b=(id)self.quickRows[i];b.hovered=NO;b.focused=i==index;b.needsDisplay=YES;}
}
-(void)focusQuickHint{
 self.quickFocused=QUICK_HINT;((TOTKQuickRow *)self.quickHint).focused=YES;self.quickHint.needsDisplay=YES;
 for(TOTKQuickRow *b in self.quickRows){b.focused=NO;b.needsDisplay=YES;}
 self.quickHelpTitle.stringValue=@(TOTK_UI("卡关助手","Hint assistant"));
 self.quickHelpText.stringValue=@(TOTK_UI("卡住时问露珠：先给方向，再给要用什么，最后才是完整解法。\n\n也可以在游戏里随时按 8 打开。","Ask Riju when you are stuck: where to go first, then what to use, the full solution last.\n\nKey 8 opens it any time in the game."));
}
-(void)quickTabAction:(NSButton *)sender{
 self.quickTab=sender.tag;[self refreshQuickMenu];
 NSNumber *first=[self quickOrder].firstObject;
 if(first.integerValue==QUICK_HINT)[self focusQuickHint];else[self focusQuickRow:self.quickRows[first.integerValue]];
 [self layoutQuickMenu];[self.quickBody scrollPoint:NSMakePoint(0,NSHeight(self.quickBody.bounds))];[self.quickScroll flashScrollers];[self.window makeFirstResponder:self.window.contentView];
}
-(void)layoutQuickMenu{
 CGFloat w=NSWidth(self.bounds),h=NSHeight(self.bounds);BOOL full=fps_overlay_full_hud();
 self.collapseButton.frame=full?NSMakeRect(w-80,h-35,70,25):NSMakeRect(w-80,2,80,28);
 self.quickDivider.hidden=full;self.quickDivider.frame=NSMakeRect(w-88,9,0.7,14);if(!full)return;
 self.quickBackdrop.frame=self.bounds;self.quickBlur.frame=self.bounds;
 self.quickTitle.frame=NSMakeRect(80,h*0.89,w-160,36);
 CGFloat tw=MIN(420,w-80);self.quickTabs.frame=NSMakeRect((w-tw)/2,h*0.795,tw,40);
 for(NSView *v in self.quickTabs.subviews)v.frame=NSMakeRect(v.tag*tw/3,0,tw/3,40);
 BOOL wide=w>=820;CGFloat x=w*0.065,bw=wide?w*0.55:w*0.87,helpHeight=wide?0:66;
 NSArray<NSNumber *> *order=[self quickOrder];NSInteger header=self.quickTab==0?1:0;   // 画面: the presets above the rows
 // Rows shrink to fit the tab (down to 28 pt); a window too small for that scrolls.
 CGFloat available=MAX(80,h*0.52-helpHeight),row=MAX(28,MIN(52,floor(available/MAX(7,order.count+header))));
 self.quickScroll.frame=NSMakeRect(x,h*0.20+helpHeight,bw,available);
 CGFloat content=MAX(available,row*(order.count+header));
 [self.quickBody setFrameSize:NSMakeSize(bw,content)];
 self.quickPresets.frame=NSMakeRect(bw*0.51,content-row,bw*0.49-4,row);
 self.quickPresetLabel.frame=NSMakeRect(18,content-row+(row-22)/2,bw*0.51-28,24);self.quickPresetLabel.font=quickFont(row>=44?17:row>=34?14:13);
 for(NSView *v in self.quickPresets.subviews)v.frame=NSMakeRect(v.tag*NSWidth(self.quickPresets.bounds)/3,0,NSWidth(self.quickPresets.bounds)/3,row);
 for(NSUInteger i=0;i<order.count;i++){CGFloat y=content-row*(i+1+header);NSInteger n=order[i].integerValue;
  (n==QUICK_HINT?self.quickHint:self.quickRows[n]).frame=NSMakeRect(0,y,bw,row);}
 CGFloat listTop=content-row*(order.count+header)-12;self.quickChannelList.font=quickFont(row>=44?14:12);
 self.quickChannelList.frame=NSMakeRect(18,MAX(0,listTop-row*4.5),bw-36,MIN(row*4.5,listTop));
 if(wide){self.quickHelpTitle.frame=NSMakeRect(w*0.63+24,h*0.715-62,w*0.33-48,38);self.quickHelpText.frame=NSMakeRect(w*0.63+24,h*0.24+24,w*0.33-48,MAX(50,h*0.475-126));
  CGFloat noteWidth=MAX(40,(w-250-x)*0.5);self.quickStatus.frame=NSMakeRect(x+noteWidth+12,22,MAX(40,w-214-(x+noteWidth+12)),20);}   // in the footer, beside the note
 else{self.quickHelpTitle.frame=NSMakeRect(x,111,bw,24);self.quickHelpText.frame=NSMakeRect(x,71,bw,40);self.quickStatus.frame=NSMakeRect(x,48,bw,18);}
 self.quickHelpTitle.font=quickFont(wide?24:15);self.quickHelpText.font=quickFont(wide?16:12);self.quickStatus.font=[NSFont monospacedDigitSystemFontOfSize:11 weight:NSFontWeightRegular];
 self.quickReturn.frame=NSMakeRect(w-202,15,180,32);self.quickNote.frame=NSMakeRect(x,22,wide?MAX(40,(w-250-x)*0.5):MAX(40,w-250-x),20);
}
static NSString *quick_saved_note(BOOL ok){
 if(!ok||(settings_quick_saving&&settings_quick_saving()<0))return @(TOTK_UI("已应用，但未能保存设置","Applied; settings could not be saved"));
 return settings_quick_saving&&settings_quick_saving()>0?@(TOTK_UI("已应用并保存","Applied and saved")):@(TOTK_UI("已应用 · 仅本次会话","Applied · This session only"));
}
-(void)quickPreset:(NSButton *)sender{
 BOOL ok=settings_quick_apply&&settings_quick_apply(100+(int)sender.tag);
 self.quickNote.stringValue=ok?@(TOTK_UI("预设已应用 · 部分选项需重启","Preset applied · Some options require restart")):quick_saved_note(NO);[self refresh];
}
-(void)quickAction:(NSButton *)sender{
 [self focusQuickRow:sender];int direction=(int)((TOTKQuickRow *)sender).direction;if(!direction)direction=1;
 if(sender.tag==QUICK_CHANNEL){BOOL ok=quickChannelStep(direction);
  self.quickNote.stringValue=ok?[NSString stringWithFormat:@(TOTK_UI("下一个问题起先用 %@","From the next question: %@ first")),quickChannelLabel(quickChannel())]:@(TOTK_UI("没能改写 assistant.json","Could not write assistant.json"));}
 else if(sender.tag==22||sender.tag==26||!settings_quick_step){int count=direction<0&&sender.tag==22?GAMEPAD_TYPE_COUNT-1:1;for(int i=0;i<count;i++){runtime_input_key_synthetic((unsigned)sender.tag,1);runtime_input_key_synthetic((unsigned)sender.tag,0);}}
 else self.quickNote.stringValue=quick_saved_note(settings_quick_step((int)sender.tag,direction));
 [self refresh];if(sender.tag==QUICK_CHANNEL)[self focusQuickRow:sender];[self.window makeFirstResponder:self.window.contentView];
}
-(void)quickOpenChoices:(TOTKQuickRow *)row{
 [self quickCloseChoices];if(row.tag!=QUICK_CHANNEL)return;
 TOTKQuickChoices *choices=[[TOTKQuickChoices alloc] initWithFrame:self.bounds];choices.options=[NSMutableArray array];
 NSArray<NSString *> *names=quickChannels();NSString *current=quickChannel();
 CGFloat split=NSWidth(row.bounds)*0.51,height=MAX(30,MIN(40,NSHeight(row.bounds)-4));
 NSRect value=[row convertRect:NSMakeRect(split,0,NSWidth(row.bounds)-split-4,NSHeight(row.bounds)) toView:self];
 CGFloat total=height*names.count,y=NSMinY(value)-total-6;
 if(y<10)y=MIN(NSMaxY(value)+6,NSHeight(self.bounds)-total-10);   // no room below: above the row
 choices.list=NSMakeRect(NSMinX(value),y,NSWidth(value),total);
 for(NSUInteger i=0;i<names.count;i++){
  NSDictionary *state=quickChannelState(names[i]);BOOL unusable=state&&![state[@"ok"] boolValue]&&![names[i] isEqual:@"auto"];
  NSString *title=unusable?[quickChannelLabel(names[i]) stringByAppendingString:@(TOTK_UI("  · 不可用","  · unavailable"))]:quickChannelLabel(names[i]);
  TOTKQuickPreset *option=[TOTKQuickPreset buttonWithTitle:title target:self action:@selector(quickChoose:)];option.bordered=NO;option.tag=(NSInteger)i;
  option.state=[names[i] isEqual:current]?NSControlStateValueOn:NSControlStateValueOff;
  option.frame=NSMakeRect(NSMinX(choices.list),NSMaxY(choices.list)-height*(i+1),NSWidth(choices.list),height);
  option.accessibilityLabel=title;[choices addSubview:option];[choices.options addObject:option];
 }
 [choices highlight:(NSInteger)[names indexOfObject:current]];
 self.quickChoices=choices;[self addSubview:choices];
}
-(void)quickCloseChoices{[self.quickChoices removeFromSuperview];self.quickChoices=nil;}
-(void)quickChoose:(NSButton *)sender{
 NSString *name=quickChannels()[(NSUInteger)sender.tag];[self quickCloseChoices];
 BOOL ok=quickChannelSet(name);
 self.quickNote.stringValue=ok?[NSString stringWithFormat:@(TOTK_UI("下一个问题起先用 %@","From the next question: %@ first")),quickChannelLabel(name)]:@(TOTK_UI("没能改写 assistant.json","Could not write assistant.json"));
 [self refresh];for(TOTKQuickRow *row in self.quickRows)if(row.tag==QUICK_CHANNEL)[self focusQuickRow:row];[self.window makeFirstResponder:self.window.contentView];
}
-(void)quickHint:(id)sender{(void)sender;NSEvent *e=[NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:self.window.windowNumber context:nil characters:@"8" charactersIgnoringModifiers:@"8" isARepeat:NO keyCode:28];totk_hint_key(e,YES);}
/* What a row shows for a setting this file reads itself (keys 6 and 7, the AI channel); the others come from
   settings_quick_value. */
-(NSString *)quickValue:(TOTKQuickRow *)row flags:(int *)flags{
 *flags=SETTINGS_ROW_ENABLED;
 if(row.tag==22)return pad_type_text();
 if(row.tag==26){if(runtime_mouse_enabled())*flags|=SETTINGS_ROW_ON;return runtime_mouse_enabled()?@(TOTK_UI("开启 · 收起后生效","On · collapse to play")):@(TOTK_UI("关闭","Off"));}
 if(row.tag==QUICK_CHANNEL)return quickChannelLabel(quickChannel());
 const char *value=settings_quick_value?settings_quick_value((int)row.tag,flags):NULL;
 if(!value){*flags=0;return @"--";}
 return @(value);
}
-(void)refreshQuickMenu {
 BOOL full=fps_overlay_full_hud(),wasOpen=quickMenuOpen;quickMenuOpen=full&&!self.hidden;
 if(quickMenuOpen&&!wasOpen){quickGeneratedAtOpen=0;quickFpsAtOpen=dm_gfx_fps_now?dm_gfx_fps_now(&quickGeneratedAtOpen):-1;}   // before the pause below
 if(runtime_settings_pause)runtime_settings_pause(quickMenuOpen&&(!bootOverlay||bootOverlay.hidden));
 if(window&&[window.contentView isKindOfClass:TOTKInputView.class]){
  BOOL hide=!quickMenuOpen&&window.isKeyWindow&&(window.styleMask&NSWindowStyleMaskFullScreen);
  TOTKInputView *input=(TOTKInputView *)window.contentView;
  if(input.cursorAutoHideActive!=hide)[input setCursorAutoHideEnabled:hide];front_mouse_update();
 }
 self.collapseButton.contentTintColor=quickInk();
 self.quickTitle.hidden=self.quickScroll.hidden=self.quickNote.hidden=self.quickTabs.hidden=self.quickHelpTitle.hidden=self.quickHelpText.hidden=self.quickReturn.hidden=self.quickBackdrop.hidden=!full;
 self.quickStatus.hidden=!full||self.quickTab!=0;
 if(self.quickChoices&&(!full||self.quickTab!=2))[self quickCloseChoices];
 self.label.hidden=full;
 self.layer.backgroundColor=[NSColor colorWithCalibratedRed:0.04 green:0.045 blue:0.03 alpha:full?0.62:0].CGColor;
 self.quickBlur.hidden=!full;self.layer.cornerRadius=0;self.layer.borderWidth=0;
 self.quickPresets.hidden=self.quickPresetLabel.hidden=self.quickTab!=0;
 self.quickHint.hidden=self.quickChannelList.hidden=self.quickTab!=2;
 for(NSUInteger i=0;i<self.quickRows.count;i++)self.quickRows[i].hidden=quickSpecs[i].tab!=self.quickTab;
 for(NSButton *b in self.quickTabs.subviews){b.state=b.tag==self.quickTab?NSControlStateValueOn:NSControlStateValueOff;b.needsDisplay=YES;}
 int preset=settings_quick_preset?settings_quick_preset():-1;
 for(NSButton *b in self.quickPresets.subviews){b.state=b.tag==preset?NSControlStateValueOn:NSControlStateValueOff;b.needsDisplay=YES;}
 char line[128];int highlight=0;NSString *fps=hud_snapshot(0,line,sizeof line,&highlight)?@(line):@"FPS --";
 // Only the measured frame rate belongs in the compact HUD; retain the full line in its tooltip.
 NSString *rate=@"--";
 NSArray *tokens=[fps componentsSeparatedByCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
 if(tokens.count>1){
  NSString *value=[tokens[0] isEqualToString:@"FPS"]?tokens[1]:tokens[0];
  NSRange end=[value rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789+-"] invertedSet]];
  rate=end.location==NSNotFound?value:[value substringToIndex:end.location];if(!rate.length)rate=@"--";
 }
 self.label.stringValue=[NSString stringWithFormat:@"%@ FPS",rate];
 self.label.font=[NSFont monospacedDigitSystemFontOfSize:12 weight:NSFontWeightRegular];self.label.textColor=quickInk();self.label.alignment=NSTextAlignmentRight;
 NSShadow *shadow=[NSShadow new];shadow.shadowColor=[NSColor colorWithWhite:0 alpha:0.85];shadow.shadowOffset=NSMakeSize(0,-1);shadow.shadowBlurRadius=3;
 self.label.shadow=full?nil:shadow;self.collapseButton.shadow=full?nil:shadow;
 NSMutableArray *details=[NSMutableArray arrayWithObject:fps];for(int i=1;i<4;i++){char t[128];int hl;if(hud_snapshot(i,t,sizeof t,&hl))[details addObject:@(t)];}self.label.toolTip=[details componentsJoinedByString:@"\n"];
 self.textSize=NSMakeSize(0,16);
 if(full){
  for(NSUInteger i=0;i<self.quickRows.count;i++){TOTKQuickRow *b=(TOTKQuickRow *)self.quickRows[i];int flags=0;
   b.title=@(TOTK_UI(quickSpecs[i].zh,quickSpecs[i].en));b.value=[self quickValue:b flags:&flags];
   b.enabled=(flags&SETTINGS_ROW_ENABLED)!=0;b.on=(flags&SETTINGS_ROW_ON)!=0;
   b.note=flags&SETTINGS_ROW_RESTART?@(TOTK_UI("重启后生效","after restart")):nil;
   b.accessibilityLabel=[NSString stringWithFormat:@"%@：%@%@",b.title,b.value,b.note?[@" · " stringByAppendingString:b.note]:@""];b.needsDisplay=YES;}
  if(self.quickTab==2)self.quickChannelList.stringValue=quickChannelList();
  self.quickStatus.stringValue=settings_quick_status?@(settings_quick_status(quickFpsAtOpen,quickGeneratedAtOpen)):@"";
 }
 self.needsDisplay=YES;[self position];
}
@end

static BOOL quick_menu_key(NSEvent *e,BOOL down){
 if(!quickMenuOpen||!hud_compact()||(e.modifierFlags&NSEventModifierFlagCommand))return NO;
 BOOL navigation=e.keyCode==53||e.keyCode==48||e.keyCode==36||e.keyCode==49||(e.keyCode>=123&&e.keyCode<=126);
 if(!navigation)return NO;if(!down){runtime_input_key_synthetic(e.keyCode,0);return YES;}
 TOTKShortcutHelp *panel=(TOTKShortcutHelp *)shortcutHelp;if(!panel)return NO;
 if(panel.quickChoices){TOTKQuickChoices *choices=(TOTKQuickChoices *)panel.quickChoices;   // the open dropdown takes the keys
  if(e.keyCode==125||e.keyCode==126)[choices highlight:choices.highlighted+(e.keyCode==125?1:-1)];
  else if(e.keyCode==36||e.keyCode==49)[panel quickChoose:choices.options[(NSUInteger)choices.highlighted]];
  else if(e.keyCode==53||e.keyCode==48)[panel quickCloseChoices];
  return YES;}
 if(e.keyCode==53){[panel toggleCollapsed:nil];return YES;}
 if(e.keyCode==48){NSInteger next=(panel.quickTab+((e.modifierFlags&NSEventModifierFlagShift)?2:1))%3;
  for(NSButton *tab in panel.quickTabs.subviews)if(tab.tag==next)[panel quickTabAction:tab];return YES;}
 NSArray<NSNumber *> *order=[panel quickOrder];NSUInteger i=[order indexOfObject:@(panel.quickFocused)];if(i==NSNotFound)i=0;
 if(e.keyCode==125||e.keyCode==126){i=(i+order.count+(e.keyCode==125?1:-1))%order.count;NSInteger n=order[i].integerValue;
  if(n==QUICK_HINT){[panel focusQuickHint];[panel.quickBody scrollRectToVisible:panel.quickHint.frame];}
  else{NSButton *row=panel.quickRows[n];[panel focusQuickRow:row];[panel.quickBody scrollRectToVisible:row.frame];}}
 else if(panel.quickFocused==QUICK_HINT){if(e.keyCode==36||e.keyCode==49)[panel quickHint:nil];}
 else if((e.keyCode==36||e.keyCode==49)&&((TOTKQuickRow *)panel.quickRows[panel.quickFocused]).dropdown){TOTKQuickRow *row=(id)panel.quickRows[panel.quickFocused];if(row.enabled)[panel quickOpenChoices:row];}
 else{TOTKQuickRow *row=(id)panel.quickRows[panel.quickFocused];row.direction=e.keyCode==123?-1:1;if(row.enabled)[panel quickAction:row];row.direction=1;}
 return YES;
}
