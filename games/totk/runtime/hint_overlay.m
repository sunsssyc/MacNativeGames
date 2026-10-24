/* Key 8 asks for progressively more explicit hints. The child panel takes keyboard focus only for composing a question.
   Python owns the read-only game-data tools and model backends; IPC is atomic JSON in the user data folder. */
#import "hint_overlay.h"
#include "game_version.h"
#include <unistd.h>
#import <AVFoundation/AVFoundation.h>
#import <Speech/Speech.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
extern void runtime_assistant_pause(int on) __attribute__((weak_import));
static BOOL hintExpanded, hintVoiceFinishing, hintListening, hintHistoryExpanded;
static NSButton *hintHistoryButton;
static NSString *hintLatest;
static NSPanel *hintDock;
static NSTextField *hintBubble;
static NSView *hintBubbleSurface;
static NSButton *hintAvatar;
static NSButton *hintMic,*hintRead,*hintVoiceCancel;
static NSImageView *hintPortrait;
static NSMutableArray<NSString *> *hintHistory;
static void hintDockLayout(void);
static void hintDragBegin(NSEvent *event);
static void hintDragMove(NSEvent *event);
static void hintDragEnd(NSEvent *event);
static void hintVoiceBegin(void);
static void hintVoiceEnd(BOOL cancel);
static void hintOpen(void);
// hint_voice.inc: pages of an answer and 朗读
static NSString *hintPageText(NSString *answer);
static BOOL hintPagesRemain(void);
static BOOL hintPageNext(void);
static BOOL hintReadOn(void);
static BOOL hintReadSet(BOOL on);
static void hintReadAnswer(void);
static void hintReadStop(void);
static void hintReadFollow(NSString *requestID);
static void hintReadPanelClosed(void);
static NSString *hintReadID;
static void hintShowSetup(NSString *title);
static void hintVoicePoll(void);
static void hintVoiceWrite(NSDictionary *value);
static void hintRecordEnd(BOOL save);
static BOOL hintRecording;
static NSButton *hintVoiceSetup;
static NSUInteger hintPage;
static NSArray<NSString *> *hintPages;
static NSString *hintPagedAnswer;
// hint_scene.inc: the frame the panel opened on, and 指给我看's marks on it
static void hintPause(void);
static void hintResume(void);
static BOOL hintTestMode(void);   // hint_test.inc: a test session drives the panel through the command channel
static void hintMarksShow(NSArray *marks);
static void hintMarksHide(void);
static NSButton *hintPointButton;
static BOOL hintSceneReady, hintPointNext, hintPanelLeft;
/* While the model works: what it is doing (the service's "stage") and the answer written so far ("partial"), typed out at
   a reading pace by hintReveal: the model hands its words over in one burst seconds before the run ends. */
static NSString *hintStage, *hintPartial;
static NSUInteger hintRevealed;
static NSTimer *hintRevealTimer;

static NSDictionary *hintRuntimeState(void);
static void hintRuntimeStop(void);
static BOOL hintRuntimeActive(void);
/* 「允许操作」: armed for the next typed question when assistant.json allow_actions is true; granted to the request in
   flight, which may press at most hintActionLimit buttons (hint_runtime_tools.inc). Esc, closing and the answer end it. */
static NSButton *hintActionsButton;
static BOOL hintActionsArmed, hintActionsGranted;
static NSUInteger hintActionCount;
static const NSUInteger hintActionLimit=6;
static NSPanel *hintPanel;
static NSTextField *hintText, *hintTitle, *hintDisclosure;
static NSButton *hintEnable, *hintBack, *hintSend;
static NSTextField *hintQuestion;
static NSString *hintPendingQuestion, *hintLastQuestion;
static BOOL hintWelcome;
static NSScrollView *hintScroll;
static NSProgressIndicator *hintProgress;
/* The service's own budget for all backends (assistant.json total_timeout_seconds, sent as "limit") plus a margin for
   writing the answer; the default covers a service that has not answered yet. */
static NSTimeInterval hintRequestLimit=160;
static NSWindow *hintGame;
static NSTask *hintService;
static NSTimer *hintTimer;
static NSString *hintFolder, *hintID, *hintSession;
static NSInteger hintTier;
static BOOL hintWorking, hintDone;
static NSDate *hintStarted;

