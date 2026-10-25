/* Companion presentation and click-to-record dictation. All state transitions run on AppKit's main queue. */
static AVAudioEngine *hintAudio;
static SFSpeechRecognizer *hintRecognizer;
static SFSpeechAudioBufferRecognitionRequest *hintRecognition;
static SFSpeechRecognitionTask *hintSpeechTask;
static NSUInteger hintVoiceGeneration;
static NSString *hintVoiceDraft;
static NSString *hintTranscript;
/* The microphone while listening, for the level bars and the log (2026-10-24: a spoken question came back empty with
   nothing to tell whether any sound had arrived): the last buffer's and the loudest loudness in dBFS, written by the
   audio tap; the partial results, the time listening began and the recognizer's error, on the main queue. */
#include <stdatomic.h>
static _Atomic float hintVoiceLevel=-120,hintVoicePeak=-120;
static NSUInteger hintVoiceResults;
static NSDate *hintVoiceStarted;
static NSString *hintVoiceError;
static NSView *hintVoiceMeter;
static void hintVoiceMeasure(AVAudioPCMBuffer *buffer){   // the audio tap's thread
 const float *samples=buffer.floatChannelData?buffer.floatChannelData[0]:NULL;AVAudioFrameCount n=buffer.frameLength;
 if(!samples||!n)return;
 double sum=0;for(AVAudioFrameCount i=0;i<n;i++)sum+=(double)samples[i]*samples[i];
 float db=(float)(10*log10(sum/n+1e-12));atomic_store(&hintVoiceLevel,db);
 if(db>atomic_load(&hintVoicePeak))atomic_store(&hintVoicePeak,db);
}
/* 正在听: seven bars left of the 正在听 line that follow the voice (flat when nothing comes in), taller in the middle and
   rippling, so the player sees the microphone hear them. */
