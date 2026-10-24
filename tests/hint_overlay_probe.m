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
 hintShow(@"新回答第一行\n二\n三\n四");assert(hintPage==0);assert(totk_hint_key(ret,YES));assert(hintPage==1);
 // 朗读 is off by default; switching it on is remembered and, without the voice service, reads with the system voice.
 FakeSpeaker *speaker=[FakeSpeaker new];hintSpeaker=speaker;
 assert(!hintReadOn());hintService=nil;hintShow(answer);
 [hintActions read:nil];assert(hintReadOn());assert([hintJSON(path)[@"enabled"] boolValue]);
 assert(hintReadSystem);assert([speaker.said isEqual:@[@"第一行\n第二行\n第三行"]]);
 [hintActions speechSynthesizer:speaker didFinishSpeechUtterance:[AVSpeechUtterance speechUtteranceWithString:@""]];
 [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
 assert(hintPage==1);assert([speaker.said.lastObject isEqual:@"第四行\n第五行"]);
 [hintActions read:nil];assert(!hintReadOn());assert(!speaker.talking);
 // With the service: reading asks it for the pages; "no_reference" falls back to the system voice and offers recording.
 hintService=[FakeHintTask new];hintShow(@"甲\n乙");[hintActions read:nil];
 NSDictionary *readRequest=hintJSON(hintPath(@"hint-voice-request.json"));assert([readRequest[@"pages"] isEqual:@[@"甲\n乙"]]);
 [[NSJSONSerialization dataWithJSONObject:@{@"id":readRequest[@"id"],@"status":@"no_reference"} options:0 error:nil] writeToFile:hintPath(@"hint-voice.json") atomically:YES];
 hintVoicePoll();assert(hintReadSystem);assert([speaker.said.lastObject isEqual:@"甲\n乙"]);
 assert(!hintVoiceSetup.hidden);assert([hintVoiceSetup.title isEqual:@"录我的声音"]);
 [hintActions close:nil];assert(!speaker.talking);
 [hintActions read:nil];assert(!hintReadOn());
 [hintTimer invalidate];[hintPanel orderOut:nil];puts("pass: enable preserves config, does not send request, rejects invalid config");
}}