static NSString *hintPath(NSString *name) { return [hintFolder stringByAppendingPathComponent:name]; }
static NSDictionary *hintJSON(NSString *path) {
 NSData *data=[NSData dataWithContentsOfFile:path];
 id value=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
 return [value isKindOfClass:NSDictionary.class]?value:nil;
}
static NSColor *hintInk(void){return [NSColor colorWithCalibratedRed:0.99 green:0.975 blue:0.85 alpha:1];}
static NSColor *hintAccent(void){return [NSColor colorWithCalibratedRed:0.88 green:0.40 blue:0.015 alpha:1];}
static NSColor *hintSurface(void){return [NSColor colorWithCalibratedRed:0.055 green:0.06 blue:0.045 alpha:1];}
static BOOL hintActionsAllowed(void){return [hintJSON(hintPath(@"assistant.json"))[@"allow_actions"] boolValue];}
static void hintActionsEnd(void){hintActionsGranted=NO;hintRuntimeStop();}
// The same inset and divider geometry frame every step of the assistant flow.
@interface TOTKHintSurface:NSView
@end
@implementation TOTKHintSurface
-(void)drawRect:(NSRect)dirty{
 (void)dirty;[hintSurface() setFill];NSRectFill(self.bounds);
 CGFloat w=NSWidth(self.bounds),h=NSHeight(self.bounds);
 [[hintInk() colorWithAlphaComponent:0.32] setStroke];
 for(NSNumber *position in @[@(h-62)]){
  CGFloat y=position.doubleValue;NSBezierPath *rule=[NSBezierPath bezierPath];rule.lineWidth=0.7;
  [rule moveToPoint:NSMakePoint(20,y)];[rule lineToPoint:NSMakePoint(w/2-9,y)];
  [rule moveToPoint:NSMakePoint(w/2+9,y)];[rule lineToPoint:NSMakePoint(w-20,y)];
  [rule moveToPoint:NSMakePoint(w/2,y+4)];[rule lineToPoint:NSMakePoint(w/2+4,y)];
  [rule lineToPoint:NSMakePoint(w/2,y-4)];[rule lineToPoint:NSMakePoint(w/2-4,y)];[rule closePath];[rule stroke];
 }
}
@end
// A compact speech bubble shares the game's olive/ivory palette and points at Riju.
@interface TOTKHintAvatar:NSButton
@end
@implementation TOTKHintAvatar
-(BOOL)acceptsFirstMouse:(NSEvent *)event{(void)event;return YES;}
-(void)mouseDown:(NSEvent *)event{hintDragBegin(event);}
-(void)mouseDragged:(NSEvent *)event{hintDragMove(event);}
-(void)mouseUp:(NSEvent *)event{hintDragEnd(event);}
@end
@interface TOTKHintBubble:NSView
@end
@implementation TOTKHintBubble
-(BOOL)acceptsFirstMouse:(NSEvent *)event{(void)event;return YES;}
-(void)mouseDown:(NSEvent *)event{hintDragBegin(event);}
-(void)mouseDragged:(NSEvent *)event{hintDragMove(event);}
-(void)mouseUp:(NSEvent *)event{hintDragEnd(event);}
-(void)drawRect:(NSRect)dirty{
 (void)dirty;NSRect body=NSMakeRect(1,1,NSWidth(self.bounds)-9,NSHeight(self.bounds)-2);
 NSColor *fill=[hintSurface() colorWithAlphaComponent:0.96];
 NSColor *edge=[hintInk() colorWithAlphaComponent:0.32];
 NSBezierPath *shape=[NSBezierPath bezierPathWithRoundedRect:body xRadius:10 yRadius:10];
 [fill setFill];[shape fill];[edge setStroke];shape.lineWidth=0.7;[shape stroke];
 CGFloat x=NSMaxX(body),y=NSMidY(body);
 NSBezierPath *tail=[NSBezierPath bezierPath];[tail moveToPoint:NSMakePoint(x-1,y+6)];
 [tail lineToPoint:NSMakePoint(x+6,y)];[tail lineToPoint:NSMakePoint(x-1,y-6)];[tail closePath];[fill setFill];[tail fill];
 NSBezierPath *outline=[NSBezierPath bezierPath];[outline moveToPoint:NSMakePoint(x,y+6)];[outline lineToPoint:NSMakePoint(x+6,y)];[outline lineToPoint:NSMakePoint(x,y-6)];[edge setStroke];outline.lineWidth=0.7;[outline stroke];
}
@end
@interface TOTKHintInputCell:NSTextFieldCell
@end
@implementation TOTKHintInputCell
-(NSRect)drawingRectForBounds:(NSRect)rect{
 NSRect r=[super drawingRectForBounds:rect];r=NSInsetRect(r,10,0);
 CGFloat height=ceil(self.font.ascender-self.font.descender)+2;
 r.origin.y+=(NSHeight(r)-height)/2;r.size.height=height;return r;
}
-(void)editWithFrame:(NSRect)rect inView:(NSView *)view editor:(NSText *)editor delegate:(id)delegate event:(NSEvent *)event{
 [super editWithFrame:[self drawingRectForBounds:rect] inView:view editor:editor delegate:delegate event:event];
}
-(void)selectWithFrame:(NSRect)rect inView:(NSView *)view editor:(NSText *)editor delegate:(id)delegate start:(NSInteger)start length:(NSInteger)length{
 [super selectWithFrame:[self drawingRectForBounds:rect] inView:view editor:editor delegate:delegate start:start length:length];
}
@end
@interface TOTKHintInput:NSTextField
@end
@implementation TOTKHintInput
-(void)drawRect:(NSRect)dirty{
 [super drawRect:dirty];
 BOOL focused=self.currentEditor!=nil;
 [[hintInk() colorWithAlphaComponent:focused?0.9:self.enabled?0.35:0.15] setStroke];
 NSBezierPath *border=[NSBezierPath bezierPathWithRect:NSInsetRect(self.bounds,1,1)];border.lineWidth=focused?1.5:0.7;[border stroke];
}
-(BOOL)becomeFirstResponder{BOOL result=[super becomeFirstResponder];self.needsDisplay=YES;return result;}
-(BOOL)resignFirstResponder{BOOL result=[super resignFirstResponder];self.needsDisplay=YES;return result;}
@end
static NSFont *hintFont(CGFloat size){return [NSFont fontWithName:@"PingFangSC-Regular" size:size]?:[NSFont systemFontOfSize:size];}
@interface TOTKHintButton:NSButton
@property BOOL primary;
@property BOOL quiet;
@end
@implementation TOTKHintButton
-(BOOL)acceptsFirstResponder{return NO;}
-(void)drawRect:(NSRect)dirty{
 (void)dirty;NSRect r=NSInsetRect(self.bounds,1,1);
 NSColor *fill=self.primary&&self.enabled?hintAccent():[NSColor colorWithWhite:0 alpha:0.3];
 if(!self.quiet){[fill setFill];[[NSBezierPath bezierPathWithRoundedRect:r xRadius:2 yRadius:2] fill];}
 [[hintInk() colorWithAlphaComponent:self.highlighted?1:0.4] setStroke];
 NSBezierPath *border=[NSBezierPath bezierPathWithRoundedRect:r xRadius:2 yRadius:2];border.lineWidth=self.highlighted?2:0.7;if(!self.quiet||self.highlighted)[border stroke];
 NSDictionary *a=@{NSFontAttributeName:hintFont(self.quiet?12:14),NSForegroundColorAttributeName:[hintInk() colorWithAlphaComponent:self.enabled?1:0.38]};
 NSSize size=[self.title sizeWithAttributes:a];[self.title drawAtPoint:NSMakePoint((NSWidth(r)-size.width)/2,(NSHeight(self.bounds)-size.height)/2) withAttributes:a];
}
@end
@interface TOTKHintPanel:NSPanel
@end
@implementation TOTKHintPanel
-(BOOL)canBecomeKeyWindow{return YES;}
-(void)keyDown:(NSEvent *)event{if(!totk_hint_key(event,YES))[super keyDown:event];}
-(void)keyUp:(NSEvent *)event{if(!totk_hint_key(event,NO))[super keyUp:event];}
@end
@interface TOTKHintActions:NSObject<NSTextFieldDelegate>
-(void)enable:(id)sender;
-(void)close:(id)sender;
-(void)request:(id)sender;
-(void)send:(id)sender;
-(void)open:(id)sender;
-(void)voice:(id)sender;
-(void)read:(id)sender;
-(void)history:(id)sender;
-(void)cancelVoice:(id)sender;
-(void)actions:(id)sender;
-(void)point:(id)sender;
@end
static TOTKHintActions *hintActions;
static void hintLayout(CGFloat height){
 (void)height;
 CGFloat w=MIN(380,NSWidth(hintGame.contentView.bounds)-40),bodyWidth=w-40;
 hintText.font=hintFont(14);
 NSRect measured=[hintText.stringValue boundingRectWithSize:NSMakeSize(bodyWidth,CGFLOAT_MAX) options:NSStringDrawingUsesLineFragmentOrigin|NSStringDrawingUsesFontLeading attributes:@{NSFontAttributeName:hintText.font}];
 CGFloat bodyHeight=MAX(52,ceil(NSHeight(measured))+12);
 CGFloat h=MIN(MAX(248,bodyHeight+224),MIN(420,NSHeight(hintGame.contentView.bounds)-40));
 if(hintWelcome)h=330;
 NSRect f=[hintGame convertRectToScreen:hintGame.contentView.bounds];
 CGFloat bottom=MIN(MAX(40,NSHeight(f)*0.18),MAX(20,NSHeight(f)-h-20));
 // The panel sits on the right, or on the left while 指给我看 marks would be under it (hint_scene.inc).
 [hintPanel setFrame:NSMakeRect(hintPanelLeft?NSMinX(f)+24:NSMaxX(f)-w-24,NSMinY(f)+bottom,w,h) display:NO];
 hintTitle.frame=NSMakeRect(64,h-47,w-148,26);hintTitle.font=hintFont(18);hintTitle.alignment=NSTextAlignmentLeft;
 hintPortrait.frame=NSMakeRect(20,h-56,36,46);
 hintBack.title=hintWorking?@"取消":@"收起";hintBack.toolTip=@"收起对话 · Esc";
 hintBack.frame=NSMakeRect(w-72,h-46,52,28);
 hintMic.frame=NSMakeRect(w-128,62,48,34);hintMic.title=hintListening?@"停止":@"语音";
 hintRead.frame=NSMakeRect(w-72,104,52,28);
 BOOL reading=hintReadOn();hintRead.title=reading?@"✓ 朗读":@"朗读";hintRead.toolTip=reading?@"朗读已开 · 点击关闭":@"朗读回复（默认关闭）";
 ((TOTKHintButton *)hintRead).quiet=!reading;((TOTKHintButton *)hintRead).primary=reading;hintRead.needsDisplay=YES;
 hintVoiceCancel.frame=NSMakeRect(20,104,92,28);hintVoiceCancel.hidden=!(hintListening||hintVoiceFinishing);
 hintMic.hidden=hintWelcome;hintRead.hidden=hintWelcome||hintListening||hintVoiceFinishing;
 hintPanel.contentView.needsDisplay=YES;
 CGFloat bodyBottom=hintWelcome?164:146;
 hintScroll.frame=NSMakeRect(20,bodyBottom,bodyWidth,MAX(40,h-bodyBottom-78));
 hintText.frame=NSMakeRect(0,0,bodyWidth,MAX(hintScroll.contentSize.height,bodyHeight));
 hintVoiceSetup.hidden=hintVoiceSetup.hidden||hintWelcome;hintVoiceSetup.frame=NSMakeRect(w-108,19,88,28);
 hintDisclosure.frame=NSMakeRect(20,16,w-40-(hintVoiceSetup.hidden?0:96),hintWelcome?82:34);
 hintQuestion.hidden=hintSend.hidden=hintWelcome;
 hintQuestion.frame=NSMakeRect(20,62,w-156,34);hintQuestion.font=hintFont(13);
 hintSend.frame=NSMakeRect(w-72,62,52,34);
 hintEnable.frame=NSMakeRect(20,hintWelcome?112:104,hintWelcome?158:92,28);
 hintPointButton.frame=NSMakeRect(116,104,70,28);
 hintPointButton.hidden=hintWelcome||hintWorking||!hintSceneReady||!hintExpanded;
 hintPointButton.toolTip=@"把这个问题和暂停的画面一起发给露珠，她会在画面上圈出来（只对这个问题有效）";
 hintHistoryButton.hidden=hintWelcome||hintHistory.count==0;
 hintHistoryButton.title=hintHistoryExpanded?@"最新回复":@"历史";
 hintHistoryButton.frame=NSMakeRect(w-124,104,48,28);
 hintActionsButton.frame=NSMakeRect(w-190,104,64,28);
 hintActionsButton.hidden=hintWelcome||hintWorking||!hintActionsAllowed();
 hintActionsButton.title=hintActionsArmed?@"✓ 允许操作":@"允许操作";
 ((TOTKHintButton *)hintActionsButton).quiet=!hintActionsArmed;((TOTKHintButton *)hintActionsButton).primary=hintActionsArmed;
 hintActionsButton.needsDisplay=YES;
 hintProgress.frame=NSMakeRect(w-98,h-42,16,16);
 if(hintExpanded){[hintGame addChildWindow:hintPanel ordered:NSWindowAbove];[hintPanel orderFront:nil];}
 hintDockLayout();
}
static void hintShow(NSString *text) {
 hintWelcome=NO;hintMic.enabled=!hintWorking;hintRead.enabled=YES;hintQuestion.enabled=!hintWorking;hintSend.enabled=!hintWorking&&!hintListening&&!hintVoiceFinishing&&[[hintQuestion.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet] length]>0;((TOTKHintButton *)hintEnable).primary=NO;
 hintTitle.hidden=hintDisclosure.hidden=hintBack.hidden=NO;
 hintTitle.stringValue=@"露珠";
 hintLatest=text;hintHistoryExpanded=NO;
 BOOL streaming=hintWorking&&hintRevealed>0;
 // An answer shows three lines at a time, also while it is being typed out.
 NSString *shown=streaming?hintPageText([hintPartial substringToIndex:hintRevealed]):hintDone&&!hintWorking?hintPageText(text):text;
 hintText.stringValue=hintWorking&&!streaming?@"让我想想…":shown;
 hintBubble.stringValue=hintWorking&&!streaming?@"让我想想…\n点击头像展开 · Esc 取消":shown;
 hintEnable.hidden=hintWorking;hintEnable.enabled=YES;hintEnable.action=@selector(request:);
 hintEnable.title=hintDone?(hintTier<3?@"更具体一点":@"新的求助"):@"重新求助";
 hintBack.title=hintWorking?@"取消求助  Esc":@"收起  Esc";
 hintDisclosure.stringValue=hintWorking&&hintRuntimeActive()?[NSString stringWithFormat:@"露珠正在操作游戏（第 %lu 次，最多 %lu 次）· Esc 中止",(unsigned long)hintActionCount,(unsigned long)hintActionLimit]
  :hintPagesRemain()?[NSString stringWithFormat:@"第 %lu/%lu 段 · 回车或点击文字继续",(unsigned long)hintPage+1,(unsigned long)hintPages.count]
  :hintWorking?[NSString stringWithFormat:@"%@… · 已等待 %.0f 秒（上限 %.0f 秒）",hintStage.length?hintStage:@"正在思考",MAX(0,-hintStarted.timeIntervalSinceNow),hintRequestLimit]
  :hintDone?@"可输入问题继续追问":@"本次求助已结束，不会自动重试。";
 hintProgress.hidden=!hintWorking;if(hintWorking)[hintProgress startAnimation:nil];else [hintProgress stopAnimation:nil];
 CGFloat bodyWidth=MIN(440,NSWidth(hintGame.frame)-40)-64;
 NSRect body=[hintText.stringValue boundingRectWithSize:NSMakeSize(bodyWidth,CGFLOAT_MAX) options:NSStringDrawingUsesLineFragmentOrigin|NSStringDrawingUsesFontLeading attributes:@{NSFontAttributeName:hintFont(16)}];
 hintLayout(hintDone?MIN(550,MAX(440,ceil(NSHeight(body))+316)):440);
 if(hintDone){[hintScroll.contentView scrollToPoint:NSMakePoint(0,hintText.isFlipped?0:MAX(0,NSHeight(hintText.frame)-hintScroll.contentSize.height))];[hintScroll reflectScrolledClipView:hintScroll.contentView];}

}
#include "hint_scene.inc"
static void hintShowWelcome(void){
 hintExpanded=YES;hintPause();hintWelcome=YES;((TOTKHintButton *)hintEnable).primary=YES;
 hintTitle.hidden=hintDisclosure.hidden=hintEnable.hidden=hintBack.hidden=NO;hintProgress.hidden=YES;[hintProgress stopAnimation:nil];
 hintTitle.stringValue=@"露珠";
 hintText.stringValue=@"遇到难题时，先给一点线索。\n需要时，再逐步查看更具体的提示。";
 hintDisclosure.stringValue=@"求助时，模型按需查看暂停的画面、读取存档与游戏文本，交给 Claude Code、Codex 或 Vertex AI。不会修改存档；代操作默认关闭。";
 hintEnable.title=@"启用助手";hintEnable.action=@selector(enable:);hintEnable.enabled=YES;hintBack.title=@"收起  Esc";
 hintLayout(440);
}
static void hintShowReady(void){
 hintExpanded=YES;hintPause();
 hintWorking=hintDone=NO;hintSession=nil;hintPendingQuestion=nil;hintLastQuestion=nil;hintQuestion.stringValue=@"";[hintHistory removeAllObjects];
 hintShow(@"卡在哪里了？告诉我，或先看看进度提示。");
 hintTitle.stringValue=@"露珠";hintEnable.title=@"根据进度给提示";
 hintDisclosure.stringValue=@"游戏已暂停 · 收起后继续";
 [hintPanel makeKeyWindow];[hintPanel makeFirstResponder:hintQuestion];
}
// Requests carry user intent only; the assistant chooses observations through tools.
static BOOL hintWrite(NSDictionary *value) {
 NSData *data=[NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
 return data&&[data writeToFile:hintPath(@"hint-request.json") options:NSDataWritingAtomic error:nil];
}

@implementation TOTKHintActions
-(void)open:(id)sender{(void)sender;hintOpen();}
-(void)history:(id)sender{(void)sender;hintHistoryExpanded=!hintHistoryExpanded;hintText.stringValue=hintHistoryExpanded?[hintHistory componentsJoinedByString:@"\n\n"]:hintDone?hintPageText(hintLatest):hintLatest;hintLayout(0);[hintScroll.contentView scrollToPoint:NSZeroPoint];[hintScroll reflectScrolledClipView:hintScroll.contentView];}
-(void)voice:(id)sender{(void)sender;if(hintListening)hintVoiceEnd(NO);else hintVoiceBegin();}
-(void)cancelVoice:(id)sender{(void)sender;hintVoiceEnd(YES);}
// 指给我看: the typed question (or a plain "what now") with the frame on screen, for marks drawn on it (hint_scene.inc).
-(void)point:(id)sender{
 (void)sender;if(hintWorking||!hintSceneReady||hintListening||hintVoiceFinishing)return;
 NSString *q=[hintQuestion.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
 hintPendingQuestion=q.length?q:@"指给我看：画面里我下一步该做什么？";hintPointNext=YES;[self request:nil];
}
-(void)actions:(id)sender{(void)sender;hintActionsArmed=!hintActionsArmed&&hintActionsAllowed();hintLayout(0);
 hintDisclosure.stringValue=hintActionsArmed?@"下一个问题允许露珠操作游戏（最多 6 次短按）· Esc 随时中止":@"可输入问题继续追问";}
// 朗读 is a switch, remembered in assistant.json: on reads the answer on screen and every answer after it (hint_voice.inc).
-(void)read:(id)sender{
 (void)sender;BOOL on=!hintReadOn();
 if(!hintReadSet(on)){hintDisclosure.stringValue=@"暂时无法保存朗读设置。";return;}
 if(on)hintReadAnswer();else{hintReadStop();hintShowSetup(nil);}
 hintLayout(0);
}
-(void)controlTextDidChange:(NSNotification *)note{
 (void)note;hintSend.enabled=!hintWorking&&!hintListening&&!hintVoiceFinishing&&[[hintQuestion.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet] length]>0;
}
-(void)send:(id)sender{
 (void)sender;if(hintWorking||hintListening||hintVoiceFinishing)return;
 NSString *q=[hintQuestion.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
 if(!q.length){hintPageNext();return;}   // Return with nothing typed: the next part of the answer
 if(q.length>1000){hintDisclosure.stringValue=@"问题请控制在 1000 字以内。";return;}
 hintPendingQuestion=q;[self request:nil];
}
-(BOOL)control:(NSControl *)control textView:(NSTextView *)view doCommandBySelector:(SEL)command{
 (void)control;(void)view;
 if(command==@selector(cancelOperation:)){if(hintRecording)hintRecordEnd(NO);else if(hintListening||hintVoiceFinishing)hintVoiceEnd(YES);else [self close:nil];return YES;}
 return NO;
}
-(void)close:(id)sender{
 (void)sender;hintVoiceEnd(YES);hintRecordEnd(NO);if(hintWorking)hintReadStop();else hintReadPanelClosed();hintActionsEnd();hintActionsArmed=NO;if(hintWorking)hintWrite(@{@"id":hintID,@"session":hintSession,@"cancel":@YES});
 hintWorking=NO;hintExpanded=NO;hintResume();[hintPanel orderOut:nil];hintDockLayout();
}
-(void)request:(id)sender{
 (void)sender;if(!hintDone&&!hintPendingQuestion.length&&hintLastQuestion.length)hintPendingQuestion=hintLastQuestion;
 NSEventModifierFlags flags=!hintPendingQuestion.length&&hintDone&&hintTier>=3?NSEventModifierFlagShift:0;
 NSEvent *e=[NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:flags timestamp:0 windowNumber:hintGame.windowNumber context:nil characters:@"8" charactersIgnoringModifiers:@"8" isARepeat:NO keyCode:28];
 totk_hint_key(e,YES);
}
-(void)enable:(id)sender{
 (void)sender;NSString *path=hintPath(@"assistant.json");NSDictionary *existing=hintJSON(path);
 if([NSFileManager.defaultManager fileExistsAtPath:path]&&!existing){
  hintDisclosure.stringValue=@"设置文件暂时无法读取。请检查后重试，已有设置未被修改。";return;
 }
 NSMutableDictionary *config=existing?[existing mutableCopy]:[NSMutableDictionary new];config[@"enabled"]=@YES;
 NSError *error=nil;NSData *data=[NSJSONSerialization dataWithJSONObject:config options:NSJSONWritingPrettyPrinted error:&error];
 BOOL ok=data&&[NSFileManager.defaultManager createDirectoryAtPath:hintFolder withIntermediateDirectories:YES attributes:nil error:&error]&&[data writeToFile:path options:NSDataWritingAtomic error:&error];
 if(!ok){hintDisclosure.stringValue=@"暂时无法保存设置，请稍后重试。";return;}
 // Continue to composition without starting a model request.
 hintShowReady();
}
@end
static BOOL hintStart(void) {
 if(hintService.running)return YES;
 NSString *script=[NSFileManager.defaultManager.currentDirectoryPath stringByAppendingPathComponent:@"tools/hint_assistant/run.py"];
 const char *override=getenv("TOTK_HINT_PYTHON");
 NSString *python=override&&*override?@(override):nil;
 if(!python){for(NSString *p in @[@"/opt/homebrew/bin/python3.14",@"/usr/local/bin/python3.14",@"/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14"]){
  if([NSFileManager.defaultManager isExecutableFileAtPath:p]){python=p;break;}
 }}
 if(!python||![NSFileManager.defaultManager fileExistsAtPath:script]){
  hintShow(@"助手运行组件尚未准备好。\n请安装 Python 3.14 后再试。");return NO;
 }
 [NSFileManager.defaultManager removeItemAtPath:hintPath(@"hint-request.json") error:nil];
 hintService=[NSTask new];hintService.executableURL=[NSURL fileURLWithPath:python];
 hintService.arguments=@[@"-E",@"-s",script,@"serve",@"--parent-pid",[@(getpid()) stringValue],@"--folder",hintFolder,@"--accept-pending",
                        @"--romfs",@"extracted/" TOTK_GAME_DIR "/romfs"];
 NSError *error=nil;
 if(![hintService launchAndReturnError:&error]){hintText.toolTip=error.localizedDescription;hintShow(@"助手暂时无法启动。\n请稍后再试。");return NO;}
 return YES;
}

#include "hint_runtime_tools.inc"
static void hintRevealStop(void){[hintRevealTimer invalidate];hintRevealTimer=nil;}
static void hintReveal(void){   // a few more characters of the answer being written, about 90 a second
 if(!hintWorking||hintRevealed>=hintPartial.length){hintRevealStop();return;}
 NSUInteger next=hintRevealed;
 for(int i=0;i<3&&next<hintPartial.length;i++)next=NSMaxRange([hintPartial rangeOfComposedCharacterSequenceAtIndex:next]);
 hintRevealed=next;hintShow(@"");
}
static void hintStream(NSDictionary *answer){   // the service's progress while working
 NSString *stage=answer[@"stage"],*partial=answer[@"partial"];
 hintStage=[stage isKindOfClass:NSString.class]?stage:nil;
 if(![partial isKindOfClass:NSString.class])partial=@"";
 if(![partial hasPrefix:[hintPartial?:@"" substringToIndex:MIN(hintRevealed,hintPartial.length)]])hintRevealed=0;   // a new attempt
 hintPartial=partial;
 if(hintRevealed<hintPartial.length&&!hintRevealTimer)
  hintRevealTimer=[NSTimer scheduledTimerWithTimeInterval:1.0/30 repeats:YES block:^(NSTimer *timer){(void)timer;hintReveal();}];
}
static void hintPoll(void) {
 hintRuntimePoll();
 hintVoicePoll();
 hintDockLayout();
 if(!hintWorking)return;
 // One deadline covers all backend attempts, so the UI can never wait through an unbounded fallback chain.
 if(-hintStarted.timeIntervalSinceNow>=hintRequestLimit){
  hintWrite(@{@"id":hintID,@"session":hintSession,@"cancel":@YES});hintWorking=hintDone=NO;hintActionsEnd();
  hintShow(@"这次等待得有些久，已停止求助。\n稍后可以再试一次。");return;
 }
 NSDictionary *answer=hintJSON(hintPath(@"hint-response.json"));
 if([answer[@"id"] isEqual:hintID]&&[answer[@"session"] isEqual:hintSession]){
  NSString *status=answer[@"status"],*text=answer[@"text"];
  if([answer[@"limit"] isKindOfClass:NSNumber.class])hintRequestLimit=MIN(900,MAX(30,[answer[@"limit"] doubleValue]+10));
  if([status isEqual:@"working"])hintStream(answer);
  else{
   hintWorking=NO;hintDone=[status isEqual:@"done"];hintActionsEnd();hintRevealStop();
   hintText.toolTip=hintDone?nil:text;
   if(hintDone&&[text isKindOfClass:NSString.class]){[hintHistory addObject:[@"露珠\n" stringByAppendingString:text]];while(hintHistory.count>24)[hintHistory removeObjectAtIndex:0];}
   hintShow(hintDone&&[text isKindOfClass:NSString.class]?text:@"这次没能取得提示。\n你可以稍后重新求助。");
   if(hintDone)hintMarksShow(answer[@"marks"]);
   if(hintDone&&hintReadOn()&&!hintReadID)hintReadAnswer();   // switched on while it worked
   if(!hintDone&&[hintReadID isEqual:hintID])hintReadStop();
   return;
  }
 }
 if(!hintService.running){
  hintWorking=hintDone=NO;hintActionsEnd();hintShow(@"助手已停止。\n你可以重新求助。");return;
 }
 hintShow(@"");
}
#include "hint_companion.inc"
#include "hint_voice.inc"

void totk_hint_install(NSWindow *window) {
#if defined(GAME_BOTW)
 (void)window;return;
#endif
 hintGame=window;hintHistory=[NSMutableArray new];
 hintFolder=[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/MacNativeGames/TOTK"];
 hintPanel=[[TOTKHintPanel alloc] initWithContentRect:NSMakeRect(0,0,470,270) styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
 hintPanel.backgroundColor=hintSurface();hintPanel.hasShadow=YES;
 hintPanel.contentView=[[TOTKHintSurface alloc] initWithFrame:hintPanel.contentView.bounds];
 hintPanel.becomesKeyOnlyIfNeeded=NO;
 hintPanel.appearance=[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
 hintPanel.collectionBehavior=NSWindowCollectionBehaviorFullScreenAuxiliary;
 hintText=[NSTextField wrappingLabelWithString:@""];hintText.frame=NSMakeRect(20,18,430,234);
 hintText.font=[NSFont systemFontOfSize:18];hintText.textColor=NSColor.whiteColor;
 hintScroll=[NSScrollView new];hintScroll.drawsBackground=NO;hintScroll.hasVerticalScroller=YES;hintScroll.autohidesScrollers=YES;hintScroll.scrollerStyle=NSScrollerStyleOverlay;hintScroll.documentView=hintText;
 [hintPanel.contentView addSubview:hintScroll];hintText.textColor=hintInk();
 hintActions=[TOTKHintActions new];
 hintTitle=[NSTextField labelWithString:@"卡关助手"];hintTitle.font=hintFont(24);hintTitle.textColor=hintInk();hintTitle.alignment=NSTextAlignmentCenter;
 hintDisclosure=[NSTextField wrappingLabelWithString:@"求助时，模型按需查看暂停的画面、读取存档与游戏文本，交给 Claude Code、Codex 或 Vertex AI。\n不会修改存档；代操作默认关闭。启用后按 8 求助。"];
 hintDisclosure.font=hintFont(12);hintDisclosure.textColor=[hintInk() colorWithAlphaComponent:0.78];
 hintEnable=[TOTKHintButton buttonWithTitle:@"启用助手" target:hintActions action:@selector(enable:)];((TOTKHintButton *)hintEnable).primary=YES;
 hintBack=[TOTKHintButton buttonWithTitle:@"返回  Esc" target:hintActions action:@selector(close:)];
 for(NSView *v in @[hintTitle,hintDisclosure,hintEnable,hintBack])[hintPanel.contentView addSubview:v];
 hintQuestion=[TOTKHintInput new];hintQuestion.cell=[[TOTKHintInputCell alloc] initTextCell:@""];hintQuestion.editable=YES;hintQuestion.selectable=YES;hintQuestion.drawsBackground=YES;hintQuestion.bordered=NO;hintQuestion.focusRingType=NSFocusRingTypeNone;hintQuestion.font=hintFont(15);hintQuestion.textColor=hintInk();hintQuestion.backgroundColor=[NSColor colorWithCalibratedRed:0.085 green:0.09 blue:0.065 alpha:1];hintQuestion.placeholderAttributedString=[[NSAttributedString alloc] initWithString:@"输入问题，或继续追问…" attributes:@{NSForegroundColorAttributeName:[hintInk() colorWithAlphaComponent:0.65],NSFontAttributeName:hintFont(15)}];hintQuestion.target=hintActions;hintQuestion.action=@selector(send:);hintQuestion.delegate=hintActions;
 hintSend=[TOTKHintButton buttonWithTitle:@"发送" target:hintActions action:@selector(send:)];((TOTKHintButton *)hintSend).primary=YES;
 [hintPanel.contentView addSubview:hintQuestion];[hintPanel.contentView addSubview:hintSend];
 hintPortrait=[[NSImageView alloc] init];hintPortrait.image=[[NSImage alloc] initWithContentsOfFile:@"runtime/assets/riju-companion.png"];hintPortrait.imageScaling=NSImageScaleProportionallyUpOrDown;[hintPanel.contentView addSubview:hintPortrait];
 hintMic=[TOTKHintButton buttonWithTitle:@"语音提问" target:hintActions action:@selector(voice:)];hintRead=[TOTKHintButton buttonWithTitle:@"朗读" target:hintActions action:@selector(read:)];[hintPanel.contentView addSubview:hintMic];[hintPanel.contentView addSubview:hintRead];
 hintHistoryButton=[TOTKHintButton buttonWithTitle:@"历史" target:hintActions action:@selector(history:)];[hintPanel.contentView addSubview:hintHistoryButton];
 hintPointButton=[TOTKHintButton buttonWithTitle:@"指给我看" target:hintActions action:@selector(point:)];((TOTKHintButton *)hintPointButton).quiet=YES;
 hintPointButton.hidden=YES;[hintPanel.contentView addSubview:hintPointButton];
 hintActionsButton=[TOTKHintButton buttonWithTitle:@"允许操作" target:hintActions action:@selector(actions:)];hintActionsButton.hidden=YES;
 hintActionsButton.toolTip=@"只对下一个问题有效：露珠可以替你按几次键（assistant.json 的 allow_actions 打开时才显示）";[hintPanel.contentView addSubview:hintActionsButton];
 for(TOTKHintButton *button in @[hintBack,hintRead,hintEnable,hintHistoryButton])button.quiet=YES;
 hintVoiceCancel=[TOTKHintButton buttonWithTitle:@"取消录音" target:hintActions action:@selector(cancelVoice:)];((TOTKHintButton *)hintVoiceCancel).quiet=YES;hintVoiceCancel.hidden=YES;[hintPanel.contentView addSubview:hintVoiceCancel];
 hintVoiceInstall();
 hintDock=[[NSPanel alloc] initWithContentRect:NSMakeRect(0,0,360,120) styleMask:NSWindowStyleMaskBorderless|NSWindowStyleMaskNonactivatingPanel backing:NSBackingStoreBuffered defer:NO];hintDock.backgroundColor=NSColor.clearColor;hintDock.opaque=NO;hintDock.hasShadow=NO;
 // The companion belongs to the game window, including background test windows.
 hintDock.hidesOnDeactivate=NO;hintDock.collectionBehavior=NSWindowCollectionBehaviorFullScreenAuxiliary;
 NSImage *mini=[[NSImage alloc] initWithContentsOfFile:@"runtime/assets/riju-mini-fullbody.png"];
 NSButton *avatar=[TOTKHintAvatar buttonWithImage:mini?:hintPortrait.image?:[NSImage imageNamed:NSImageNameUser] target:hintActions action:@selector(open:)];hintAvatar=avatar;avatar.bordered=NO;avatar.imageScaling=NSImageScaleProportionallyUpOrDown;avatar.frame=NSMakeRect(284,0,76,96);avatar.toolTip=@"露珠 · 点击聊天，拖动调整位置";[avatar setAccessibilityLabel:@"露珠：点击打开对话，拖动调整位置"];[hintDock.contentView addSubview:avatar];
 hintBubble=[NSTextField wrappingLabelWithString:@"点击露珠，语音提问\n点击露珠，输入问题"];hintBubble.maximumNumberOfLines=6;hintBubble.lineBreakMode=NSLineBreakByTruncatingTail;hintBubble.cell.truncatesLastVisibleLine=YES;hintBubble.font=hintFont(13);hintBubble.textColor=hintInk();hintBubble.drawsBackground=NO;hintBubbleSurface=[TOTKHintBubble new];[hintBubbleSurface addSubview:hintBubble];[hintDock.contentView addSubview:hintBubbleSurface];
 [hintGame addChildWindow:hintDock ordered:NSWindowAbove];hintDockLayout();
 hintProgress=[NSProgressIndicator new];hintProgress.appearance=[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];hintProgress.style=NSProgressIndicatorStyleSpinning;hintProgress.controlSize=NSControlSizeSmall;hintProgress.indeterminate=YES;[hintPanel.contentView addSubview:hintProgress];
 hintTitle.hidden=hintDisclosure.hidden=hintEnable.hidden=hintBack.hidden=hintProgress.hidden=YES;
 [NSNotificationCenter.defaultCenter addObserverForName:NSApplicationWillResignActiveNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note){(void)note;hintVoiceEnd(YES);}];
 hintTimer=[NSTimer scheduledTimerWithTimeInterval:0.25 repeats:YES block:^(NSTimer *timer){(void)timer;hintPoll();}];
}
BOOL totk_hint_key(NSEvent *event, BOOL down) {
 if(!hintGame)return NO;
 BOOL escape=event.keyCode==53&&(hintPanel.visible||hintListening||hintWorking||hintRecording);
 // Return (key code 36) shows the next part of an answer while the panel is open; otherwise it stays the game's.
 if(event.keyCode==36&&hintPanel.visible&&hintPagesRemain()){if(down&&!event.isARepeat)hintPageNext();return YES;}
 if(event.keyCode!=28&&!escape)return NO; // macOS virtual key 28: 8
 if(!down||event.isARepeat)return YES;
 if(escape){
  if(hintRecording){hintRecordEnd(NO);return YES;}
  if(hintListening||hintVoiceFinishing){hintVoiceEnd(YES);return YES;}
  if(hintWorking)hintReadStop();else hintReadPanelClosed();   // a request being cancelled is not read on
  hintActionsEnd();hintActionsArmed=NO;
  if(hintWorking)hintWrite(@{@"id":hintID,@"session":hintSession,@"cancel":@YES});
  hintWorking=NO;hintExpanded=NO;hintResume();[hintPanel orderOut:nil];hintDockLayout();return YES;
 }
 NSDictionary *config=hintJSON(hintPath(@"assistant.json"));
 if(![config[@"enabled"] boolValue]){
  hintShowWelcome();return YES;
 }
 if(hintWorking||hintListening||hintVoiceFinishing||hintRecording)return YES;
 if(!hintPanel.visible&&!hintPendingQuestion.length){hintOpen();return YES;}
 if(![NSFileManager.defaultManager createDirectoryAtPath:hintFolder withIntermediateDirectories:YES attributes:nil error:nil]){
  hintShow(@"无法创建卡关助手的数据目录。");return YES;
 }
 if(!hintStart())return YES;
 BOOL fresh=!hintSession||(event.modifierFlags&NSEventModifierFlagShift);
 if(fresh){[hintHistory removeAllObjects];hintSession=NSUUID.UUID.UUIDString;hintTier=[config[@"tier_default"] integerValue];if(hintTier<1||hintTier>3)hintTier=1;}
 else if(hintDone&&!hintPendingQuestion.length&&hintTier<3)hintTier++;
 hintID=NSUUID.UUID.UUIDString;
 NSMutableDictionary *request=[@{@"id":hintID,@"session":hintSession,@"tier":@(hintTier),@"time":@(NSDate.date.timeIntervalSince1970)} mutableCopy];
 if(hintPendingQuestion.length)request[@"question"]=hintPendingQuestion;
 BOOL pointing=hintPointNext&&hintSceneReady&&hintPendingQuestion.length;hintPointNext=NO;
 if(pointing)request[@"scene"]=@YES;   // 指给我看: the frame on screen goes with this question only
 hintActionsGranted=!pointing&&hintPendingQuestion.length&&hintActionsArmed&&[config[@"allow_actions"] boolValue];hintActionsArmed=NO;hintActionCount=0;
 if(hintActionsGranted)request[@"actions"]=@YES;
 hintMarksHide();
 BOOL reading=hintReadOn();
 if(reading)request[@"read"]=@YES;   // read aloud line by line as it is written; the voice gets ready meanwhile
 if(!hintWrite(request)){
  hintShow(@"无法写入求助请求。");return YES;
 }
 hintReadStop();hintPagedAnswer=nil;hintPages=nil;hintPage=0;hintPartial=hintStage=nil;hintRevealed=0;hintRevealStop();
 if(hintPendingQuestion.length)[hintHistory addObject:[@"你\n" stringByAppendingString:hintPendingQuestion]];
 hintLastQuestion=hintPendingQuestion;hintPendingQuestion=nil;hintQuestion.stringValue=@"";[hintPanel makeFirstResponder:nil];[hintGame makeKeyWindow];
 hintDone=NO;hintWorking=YES;hintStarted=NSDate.date;if(reading)hintReadFollow(hintID);
 hintShow(@"让我想想……\n\nEsc 取消");return YES;
}
#include "hint_test.inc"
