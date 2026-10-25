#include "../games/totk/runtime/hint_overlay.m"
#include <assert.h>
int runtime_live_player(float xyz[3]){xyz[0]=1;xyz[1]=2;xyz[2]=3;return 1;}
// One actor ahead of the player, as world_survey.c reads them in the game, plus one that can appear on demand (the
// runtime_state "changes" test).
static RuntimePlayerActivity fakeActivity;
int runtime_live_activity(RuntimePlayerActivity *out){*out=fakeActivity;return out->valid;}
static int sceneExtra;
int runtime_live_scene(RuntimeScene *out,float radius){
 (void)radius;memset(out,0,sizeof *out);out->rot[0]=out->rot[4]=1;out->rot[8]=-1;out->table=2135;out->has_camera=1;out->camera[2]=8;
 out->cam_rot[0]=out->cam_rot[4]=1;out->cam_rot[8]=-1;out->has_cam_rot=1;
 out->actors=1;strcpy(out->near[0].name,"SpObj_LiftGeneratorWing_A_01");out->near[0].xyz[2]=-50;out->near[0].distance=53.1f;
 if(sceneExtra){out->actors=2;strcpy(out->near[1].name,"SpObj_Switch_A_01");out->near[1].xyz[0]=2;out->near[1].distance=2.2f;}
 return 1;
}
// The camera and player rotations for the guide arrow's fast path: level, facing north (-Z). cameraConvention picks
// which way the game stores the camera's forward axis; the arrow must come out the same either way.
static int cameraConvention,cameraMissing;   // cameraMissing: only Link's rotation, the arrow's fallback
int runtime_live_facing(float player_rot[9],float camera_rot[9],float camera_pos[3]){
 player_rot[0]=player_rot[4]=1;player_rot[8]=-1;
 camera_rot[0]=camera_rot[4]=1;camera_rot[8]=cameraConvention?1:-1;   // the sign is settled by the position below
 camera_pos[0]=1;camera_pos[1]=2;camera_pos[2]=3+8;   // eight metres behind Link (south of him), so it looks north
 return cameraMissing?1:3;
}
static unsigned syntheticDowns;static int syntheticHeld=-1;
void runtime_input_key_synthetic(unsigned code,int down){if(down){syntheticDowns++;syntheticHeld=(int)code;}else if(syntheticHeld==(int)code)syntheticHeld=-1;}
static NSDictionary *runtimeSequence(NSString *id,NSArray *steps){
 NSDictionary *q=@{@"id":id,@"op":@"sequence",@"steps":steps,@"time":@(NSDate.date.timeIntervalSince1970)};
 [[NSJSONSerialization dataWithJSONObject:q options:0 error:nil] writeToFile:hintPath(@"runtime-request.json") atomically:YES];
 [NSFileManager.defaultManager removeItemAtPath:hintPath(@"runtime-response.json") error:nil];hintRuntimePoll();
 // The steps run on dispatch_after: pump the main queue until the reply for this id is written.
 NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:3];
 while(deadline.timeIntervalSinceNow>0){
  NSDictionary *r=hintJSON(hintPath(@"runtime-response.json"));
  if([r[@"id"] isEqual:id])return r;
  [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
 }
 return @{};
}
static NSDictionary *runtimeStateReply(NSString *id){
 NSDictionary *q=@{@"id":id,@"op":@"state",@"time":@(NSDate.date.timeIntervalSince1970)};
 [[NSJSONSerialization dataWithJSONObject:q options:0 error:nil] writeToFile:hintPath(@"runtime-request.json") atomically:YES];
 [NSFileManager.defaultManager removeItemAtPath:hintPath(@"runtime-response.json") error:nil];hintRuntimePoll();
 NSDictionary *r=hintJSON(hintPath(@"runtime-response.json"));return [r[@"id"] isEqual:id]?r:@{};
}
static NSString *runtimePress(NSString *id){
 NSDictionary *q=@{@"id":id,@"op":@"press",@"button":@"a",@"duration_ms":@50,@"time":@(NSDate.date.timeIntervalSince1970)};
 [[NSJSONSerialization dataWithJSONObject:q options:0 error:nil] writeToFile:hintPath(@"runtime-request.json") atomically:YES];
 [NSFileManager.defaultManager removeItemAtPath:hintPath(@"runtime-response.json") error:nil];hintRuntimePoll();
 NSDictionary *r=hintJSON(hintPath(@"runtime-response.json"));return [r[@"id"] isEqual:id]?r[@"error"]:nil;   // nil: still held
}
static int assistantPaused;
void runtime_assistant_pause(int on){assistantPaused=on;}
@interface FakeHintTask:NSTask
@end
// The system voice without sound: what it was asked to say.
@interface FakeSpeaker:AVSpeechSynthesizer
@property NSMutableArray<NSString *> *said;
@property BOOL talking;
@end
// The game's window shot, written at once (a covered window writes none).
static BOOL shotFails;
void dm_gfx_window_shot(const char *path){
 if(shotFails)return;
 NSBitmapImageRep *rep=[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:160 pixelsHigh:90 bitsPerSample:8 samplesPerPixel:4
  hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:0 bitsPerPixel:0];
 [[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:@(path) atomically:YES];
}
static NSString *silentWav(NSString *folder){   // 0.1 s of 24 kHz 16-bit mono silence
 NSMutableData *d=[NSMutableData data];uint32_t n=4800,riff=36+n,fmt=16,rate=24000,bytes=48000;uint16_t pcm=1,ch=1,align=2,bits=16;
 [d appendBytes:"RIFF" length:4];[d appendBytes:&riff length:4];[d appendBytes:"WAVEfmt " length:8];[d appendBytes:&fmt length:4];
 [d appendBytes:&pcm length:2];[d appendBytes:&ch length:2];[d appendBytes:&rate length:4];[d appendBytes:&bytes length:4];
 [d appendBytes:&align length:2];[d appendBytes:&bits length:2];[d appendBytes:"data" length:4];[d appendBytes:&n length:4];[d increaseLengthBy:n];
 NSString *file=[folder stringByAppendingPathComponent:@"silence.wav"];[d writeToFile:file atomically:YES];return file;
}
@implementation FakeSpeaker
-(BOOL)isSpeaking{return self.talking;}
-(void)speakUtterance:(AVSpeechUtterance *)utterance{if(!self.said)self.said=[NSMutableArray new];[self.said addObject:utterance.speechString];self.talking=YES;}
-(BOOL)stopSpeakingAtBoundary:(AVSpeechBoundary)boundary{(void)boundary;self.talking=NO;return YES;}
@end
@implementation FakeHintTask
-(BOOL)isRunning{return YES;}
@end
int main(int argc,const char **argv){@autoreleasepool{
 (void)argc;[NSApplication sharedApplication];
 NSWindow *w=[[NSWindow alloc] initWithContentRect:NSMakeRect(200,200,1000,680) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
 w.title=@"卡关助手界面验证";w.backgroundColor=[NSColor colorWithCalibratedRed:0.07 green:0.085 blue:0.06 alpha:1];
 totk_hint_install(w);hintFolder=@(argv[1]);
 // Hover and drag feedback preserve the control's fixed hit area; hidden panels stop animation.
 TOTKHintAvatar *pet=(TOTKHintAvatar *)hintAvatar;
 NSEvent *hover=[NSEvent mouseEventWithType:NSEventTypeMouseMoved location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:w.windowNumber context:nil eventNumber:0 clickCount:0 pressure:0];
 NSRect petFrame=pet.frame;[pet mouseEntered:hover];assert(pet.hovered&&pet.greeting>0);
 [pet mouseExited:hover];assert(!pet.hovered&&NSEqualRects(petFrame,pet.frame));
 hintExpanded=YES;[pet syncMotion];assert(!pet.motionTimer);hintExpanded=NO;
 assert(!hintDock.hidesOnDeactivate);assert(hintDock.collectionBehavior&NSWindowCollectionBehaviorFullScreenAuxiliary);
 // A drag moves the companion without opening chat, persists, and stays in bounds after resizing.
 hintExpanded=NO;hintDockPositionLoaded=NO;hintDockPositionSet=NO;hintDockLayout();
 NSPoint origin=hintDock.frame.origin;
 NSEvent *(^mouse)(NSEventType,NSPoint)=^NSEvent *(NSEventType type,NSPoint screen){
  return [NSEvent mouseEventWithType:type location:[w convertPointFromScreen:screen] modifierFlags:0 timestamp:0
    windowNumber:w.windowNumber context:nil eventNumber:0 clickCount:1 pressure:1];
 };
 [hintAvatar mouseDown:mouse(NSEventTypeLeftMouseDown,origin)];
 [hintAvatar mouseDragged:mouse(NSEventTypeLeftMouseDragged,NSMakePoint(origin.x-120,origin.y+70))];
 [hintAvatar mouseUp:mouse(NSEventTypeLeftMouseUp,NSMakePoint(origin.x-120,origin.y+70))];
 assert(!hintExpanded);assert(fabs(hintDock.frame.origin.x-(origin.x-120))<1);
 assert(hintJSON(hintPath(@"companion-position.json"))!=nil);
 NSPoint saved=hintDock.frame.origin;hintDockPositionLoaded=NO;hintDockPositionSet=NO;hintDockLayout();
 assert(NSEqualPoints(saved,hintDock.frame.origin));
 [hintAvatar mouseDown:mouse(NSEventTypeLeftMouseDown,saved)];
 [hintAvatar mouseDragged:mouse(NSEventTypeLeftMouseDragged,NSMakePoint(-10000,10000))];
 [hintAvatar mouseUp:mouse(NSEventTypeLeftMouseUp,NSMakePoint(-10000,10000))];
 [w setContentSize:NSMakeSize(640,480)];hintDockLayout();
 assert(NSContainsRect([w convertRectToScreen:w.contentView.bounds],hintDock.frame));
 [w setContentSize:NSMakeSize(1000,680)];hintDockLayout();
 NSString *path=hintPath(@"assistant.json");
 [@"{\"enabled\":false,\"allow_screenshot\":false,\"custom\":42}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 [hintActions enable:nil];NSDictionary *c=hintJSON(path);assert([c[@"enabled"] boolValue]);assert([c[@"custom"] intValue]==42);assert(![c[@"allow_screenshot"] boolValue]);
 assert(![NSFileManager.defaultManager fileExistsAtPath:hintPath(@"hint-request.json")]);
 assert(!assistantPaused);assert(!hintWelcome);assert(!hintQuestion.hidden);assert(hintQuestion.editable);assert(hintQuestion.stringValue.length==0);
 [@"invalid" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];[hintActions enable:nil];
 assert([[NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:nil] isEqual:@"invalid"]);
 assert([hintDisclosure.stringValue containsString:@"未被修改"]);
 [@"{\"enabled\":true}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 hintService=[FakeHintTask new];hintShowReady();
 assert(NSHeight(hintPanel.frame)<300);assert(NSHeight(hintText.frame)<=hintScroll.contentSize.height);
 assert(!hintWorking);assert(![NSFileManager.defaultManager fileExistsAtPath:hintPath(@"hint-request.json")]);
 hintQuestion.stringValue=@"这个神庙怎么过？";[hintActions send:nil];
 NSDictionary *first=hintJSON(hintPath(@"hint-request.json"));assert([first[@"question"] isEqual:@"这个神庙怎么过？"]);assert([first[@"tier"] intValue]==1);
 hintWorking=NO;hintDone=YES;hintQuestion.stringValue=@"刚才说的入口在哪？";[hintActions send:nil];
 NSDictionary *followup=hintJSON(hintPath(@"hint-request.json"));assert([followup[@"session"] isEqual:first[@"session"]]);assert([followup[@"tier"] intValue]==1);assert([followup[@"question"] isEqual:@"刚才说的入口在哪？"]);
 hintWorking=hintDone=NO;[hintActions request:nil];
 assert([hintJSON(hintPath(@"hint-request.json"))[@"question"] isEqual:@"刚才说的入口在哪？"]);
 hintID=@"deadline-test";hintSession=@"test-session";hintWorking=YES;hintDone=NO;hintStarted=[NSDate dateWithTimeIntervalSinceNow:-(hintRequestLimit+1)];
 hintPoll();assert(!hintWorking);assert([hintJSON(hintPath(@"hint-request.json"))[@"cancel"] boolValue]);
 assert([hintText.stringValue containsString:@"已停止求助"]);assert([hintEnable.title isEqual:@"重新求助"]);
 hintWorking=YES;hintStarted=[NSDate date];[hintActions close:nil];assert(!hintWorking);
 assert(!assistantPaused);
 // While listening, level bars sit left of the 正在听 line and follow the microphone's loudness (hintVoiceMeasure).
 hintListening=YES;hintVoiceControls(YES);
 assert(!hintVoiceMeter.hidden&&((TOTKHintLevel *)hintVoiceMeter).timer&&NSMinX(hintDisclosure.frame)>=NSMaxX(hintVoiceMeter.frame));
 AVAudioPCMBuffer *tone=[[AVAudioPCMBuffer alloc] initWithPCMFormat:[[AVAudioFormat alloc] initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:16000 channels:1 interleaved:NO] frameCapacity:1600];
 tone.frameLength=1600;for(int i=0;i<1600;i++)tone.floatChannelData[0][i]=0.1f*sinf(i*0.2f);
 atomic_store(&hintVoicePeak,-120);hintVoiceMeasure(tone);float toneDb=atomic_load(&hintVoiceLevel);
 assert(toneDb>-24&&toneDb<-22&&atomic_load(&hintVoicePeak)==toneDb);   // a 0.1 sine: -23 dBFS
 hintListening=NO;hintVoiceControls(NO);assert(hintVoiceMeter.hidden&&!((TOTKHintLevel *)hintVoiceMeter).timer&&NSMinX(hintDisclosure.frame)==20);
 // Key 0 asks by voice from the game window or an empty question field; typed text, an input method composing and the
 // game's own text entry keep it as a digit. (hintWorking: taken, but nothing starts in the probe.)
 hintWorking=YES;
 NSEvent *(^zero)(NSWindow *,NSEventModifierFlags)=^NSEvent *(NSWindow *in,NSEventModifierFlags flags){
  return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:flags timestamp:0 windowNumber:in.windowNumber context:nil characters:@"0" charactersIgnoringModifiers:@"0" isARepeat:NO keyCode:29];};
 assert(hintVoiceKey(zero(w,0))&&!hintVoiceKey(zero(w,NSEventModifierFlagCommand)));
 [hintPanel makeFirstResponder:hintQuestion];hintQuestion.stringValue=@"";
 assert(hintVoiceKey(zero(hintPanel,0)));
 [(NSTextView *)hintPanel.firstResponder setString:@"第"];assert(!hintVoiceKey(zero(hintPanel,0)));
 hintQuestion.stringValue=@"";[hintPanel makeFirstResponder:nil];hintWorking=NO;
 // Cancelled voice recognition must never submit a stale transcript.
 NSDictionary *beforeVoice=hintJSON(hintPath(@"hint-request.json"));
 hintListening=YES;hintTranscript=@"不应发送";NSUInteger stale=hintVoiceGeneration;
 hintVoiceEnd(YES);hintVoiceSubmit(stale);
 assert(!hintListening&&!hintVoiceFinishing);assert([beforeVoice isEqual:hintJSON(hintPath(@"hint-request.json"))]);
 // Dictation stops into an editable draft; it must never submit a model request.
 hintVoiceDraft=@"原来的问题";hintTranscript=@"补充描述";hintVoiceFinishing=YES;
 NSUInteger completed=hintVoiceGeneration;hintVoiceSubmit(completed);
 assert([hintQuestion.stringValue isEqual:@"原来的问题 补充描述"]);
 assert(!hintListening&&!hintVoiceFinishing&&hintQuestion.enabled&&hintSend.enabled);
 assert([beforeVoice isEqual:hintJSON(hintPath(@"hint-request.json"))]);
 hintVoiceDraft=@"保留草稿";hintListening=YES;hintQuestion.stringValue=@"未确认的语音";
 hintVoiceEnd(YES);assert([hintQuestion.stringValue isEqual:@"保留草稿"]);
 NSEvent *v=[NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:w.windowNumber context:nil characters:@"v" charactersIgnoringModifiers:@"v" isARepeat:NO keyCode:9];
 assert(!totk_hint_key(v,YES));assert(!totk_hint_key(v,NO));
 // Collapsing and reopening preserves the existing conversation.
 hintSession=@"preserved-session";hintDone=YES;[hintActions close:nil];hintOpen();
 assert([hintSession isEqual:@"preserved-session"]);assert(!assistantPaused);
 [hintActions close:nil];assert(!assistantPaused);
 hintDone=YES;hintHistory=[NSMutableArray arrayWithArray:@[@"你\n入口在哪？",@"露珠\n往北走。"]];hintShow(@"往北走。");
 assert([hintText.stringValue isEqual:@"往北走。"]);[hintActions history:nil];
 assert([hintText.stringValue containsString:@"入口在哪"]);[hintActions history:nil];
 assert([hintText.stringValue isEqual:@"往北走。"]);assert(NSHeight(hintPanel.frame)<=420);
 // The companion bubble shows a whole answer of up to six lines, longer text ending in "…" (2026-10-24: a four-line
 // greeting lost its last line to a fixed 80 pt height).
 hintBubble.stringValue=@"你好，我是《王国之泪》的卡关助手。\n不知道去哪、解不开谜题都可以问我。\n我会按你选的提示档位给提示，尽量不剧透。\n想更具体就点「更具体一点」。";
 hintDockLayout();
 NSSize need=[hintBubble.cell cellSizeForBounds:NSMakeRect(0,0,NSWidth(hintBubble.frame),CGFLOAT_MAX)];   // what the cell draws
 assert(ceil(need.height)<=NSHeight(hintBubble.frame));
 hintBubble.stringValue=[@"" stringByPaddingToLength:400 withString:@"往北走到驿站再找英帕。" startingAtIndex:0];
 hintDockLayout();assert(hintBubble.cell.truncatesLastVisibleLine);assert(NSHeight(hintBubble.frame)>=6*17);
 // runtime_state carries the facing, the camera and the actors nearby.
 NSDictionary *live=hintRuntimeState();
 assert(([live[@"facing"] isEqual:@[@0,@0,@(-1)]]));assert([live[@"actor_table"] intValue]==2135);
 assert([live[@"nearby"][0][@"name"] isEqual:@"SpObj_LiftGeneratorWing_A_01"]);assert([live[@"camera"][2] floatValue]==8);
 // Game inputs: none without 「允许操作」 for the request in flight, at most hintActionLimit per request, Esc releases.
 [@"{\"enabled\":true}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 hintDone=YES;hintWorking=NO;[hintActions actions:nil];assert(!hintActionsArmed);
 hintLayout(0);assert(hintActionsButton.hidden);
 [@"{\"enabled\":true,\"allow_actions\":true}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 hintLayout(0);assert(!hintActionsButton.hidden);
 hintWorking=YES;hintActionsGranted=NO;hintID=@"no-consent";assert([runtimePress(@"p0") isEqual:@"actions_not_allowed"]);assert(syntheticDowns==0);
 hintWorking=NO;hintDone=YES;[hintActions actions:nil];assert(hintActionsArmed);
 hintQuestion.stringValue=@"帮我按一下 A";[hintActions send:nil];
 NSDictionary *acting=hintJSON(hintPath(@"hint-request.json"));assert([acting[@"actions"] boolValue]);assert(hintActionsGranted&&!hintActionsArmed&&hintWorking);
 for(NSUInteger i=0;i<hintActionLimit;i++){assert(runtimePress([NSString stringWithFormat:@"p%lu",(unsigned long)i+1])==nil);assert(hintRuntimeActive());hintRuntimeStop();}
 assert(syntheticDowns==hintActionLimit);assert([runtimePress(@"over") isEqual:@"action_limit"]);
 hintActionCount=0;assert(runtimePress(@"held")==nil);assert(syntheticHeld>=0);
 NSEvent *esc=[NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:w.windowNumber context:nil characters:@"\x1b" charactersIgnoringModifiers:@"\x1b" isARepeat:NO keyCode:53];
 assert(totk_hint_key(esc,YES));assert(syntheticHeld<0&&!hintRuntimeActive()&&!hintActionsGranted&&!hintWorking);
 hintWorking=YES;hintID=@"after-esc";assert([runtimePress(@"p9") isEqual:@"actions_not_allowed"]);hintWorking=NO;
 hintQuestion.stringValue=@"再问一句";hintDone=YES;[hintActions send:nil];assert(![hintJSON(hintPath(@"hint-request.json"))[@"actions"] boolValue]);hintWorking=NO;
 // An answer shows three lines at a time; Return (empty question) and the end of a page being read move on.
 [@"{\"enabled\":true}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 hintOpen();hintWorking=NO;hintDone=YES;hintHistoryExpanded=NO;
 NSString *answer=@"第一行\n第二行\n第三行\n第四行\n第五行";hintShow(answer);
 assert([hintText.stringValue isEqual:@"第一行\n第二行\n第三行  ▼"]);assert([hintBubble.stringValue isEqual:hintText.stringValue]);
 assert([hintDisclosure.stringValue containsString:@"1/2"]);assert(hintPagesRemain());
 hintQuestion.stringValue=@"";[hintActions send:nil];
 assert([hintText.stringValue isEqual:@"第四行\n第五行"]);assert(!hintPagesRemain());assert(!hintPageNext());
 NSEvent *ret=[NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:w.windowNumber context:nil characters:@"\r" charactersIgnoringModifiers:@"\r" isARepeat:NO keyCode:36];
 assert(!totk_hint_key(ret,YES));   // nothing left to show: Return is the game's again
 hintPagedAnswer=nil;hintShow(@"新回答第一行\n二\n三\n四");assert(hintPage==0);   // a new request starts on page oneassert(totk_hint_key(ret,YES));assert(hintPage==1);
 // 朗读 is off by default; switching it on is remembered and reads line by line (here the system voice: no service),
 // turning the page when the voice gets there.
 FakeSpeaker *speaker=[FakeSpeaker new];hintSpeaker=speaker;
 void (^finishLine)(void)=^{[hintActions speechSynthesizer:speaker didFinishSpeechUtterance:[AVSpeechUtterance speechUtteranceWithString:@""]];
  [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];};
 assert(!hintReadOn());hintService=nil;hintPagedAnswer=nil;hintShow(answer);
 [hintActions read:nil];assert(hintReadOn());assert([hintVoiceConfig()[@"enabled"] boolValue]);
 assert(hintReadSystem);assert(([speaker.said isEqual:@[@"第一行"]]));
 finishLine();finishLine();finishLine();
 assert(([speaker.said isEqual:@[@"第一行",@"第二行",@"第三行",@"第四行"]]));assert(hintPage==1);
 [hintActions read:nil];assert(!hintReadOn());assert(!speaker.talking);assert(!hintReadID);
 // With the service: the lines go to it and its files play in order; when it has no voice ("system") the system voice
 // takes over, and in "local" mode the panel offers to record a voice. The system voice reads on after the panel closes;
 // the local clone, which needs the paused game's GPU, stops.
 [@"{\"enabled\":true,\"voice\":{\"enabled\":false,\"engine\":\"local\"}}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 NSString *wav=silentWav(hintFolder);
 void (^voiceReply)(NSDictionary *)=^(NSDictionary *fields){
  [[NSJSONSerialization dataWithJSONObject:fields options:0 error:nil] writeToFile:hintPath(@"hint-voice.json") atomically:YES];hintVoicePoll();};
 hintOpen();hintService=[FakeHintTask new];hintWorking=NO;hintDone=YES;hintPagedAnswer=nil;hintShow(@"甲\n乙");[hintActions read:nil];
 NSDictionary *readRequest=hintJSON(hintPath(@"hint-voice-request.json"));assert(([readRequest[@"lines"] isEqual:@[@"甲",@"乙"]]));
 voiceReply(@{@"id":readRequest[@"id"],@"status":@"working",@"engine":@"google",@"files":@[]});assert(hintReadPlaying<0);
 voiceReply(@{@"id":readRequest[@"id"],@"status":@"working",@"engine":@"google",@"files":@[wav]});
 assert(hintPlayer&&hintReadPlaying==0);
 [hintActions audioPlayerDidFinishPlaying:hintPlayer successfully:YES];[[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
 assert(hintReadLine==1&&hintReadPlaying<0);   // the next line's audio is not there yet
 voiceReply(@{@"id":readRequest[@"id"],@"status":@"system",@"local":@"no_reference",@"files":@[wav]});
 assert(hintReadSystem);assert([speaker.said.lastObject isEqual:@"乙"]);
 assert(!hintVoiceSetup.hidden);assert([hintVoiceSetup.title isEqual:@"录我的声音"]);
 [hintActions close:nil];assert(speaker.talking&&hintReadID);   // the system voice reads on
 [hintActions read:nil];assert(!hintReadOn());assert(!speaker.talking&&!hintReadID);
 hintOpen();hintWorking=NO;hintDone=YES;hintPagedAnswer=nil;hintShow(@"丙\n丁");[hintActions read:nil];
 readRequest=hintJSON(hintPath(@"hint-voice-request.json"));
 voiceReply(@{@"id":readRequest[@"id"],@"status":@"working",@"engine":@"local",@"files":@[wav]});assert(hintPlayer);
 [hintActions close:nil];assert(!hintPlayer&&!hintReadID);
 assert([hintJSON(hintPath(@"hint-voice-request.json"))[@"cancel"] boolValue]);
 [hintActions read:nil];assert(!hintReadOn());
 // A question asked with 朗读 on is read while it streams: a finished sentence before the answer is done.
 [@"{\"enabled\":true,\"voice\":{\"enabled\":true}}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 [speaker.said removeAllObjects];speaker.talking=NO;
 hintOpen();hintWorking=NO;hintDone=YES;hintQuestion.stringValue=@"去哪";[hintActions send:nil];
 assert([hintJSON(hintPath(@"hint-request.json"))[@"read"] boolValue]);assert([hintReadID isEqual:hintID]);
 [[NSJSONSerialization dataWithJSONObject:@{@"id":hintID,@"session":hintSession,@"status":@"working",@"stage":@"正在回答",@"partial":@"往北走。\n再找"} options:0 error:nil] writeToFile:hintPath(@"hint-response.json") atomically:YES];
 hintPoll();voiceReply(@{@"id":hintID,@"status":@"system",@"local":@"missing"});
 assert(([speaker.said isEqual:@[@"往北走。"]]));finishLine();assert(speaker.said.count==1);   // "再找" is still being written
 [hintActions close:nil];assert(!hintReadID);
 [@"{\"enabled\":true}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 // While the model works the panel says what it is doing, then types the answer out on its pages; the page the player
 // turned to stays when the finished answer arrives.
 NSString *responsePath=hintPath(@"hint-response.json");
 void (^respond)(NSDictionary *)=^(NSDictionary *fields){NSMutableDictionary *r=[@{@"id":@"stream",@"session":@"s"} mutableCopy];[r addEntriesFromDictionary:fields];
  [[NSJSONSerialization dataWithJSONObject:r options:0 error:nil] writeToFile:responsePath atomically:YES];};
 hintOpen();hintID=@"stream";hintSession=@"s";hintWorking=YES;hintDone=NO;hintStarted=NSDate.date;
 hintPagedAnswer=nil;hintPages=nil;hintPartial=nil;hintRevealed=0;
 respond(@{@"status":@"working",@"stage":@"正在看任务日志",@"partial":@""});hintPoll();
 assert([hintDisclosure.stringValue containsString:@"正在看任务日志"]);assert([hintText.stringValue isEqual:@"让我想想…"]);
 respond(@{@"status":@"working",@"stage":@"正在回答",@"partial":@"第一行\n第二行\n第三行\n第四行"});hintPoll();
 assert(hintRevealTimer);hintReveal();assert(hintRevealed==3&&[hintText.stringValue isEqual:@"第一行"]);
 while(hintRevealed<hintPartial.length)hintReveal();
 assert([hintText.stringValue isEqual:@"第一行\n第二行\n第三行  ▼"]);
 assert(totk_hint_key(ret,YES));assert([hintText.stringValue isEqual:@"第四行"]);
 respond(@{@"status":@"done",@"text":@"第一行\n第二行\n第三行\n第四行"});hintPoll();
 assert(hintDone&&!hintWorking&&!hintRevealTimer);assert(hintPage==1&&[hintText.stringValue isEqual:@"第四行"]);
 [hintActions close:nil];
 // 指给我看: the panel pauses the game once the frame it opens on is saved, offers pointing, and draws the answer's
 // marks over the paused window until the game moves again. Without a new frame (a covered window) it pauses anyway.
 [@"{\"enabled\":true}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 [hintActions close:nil];assert(!assistantPaused);[w orderFront:nil];
 hintOpen();assert(!assistantPaused&&!hintSceneReady);   // a plain question leaves the game running
 hintWorking=NO;hintDone=YES;hintLayout(0);assert(!hintPointButton.hidden);
 hintQuestion.stringValue=@"";[hintActions point:nil];   // saves the frame, pauses, then sends
 assert(assistantPaused&&hintSceneReady);assert(hintSceneSaved(hintPath(@"hint-scene.png")));
 NSDictionary *pointing=hintJSON(hintPath(@"hint-request.json"));
 assert([pointing[@"scene"] boolValue]&&[pointing[@"question"] hasPrefix:@"指给我看"]&&!pointing[@"actions"]);
 NSArray *marks=@[@{@"kind":@"circle",@"at":@[@0.34,@0.51],@"label":@"发光图案"},@{@"kind":@"arrow",@"at":@[@0.8,@0.9],@"to":@[@0.4,@0.55],@"label":@"往这边走"}];
 [[NSJSONSerialization dataWithJSONObject:@{@"id":hintID,@"session":hintSession,@"status":@"done",@"text":@"圈出的图案在旗帜右边。",@"marks":marks} options:0 error:nil]
  writeToFile:hintPath(@"hint-response.json") atomically:YES];
 hintPoll();assert(hintMarksWindow.visible&&hintMarks.count==2);
 // Marks the panel would hide move it to the other side; it comes back when they go.
 CGFloat rightX=NSMinX(hintPanel.frame);
 hintMarksShow(@[@{@"kind":@"circle",@"at":@[@0.85,@0.5],@"label":@"右边的东西"}]);
 assert(hintPanelLeft&&NSMinX(hintPanel.frame)<rightX);
 hintMarksShow(marks);
 if(getenv("HINT_PROBE_MARKS")){   // a look at the drawing: the marks over a picture
  NSView *view=hintMarksWindow.contentView;NSBitmapImageRep *shot=[view bitmapImageRepForCachingDisplayInRect:view.bounds];
  [NSGraphicsContext saveGraphicsState];[NSGraphicsContext setCurrentContext:[NSGraphicsContext graphicsContextWithBitmapImageRep:shot]];
  if(getenv("HINT_PROBE_SCENE"))[[[NSImage alloc] initWithContentsOfFile:@(getenv("HINT_PROBE_SCENE"))] drawInRect:view.bounds];
  [view drawRect:view.bounds];[NSGraphicsContext restoreGraphicsState];
  [[shot representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:@(getenv("HINT_PROBE_MARKS")) atomically:YES];
 }
 [hintActions close:nil];assert(!hintMarksWindow.visible&&!hintSceneReady&&!assistantPaused&&!hintPanelLeft);
 // The answer that talks about the circles does not stay in the bubble once they are gone, nor unexplained on reopening.
 assert([hintBubble.stringValue containsString:@"已清除"]);assert(!hintMarksWindow.hidesOnDeactivate);
 hintOpen();assert([hintDisclosure.stringValue containsString:@"圈画已清除"]);[hintActions close:nil];
 // The controller (totk_hint_pad): its assistant button opens the panel as key 8 does, A turns a page as Return does, B
 // closes it as Esc does; while it is closed only the assistant button reaches it.
 assert(!totk_hint_pad(CONTROLLER_UI_HELD)&&!totk_hint_pad(CONTROLLER_UI_ACCEPT));
 assert(totk_hint_pad(CONTROLLER_UI_ASSISTANT)&&hintPanel.visible&&totk_hint_pad(CONTROLLER_UI_HELD)&&!assistantPaused);   // the game runs on
 hintWorking=NO;hintDone=YES;hintHistoryExpanded=NO;hintPagedAnswer=nil;hintShow(@"甲\n乙\n丙\n丁");assert(hintPagesRemain());
 assert(totk_hint_pad(CONTROLLER_UI_ACCEPT)&&[hintText.stringValue isEqual:@"丁"]);
 assert(totk_hint_pad(CONTROLLER_UI_DOWN)&&totk_hint_pad(CONTROLLER_UI_UP));
 assert(totk_hint_pad(CONTROLLER_UI_BACK)&&!hintPanel.visible&&!totk_hint_pad(CONTROLLER_UI_HELD)&&!assistantPaused);
 shotFails=YES;[[NSFileManager defaultManager] removeItemAtPath:hintPath(@"hint-scene.png") error:nil];
 hintOpen();assert(!assistantPaused);
 hintQuestion.stringValue=@"";[hintActions point:nil];   // the frame never arrives: pause anyway, ask without marks
 [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.8]];
 assert(assistantPaused&&!hintSceneReady);
 [hintActions close:nil];shotFails=NO;
 // runtime_state's changes name what appeared or vanished since the previous observation.
 sceneExtra=0;assert(!runtimeStateReply(@"d0")[@"changes"]);
 sceneExtra=1;NSDictionary *changed=runtimeStateReply(@"d1");
 assert([changed[@"changes"][@"appeared"][0] isEqual:@"SpObj_Switch_A_01"]);
 sceneExtra=0;NSDictionary *gone=runtimeStateReply(@"d2");
 assert([gone[@"changes"][@"vanished"][0] isEqual:@"SpObj_Switch_A_01"]);
 // A sequence is one call for several presses; every step spends the same budget, and a run that does not fit is refused.
 [@"{\"enabled\":true,\"allow_actions\":true}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 hintActionLimitLoad();assert(hintActionLimit==6);
 hintWorking=YES;hintActionsGranted=YES;hintActionCount=0;hintID=@"seq";
 NSUInteger before=syntheticDowns;
 NSArray *two=@[@{@"button":@"a",@"duration_ms":@30,@"wait_ms":@20},@{@"button":@"down",@"duration_ms":@30,@"wait_ms":@20}];
 NSDictionary *sequence=runtimeSequence(@"seq",two);
 assert([sequence[@"ok"] boolValue]);assert(hintActionCount==2);assert(syntheticDowns==before+2);
 NSMutableArray *seven=[NSMutableArray new];
 for(int i=0;i<7;i++)[seven addObject:@{@"button":@"a",@"duration_ms":@30,@"wait_ms":@0}];
 hintActionCount=0;assert([runtimeSequence(@"seq-over",seven)[@"error"] isEqual:@"action_limit"]);
 NSMutableArray *nine=[NSMutableArray new];
 for(int i=0;i<9;i++)[nine addObject:@{@"button":@"a",@"duration_ms":@30,@"wait_ms":@0}];
 assert([runtimeSequence(@"seq-nine",nine)[@"error"] isEqual:@"invalid_steps"]);
 hintActionCount=0;assert([runtimeSequence(@"seq-bad",@[@{@"button":@"nope",@"duration_ms":@30,@"wait_ms":@0}])[@"error"] isEqual:@"invalid_steps"]);
 // assistant.json can widen the budget, and the panel reads it before every request.
 [@"{\"enabled\":true,\"allow_actions\":true,\"action_limit\":3}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 hintActionLimitLoad();assert(hintActionLimit==3);
 hintActionCount=0;hintWorking=YES;hintActionsGranted=YES;
 assert([runtimeSequence(@"seq-budget",@[@{@"button":@"a",@"duration_ms":@30,@"wait_ms":@0},@{@"button":@"a",@"duration_ms":@30,@"wait_ms":@0},@{@"button":@"a",@"duration_ms":@30,@"wait_ms":@0}])[@"ok"] boolValue]);
 assert([runtimeSequence(@"seq-budget-over",two)[@"error"] isEqual:@"action_limit"]);
 hintWorking=NO;hintActionsGranted=NO;
 // A press with the panel open and the game running leaves it running, after the press and after closing (it paused
 // the game after the press, and closing never released it: the panel held no pause of its own).
 [@"{\"enabled\":true,\"allow_actions\":true}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 [hintActions close:nil];hintOpen();assert(!assistantPaused&&!hintPauseHeld&&![hintRuntimeState()[@"assistant_paused"] boolValue]);
 hintWorking=YES;hintActionsGranted=YES;hintActionCount=0;hintID=@"running-press";
 assert(runtimePress(@"running-1")==nil);[[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.3]];
 assert(!hintRuntimeActive()&&!assistantPaused);
 hintWorking=NO;hintActionsGranted=NO;[hintActions close:nil];assert(!assistantPaused);
 // With the panel holding the pause (指给我看), a press lets the game move and the pause comes back after it.
 hintOpen();hintPause();[[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.8]];
 assert(hintPauseHeld&&assistantPaused&&[hintRuntimeState()[@"assistant_paused"] boolValue]);
 hintWorking=YES;hintActionsGranted=YES;hintActionCount=0;hintID=@"paused-press";
 assert(runtimePress(@"paused-1")==nil&&!assistantPaused);[[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.3]];
 assert(assistantPaused);
 hintWorking=NO;hintActionsGranted=NO;[hintActions close:nil];assert(!assistantPaused&&!hintPauseHeld);
 // 指路: the service's answer (no model) becomes an arrow that turns with the camera and leaves when Link is close.
 [@"{\"enabled\":true}" writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
 hintService=[FakeHintTask new];hintGuideHide();[hintActions guide:nil];
 NSDictionary *guideAsk=hintJSON(hintPath(@"guide-request.json"));assert([guideAsk[@"id"] isKindOfClass:NSString.class]);
 void (^guideReply)(NSDictionary *)=^(NSDictionary *target){
  NSDictionary *ask=hintJSON(hintPath(@"guide-request.json"));   // the newest request, not the one captured above
  [[NSJSONSerialization dataWithJSONObject:@{@"id":ask[@"id"],@"ok":@YES,@"target":target} options:0 error:nil] writeToFile:hintPath(@"guide-response.json") atomically:YES];
  hintGuidePoll();};
 guideReply(@{@"name":@"希多",@"quest":@"主线",@"xyz":@[@0,@0,@(-300)],@"distance_m":@300});
 assert(hintGuidePanel.visible);hintGuideTick();
 assert(fabs(hintGuideDistance-303)<6);assert(fabs(hintGuideAngle)<1);   // straight ahead of the camera
 cameraConvention=1;hintGuideTick();assert(fabs(hintGuideAngle)<1);   // the other axis convention reads the same
 cameraConvention=0;
 cameraMissing=1;hintGuideTick();assert(fabs(hintGuideAngle)<1);cameraMissing=0;   // no camera: Link faces north too, so ahead (it read south)
 hintGuideHide();assert(!hintGuidePanel.visible);
 // A target without Link's place in the save: no distance or name (null), still an arrow; null in its position: none.
 [hintActions guide:nil];guideReply(@{@"name":NSNull.null,@"xyz":@[@0,@0,@(-300)],@"distance_m":NSNull.null});
 assert(hintGuidePanel.visible&&!hintGuideLabel);hintGuideTick();assert(fabs(hintGuideDistance-303)<6);hintGuideHide();
 [hintActions guide:nil];guideReply(@{@"name":@"坏",@"xyz":@[@0,NSNull.null,@(-300)],@"distance_m":@300});
 assert(!hintGuidePanel.visible&&[hintDisclosure.stringValue containsString:@"没有找到"]);
 [hintActions guide:nil];guideAsk=hintJSON(hintPath(@"guide-request.json"));
 guideReply(@{@"name":@"脚下",@"xyz":@[@1,@2,@8],@"distance_m":@5});
 assert(hintGuidePanel.visible);hintGuideTick();assert(!hintGuidePanel.visible);   // close enough: the arrow leaves
 [hintTimer invalidate];[hintPanel orderOut:nil];puts("pass: enable preserves config, does not send request, rejects invalid config");
}}
