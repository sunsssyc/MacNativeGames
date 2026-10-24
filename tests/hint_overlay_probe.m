#include "../games/totk/runtime/hint_overlay.m"
#include <assert.h>
int runtime_live_player(float xyz[3]){(void)xyz;return 0;}
static unsigned syntheticDowns;static int syntheticHeld=-1;
void runtime_input_key_synthetic(unsigned code,int down){if(down){syntheticDowns++;syntheticHeld=(int)code;}else if(syntheticHeld==(int)code)syntheticHeld=-1;}
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
 assert(assistantPaused);assert(!hintWelcome);assert(!hintQuestion.hidden);assert(hintQuestion.editable);assert(hintQuestion.stringValue.length==0);
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
 assert([hintSession isEqual:@"preserved-session"]);assert(assistantPaused);
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
 hintOpen();assert(assistantPaused&&hintSceneReady);assert(hintSceneSaved(hintPath(@"hint-scene.png")));
 hintWorking=NO;hintDone=YES;hintLayout(0);assert(!hintPointButton.hidden);
 hintQuestion.stringValue=@"";[hintActions point:nil];
 NSDictionary *pointing=hintJSON(hintPath(@"hint-request.json"));
 assert([pointing[@"scene"] boolValue]&&[pointing[@"question"] hasPrefix:@"指给我看"]&&!pointing[@"actions"]);
 NSArray *marks=@[@{@"kind":@"circle",@"at":@[@0.34,@0.51],@"label":@"发光图案"},@{@"kind":@"arrow",@"at":@[@0.8,@0.9],@"to":@[@0.4,@0.55],@"label":@"往这边走"}];
 [[NSJSONSerialization dataWithJSONObject:@{@"id":hintID,@"session":hintSession,@"status":@"done",@"text":@"圈出的图案在旗帜右边。",@"marks":marks} options:0 error:nil]
  writeToFile:hintPath(@"hint-response.json") atomically:YES];
 hintPoll();assert(hintMarksWindow.visible&&hintMarks.count==2);
 if(getenv("HINT_PROBE_MARKS")){   // a look at the drawing: the marks over a picture
  NSView *view=hintMarksWindow.contentView;NSBitmapImageRep *shot=[view bitmapImageRepForCachingDisplayInRect:view.bounds];
  [NSGraphicsContext saveGraphicsState];[NSGraphicsContext setCurrentContext:[NSGraphicsContext graphicsContextWithBitmapImageRep:shot]];
  if(getenv("HINT_PROBE_SCENE"))[[[NSImage alloc] initWithContentsOfFile:@(getenv("HINT_PROBE_SCENE"))] drawInRect:view.bounds];
  [view drawRect:view.bounds];[NSGraphicsContext restoreGraphicsState];
  [[shot representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:@(getenv("HINT_PROBE_MARKS")) atomically:YES];
 }
 [hintActions close:nil];assert(!hintMarksWindow.visible&&!hintSceneReady&&!assistantPaused);
 shotFails=YES;[[NSFileManager defaultManager] removeItemAtPath:hintPath(@"hint-scene.png") error:nil];
 hintOpen();assert(!assistantPaused);   // waiting for the frame
 [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.8]];
 assert(assistantPaused&&!hintSceneReady);hintLayout(0);assert(hintPointButton.hidden);
 [hintActions close:nil];shotFails=NO;
 [hintTimer invalidate];[hintPanel orderOut:nil];puts("pass: enable preserves config, does not send request, rejects invalid config");
}}
