#include "../games/totk/runtime/hint_overlay.m"
#include <assert.h>
int runtime_live_player(float xyz[3]){(void)xyz;return 0;}
void runtime_input_key_synthetic(unsigned code,int down){(void)code;(void)down;}
static int assistantPaused;
void runtime_assistant_pause(int on){assistantPaused=on;}
@interface FakeHintTask:NSTask
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
 hintID=@"deadline-test";hintSession=@"test-session";hintWorking=YES;hintDone=NO;hintStarted=[NSDate dateWithTimeIntervalSinceNow:-121];
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
 [hintTimer invalidate];[hintPanel orderOut:nil];puts("pass: enable preserves config, does not send request, rejects invalid config");
}}