@interface TOTKHintLevel:NSView
@property(strong) NSTimer *timer;
@end
@implementation TOTKHintLevel{CGFloat bars[7];}
-(void)drawRect:(NSRect)dirty{
 (void)dirty;CGFloat gap=3,bw=(NSWidth(self.bounds)-gap*6)/7,h=NSHeight(self.bounds);
 [hintAccent() setFill];
 for(int i=0;i<7;i++){CGFloat bh=MAX(bw,bars[i]*h);[[NSBezierPath bezierPathWithRoundedRect:NSMakeRect(i*(bw+gap),(h-bh)/2,bw,bh) xRadius:bw/2 yRadius:bw/2] fill];}
}
-(void)tick{
 CGFloat loud=MAX(0,MIN(1,(atomic_load(&hintVoiceLevel)+55)/40));   // -55 dBFS: a quiet room; -15: a raised voice
 double t=NSDate.timeIntervalSinceReferenceDate;
 for(int i=0;i<7;i++){
  CGFloat target=0.15+0.85*loud*(1-fabs(i-3.0)/4.5)*(0.6+0.4*sin(t*11+i*1.4));
  bars[i]+=(target-bars[i])*(target>bars[i]?0.55:0.2);   // up fast, down slowly
 }
 self.needsDisplay=YES;
}
-(void)run:(BOOL)on{
 if(on&&!self.timer){__weak TOTKHintLevel *weak=self;self.timer=[NSTimer timerWithTimeInterval:1/30.0 repeats:YES block:^(NSTimer *t){(void)t;[weak tick];}];
  [NSRunLoop.mainRunLoop addTimer:self.timer forMode:NSRunLoopCommonModes];}
 if(!on){[self.timer invalidate];self.timer=nil;for(int i=0;i<7;i++)bars[i]=0;}
}
@end
/* hintLayout and the voice controls: the bars while listening, the 正在听 line moved right of them. */
static void hintVoiceMeterLayout(void){
 if(!hintPanel)return;
 if(!hintVoiceMeter){hintVoiceMeter=[TOTKHintLevel new];[hintPanel.contentView addSubview:hintVoiceMeter];}
 BOOL on=hintListening;hintVoiceMeter.hidden=!on;[(TOTKHintLevel *)hintVoiceMeter run:on];
 hintVoiceMeter.frame=NSMakeRect(20,26,52,18);
 NSRect d=hintDisclosure.frame;CGFloat right=NSMaxX(d),left=on?82:20;
 if(NSMinX(d)!=left){d.origin.x=left;d.size.width=MAX(40,right-left);hintDisclosure.frame=d;}
}
// Position is relative to the available travel area, so it survives window resizing.
// Keep this UI preference separate from the assistant service's configuration.
static BOOL hintDockPositionLoaded, hintDockPositionSet, hintDragging;
static NSPoint hintDockPosition, hintDragPointer, hintDragOrigin;
static NSRect hintDockTravel(NSSize size){
 NSRect r=[hintGame convertRectToScreen:hintGame.contentView.bounds];
 return NSMakeRect(NSMinX(r)+12,NSMinY(r)+12,MAX(0,NSWidth(r)-size.width-24),MAX(0,NSHeight(r)-size.height-24));
}
static void hintDockLoadPosition(void){
 if(hintDockPositionLoaded)return;
 hintDockPositionLoaded=YES;
 NSDictionary *p=hintJSON(hintPath(@"companion-position.json"));
 if([p[@"x"] isKindOfClass:NSNumber.class]&&[p[@"y"] isKindOfClass:NSNumber.class]){
  double x=[p[@"x"] doubleValue],y=[p[@"y"] doubleValue];
  if(isfinite(x)&&isfinite(y)){hintDockPosition=NSMakePoint(MAX(0,MIN(1,x)),MAX(0,MIN(1,y)));hintDockPositionSet=YES;}
 }
}
static void hintDragBegin(NSEvent *event){
 hintDragging=NO;hintDragPointer=[event.window convertPointToScreen:event.locationInWindow];hintDragOrigin=hintDock.frame.origin;
}
static void hintDragMove(NSEvent *event){
 NSPoint pointer=[event.window convertPointToScreen:event.locationInWindow];
 CGFloat dx=pointer.x-hintDragPointer.x,dy=pointer.y-hintDragPointer.y;
 if(!hintDragging&&hypot(dx,dy)<4)return;
 hintDragging=YES;
 NSRect travel=hintDockTravel(hintDock.frame.size);
 CGFloat x=MAX(NSMinX(travel),MIN(NSMaxX(travel),hintDragOrigin.x+dx));
 CGFloat y=MAX(NSMinY(travel),MIN(NSMaxY(travel),hintDragOrigin.y+dy));
 hintDockPosition=NSMakePoint(travel.size.width?(x-travel.origin.x)/travel.size.width:0,
                             travel.size.height?(y-travel.origin.y)/travel.size.height:0);
 hintDockPositionSet=YES;[hintDock setFrameOrigin:NSMakePoint(x,y)];
}
static void hintDragEnd(NSEvent *event){
 (void)event;
 if(!hintDragging){hintOpen();return;}
 hintDragging=NO;
 NSData *data=[NSJSONSerialization dataWithJSONObject:@{@"x":@(hintDockPosition.x),@"y":@(hintDockPosition.y)} options:0 error:nil];
 [data writeToFile:hintPath(@"companion-position.json") options:NSDataWritingAtomic error:nil];
}
static void hintDockLayout(void){
 if(!hintDock)return;
 hintDockLoadPosition();
 NSRect r=[hintGame convertRectToScreen:hintGame.contentView.bounds];
 NSFont *font=hintFont(13);
 NSMutableParagraphStyle *paragraph=[NSMutableParagraphStyle new];paragraph.lineSpacing=3;paragraph.lineBreakMode=NSLineBreakByWordWrapping;
 NSDictionary *style=@{NSFontAttributeName:font,NSForegroundColorAttributeName:hintInk(),NSParagraphStyleAttributeName:paragraph};
 /* Up to six lines, the answer's own limit (prompts.py MAX_LINES), measured by the cell that draws them: the fixed 80 pt
    held three lines of PingFang 13 with the 3 pt spacing and dropped the fourth without a mark (user, 2026-10-24), and a
    string measurement comes out shorter than the cell's own lines. Longer text ends in "…" on the last line (the cell
    truncates it); the whole answer is in the panel. */
 CGFloat textWidth=MIN(260,MAX(144,[hintBubble.stringValue sizeWithAttributes:style].width));
 NSString *text=hintBubble.stringValue;
 hintBubble.attributedStringValue=[[NSAttributedString alloc] initWithString:@"一\n一\n一\n一\n一\n一" attributes:style];
 CGFloat sixLines=ceil([hintBubble.cell cellSizeForBounds:NSMakeRect(0,0,textWidth,CGFLOAT_MAX)].height);
 hintBubble.attributedStringValue=[[NSAttributedString alloc] initWithString:text attributes:style];
 CGFloat need=ceil([hintBubble.cell cellSizeForBounds:NSMakeRect(0,0,textWidth,CGFLOAT_MAX)].height);
 CGFloat textHeight=MIN(sixLines,MAX(36,need));
 CGFloat bubbleWidth=textWidth+36,bubbleHeight=textHeight+24;
 CGFloat height=MAX(144,bubbleHeight+8),width=bubbleWidth+102;
 hintBubbleSurface.frame=NSMakeRect(0,(height-bubbleHeight)/2,bubbleWidth,bubbleHeight);
 hintBubble.frame=NSMakeRect(14,12,textWidth,textHeight);
 hintAvatar.frame=NSMakeRect(width-96,(height-144)/2,96,144);
 NSRect frame=NSMakeRect(NSMaxX(r)-width-24,NSMinY(r)+MAX(156,NSHeight(r)*0.29),width,height);
 NSRect travel=hintDockTravel(frame.size);
 if(hintDockPositionSet)frame.origin=NSMakePoint(travel.origin.x+travel.size.width*hintDockPosition.x,travel.origin.y+travel.size.height*hintDockPosition.y);
 frame.origin.x=MAX(NSMinX(travel),MIN(NSMaxX(travel),frame.origin.x));
 frame.origin.y=MAX(NSMinY(travel),MIN(NSMaxY(travel),frame.origin.y));
 if(!NSEqualRects(frame,hintDock.frame))[hintDock setFrame:frame display:YES];
 if(hintExpanded){if(hintDock.visible)[hintDock orderOut:nil];}
 else if(hintGame.visible&&!hintDock.visible){[hintGame addChildWindow:hintDock ordered:NSWindowAbove];[hintDock orderFront:nil];}
 [(TOTKHintAvatar *)hintAvatar syncMotion];
 [hintPortrait syncMotion];
}
static void hintOpen(void){
 hintExpanded=YES;
 if(![hintJSON(hintPath(@"assistant.json"))[@"enabled"] boolValue]){hintShowWelcome();return;}
 if(hintSession||hintWorking||hintDone){hintLayout(540);hintMarksNoteOnOpen();[hintPanel makeKeyWindow];[hintPanel makeFirstResponder:hintQuestion];}
 else hintShowReady();
}
static void hintVoiceNotice(NSString *message){
 hintBubble.stringValue=message;hintDisclosure.stringValue=message;hintDockLayout();
}
static void hintVoiceStopAudio(void){
 if(hintAudio){[hintAudio stop];[hintAudio.inputNode removeTapOnBus:0];hintAudio=nil;}
}
static void hintVoiceControls(BOOL active){
 hintVoiceMeterLayout();
 hintQuestion.enabled=!active;hintMic.enabled=!hintVoiceFinishing;
 hintMic.title=hintListening?@"停止":@"语音";
 hintSend.enabled=!active&&hintQuestion.stringValue.length>0;
 hintEnable.hidden=active||hintWorking;hintHistoryButton.hidden=active||!hintHistoryCount();
 hintRead.hidden=active;hintVoiceCancel.hidden=!active;
 hintVoiceCancel.frame=NSMakeRect(20,104,92,28);
}
static void hintVoiceSubmit(NSUInteger generation){
 if(generation!=hintVoiceGeneration||!hintVoiceFinishing)return;
 NSString *text=[hintTranscript stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
 float peak=atomic_load(&hintVoicePeak);
 fprintf(stderr,"[hint-voice] stopped after %.1f s: loudest %.0f dBFS, %lu partial results, %lu characters%s%s\n",hintVoiceStarted?-hintVoiceStarted.timeIntervalSinceNow:0,
         peak,(unsigned long)hintVoiceResults,(unsigned long)text.length,hintVoiceError?"; recognizer: ":"",hintVoiceError?hintVoiceError.UTF8String:"");
 hintVoiceStopAudio();hintVoiceFinishing=NO;hintListening=NO;hintVoiceGeneration++;
 [hintSpeechTask cancel];hintSpeechTask=nil;hintRecognition=nil;
 hintQuestion.stringValue=text.length?(hintVoiceDraft.length?[hintVoiceDraft stringByAppendingFormat:@" %@",text]:text):hintVoiceDraft?:@"";
 hintVoiceControls(NO);
 hintVoiceNotice(text.length?@"录音已停止 · 检查文字后点击发送":peak<-50?@"没有收到声音 · 请检查系统设置里的声音输入（麦克风）":@"听到了声音，但没认出文字 · 可以再说一次或输入文字");
 [hintPanel makeFirstResponder:hintQuestion];
}
static void hintVoiceEnd(BOOL cancel){
 if(!hintListening&&!hintVoiceFinishing)return;
 hintVoiceStopAudio();hintListening=NO;
 if(cancel){hintVoiceGeneration++;hintVoiceFinishing=NO;[hintSpeechTask cancel];hintSpeechTask=nil;hintRecognition=nil;hintQuestion.stringValue=hintVoiceDraft?:@"";hintVoiceControls(NO);hintVoiceNotice(@"已取消录音 · 原有文字已保留");return;}
 hintVoiceFinishing=YES;hintVoiceControls(YES);[hintRecognition endAudio];hintVoiceNotice(@"麦克风已关闭 · 正在整理文字…");
 NSUInteger generation=hintVoiceGeneration;
 dispatch_after(dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC),dispatch_get_main_queue(),^{hintVoiceSubmit(generation);});
}
static void hintVoiceBegin(void){
 if(hintListening||hintVoiceFinishing||hintWorking)return;
 if(![hintJSON(hintPath(@"assistant.json"))[@"enabled"] boolValue]){hintOpen();return;}
 SFSpeechRecognizerAuthorizationStatus speech=[SFSpeechRecognizer authorizationStatus];
 /* The first time, macOS asks for speech recognition and then for the microphone; one click goes through both and
    then listens (it once took a click per question and another to start, 2026-10-24), unless the panel was closed. */
 if(speech==SFSpeechRecognizerAuthorizationStatusNotDetermined){
  hintVoiceNotice(@"首次使用需要语音识别和麦克风授权，同意后就开始听");
  [SFSpeechRecognizer requestAuthorization:^(SFSpeechRecognizerAuthorizationStatus status){dispatch_async(dispatch_get_main_queue(),^{
   if(status!=SFSpeechRecognizerAuthorizationStatusAuthorized){hintVoiceNotice(@"语音识别未授权 · 仍可点击露珠打字");return;}
   if(hintExpanded)hintVoiceBegin();});}];return;   // on to the microphone
 }
 if(speech!=SFSpeechRecognizerAuthorizationStatusAuthorized){hintVoiceNotice(@"语音识别未授权 · 可在系统设置中开启，或直接打字");return;}
 AVAuthorizationStatus mic=[AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio];
 if(mic==AVAuthorizationStatusNotDetermined){
  hintVoiceNotice(@"需要麦克风授权，同意后就开始听");
  [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL allowed){dispatch_async(dispatch_get_main_queue(),^{
   if(!allowed){hintVoiceNotice(@"麦克风未授权 · 仍可点击露珠打字");return;}
   if(hintExpanded)hintVoiceBegin();});}];return;   // allowed: listen now
 }
 if(mic!=AVAuthorizationStatusAuthorized){hintVoiceNotice(@"麦克风未授权 · 可在系统设置中开启，或直接打字");return;}
 hintRecognizer=[[SFSpeechRecognizer alloc] initWithLocale:[NSLocale localeWithLocaleIdentifier:@"zh-CN"]];
 if(!hintRecognizer.available||!hintRecognizer.supportsOnDeviceRecognition){hintVoiceNotice(@"本机中文语音识别暂不可用 · 请先输入文字");return;}
 hintRecognition=[SFSpeechAudioBufferRecognitionRequest new];hintRecognition.requiresOnDeviceRecognition=YES;hintRecognition.shouldReportPartialResults=YES;
 hintAudio=[AVAudioEngine new];AVAudioInputNode *input=hintAudio.inputNode;AVAudioFormat *format=[input outputFormatForBus:0];
 if(format.channelCount==0||format.sampleRate<=0){hintAudio=nil;hintVoiceNotice(@"未找到可用麦克风 · 请先输入文字");return;}
 SFSpeechAudioBufferRecognitionRequest *request=hintRecognition;
 /* The recognizer gets one channel: a MacBook Pro's microphone array comes in as three. */
 AVAudioFormat *mono=format.channelCount>1&&format.commonFormat==AVAudioPCMFormatFloat32&&!format.interleaved?
  [[AVAudioFormat alloc] initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:format.sampleRate channels:1 interleaved:NO]:nil;
 fprintf(stderr,"[hint-voice] listening: %s, %.0f Hz, %u channel(s)%s\n",([AVCaptureDevice defaultDeviceWithMediaType:AVMediaTypeAudio].localizedName?:@"no default input").UTF8String,
         format.sampleRate,(unsigned)format.channelCount,mono?", the first one to the recognizer":"");
 atomic_store(&hintVoiceLevel,-120);atomic_store(&hintVoicePeak,-120);hintVoiceResults=0;hintVoiceError=nil;hintVoiceStarted=NSDate.date;
 [input installTapOnBus:0 bufferSize:1024 format:format block:^(AVAudioPCMBuffer *buffer,AVAudioTime *when){(void)when;
  AVAudioPCMBuffer *one=buffer;
  if(mono&&buffer.floatChannelData&&(one=[[AVAudioPCMBuffer alloc] initWithPCMFormat:mono frameCapacity:buffer.frameLength])){
   one.frameLength=buffer.frameLength;memcpy(one.floatChannelData[0],buffer.floatChannelData[0],buffer.frameLength*sizeof(float));}
  else one=buffer;
  hintVoiceMeasure(one);[request appendAudioPCMBuffer:one];}];
 NSError *error=nil;[hintAudio prepare];if(![hintAudio startAndReturnError:&error]){hintVoiceStopAudio();hintVoiceNotice(@"麦克风暂时无法使用 · 请先输入文字");return;}
 hintVoiceDraft=[hintQuestion.stringValue copy];hintListening=YES;hintTranscript=@"";hintVoiceGeneration++;NSUInteger generation=hintVoiceGeneration;hintVoiceControls(YES);[hintPanel makeFirstResponder:nil];
 hintVoiceNotice(@"正在听… 点击停止结束 · Esc 取消");
 hintSpeechTask=[hintRecognizer recognitionTaskWithRequest:request resultHandler:^(SFSpeechRecognitionResult *result,NSError *failure){dispatch_async(dispatch_get_main_queue(),^{
  if(generation!=hintVoiceGeneration)return;
  if(result)hintVoiceResults++;
  if(failure&&!hintVoiceError){hintVoiceError=[NSString stringWithFormat:@"%@ %ld: %@",failure.domain,(long)failure.code,failure.localizedDescription];
   fprintf(stderr,"[hint-voice] recognizer: %s\n",hintVoiceError.UTF8String);}
  if(result){hintTranscript=result.bestTranscription.formattedString;if(hintListening){hintQuestion.stringValue=hintVoiceDraft.length?[hintVoiceDraft stringByAppendingFormat:@" %@",hintTranscript]:hintTranscript;}}
  if(result.isFinal){hintVoiceStopAudio();hintListening=NO;hintVoiceFinishing=YES;hintVoiceSubmit(generation);}
  else if(failure){hintVoiceStopAudio();if(hintVoiceFinishing)hintVoiceSubmit(generation);else{hintVoiceEnd(YES);hintVoiceNotice(@"语音识别中断 · 请重试或输入文字");}}
 });}];
 dispatch_after(dispatch_time(DISPATCH_TIME_NOW,60*NSEC_PER_SEC),dispatch_get_main_queue(),^{if(generation==hintVoiceGeneration&&hintListening)hintVoiceEnd(NO);});
}
