/* Key 8 asks for progressively more explicit hints. The child panel never takes keyboard focus.
   Python owns the read-only game-data tools and model backends; IPC is atomic JSON in the user data folder. */
#import "hint_overlay.h"
#include "game_version.h"
#include <unistd.h>

static NSPanel *hintPanel;
static NSTextField *hintText;
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
static void hintShow(NSString *text) {
 hintText.stringValue=text;
 NSRect f=hintGame.frame;
 [hintPanel setFrameTopLeftPoint:NSMakePoint(NSMaxX(f)-490,NSMaxY(f)-70)];
 [hintGame addChildWindow:hintPanel ordered:NSWindowAbove];[hintPanel orderFront:nil];
}
static BOOL hintWrite(NSDictionary *value) {
 NSData *data=[NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
 return data&&[data writeToFile:hintPath(@"hint-request.json") options:NSDataWritingAtomic error:nil];
}
static BOOL hintStart(void) {
 if(hintService.running)return YES;
 NSString *script=[NSFileManager.defaultManager.currentDirectoryPath stringByAppendingPathComponent:@"tools/hint_assistant/run.py"];
 const char *override=getenv("TOTK_HINT_PYTHON");
 NSString *python=override&&*override?@(override):nil;
 if(!python){for(NSString *p in @[@"/opt/homebrew/bin/python3.14",@"/usr/local/bin/python3.14",@"/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14"]){
  if([NSFileManager.defaultManager isExecutableFileAtPath:p]){python=p;break;}
 }}
 if(!python||![NSFileManager.defaultManager fileExistsAtPath:script]){
  hintShow(@"卡关助手需要 Python 3.14 和随游戏附带的 hint_assistant。\n可用 TOTK_HINT_PYTHON 指定 Python 3.14 路径。");return NO;
 }
 [NSFileManager.defaultManager removeItemAtPath:hintPath(@"hint-request.json") error:nil];
 hintService=[NSTask new];hintService.executableURL=[NSURL fileURLWithPath:python];
 hintService.arguments=@[@"-E",@"-s",script,@"serve",@"--parent-pid",[@(getpid()) stringValue],@"--folder",hintFolder,@"--accept-pending",
                        @"--romfs",@"extracted/" TOTK_GAME_DIR "/romfs"];
 NSError *error=nil;
 if(![hintService launchAndReturnError:&error]){hintShow([@"无法启动卡关助手：" stringByAppendingString:error.localizedDescription]);return NO;}
 return YES;
}
static void hintPoll(void) {
 if(!hintWorking)return;
 NSDictionary *answer=hintJSON(hintPath(@"hint-response.json"));
 if([answer[@"id"] isEqual:hintID]&&[answer[@"session"] isEqual:hintSession]){
  NSString *status=answer[@"status"],*text=answer[@"text"];
  if([text isKindOfClass:NSString.class]){
   BOOL done=[status isEqual:@"done"];hintDone=done;
   NSString *footer=done?(hintTier<3?@"\n\n8 更具体 · Shift+8 新问题 · Esc 关闭":@"\n\nShift+8 新问题 · Esc 关闭"):@"\n\nEsc 取消";
   hintShow([text stringByAppendingString:footer]);
  }
  if(![status isEqual:@"working"]){hintWorking=NO;return;}
 }
 if(!hintService.running||-[hintStarted timeIntervalSinceNow]>600){
  hintWrite(@{@"id":hintID,@"session":hintSession,@"cancel":@YES});hintWorking=NO;
  hintShow(@"卡关助手已停止或等待超时。按 8 重试，Esc 关闭。\n详细原因见游戏日志。");
 }
}
void totk_hint_install(NSWindow *window) {
#if defined(GAME_BOTW)
 (void)window;return;
#endif
 hintGame=window;
 hintFolder=[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/MacNativeGames/TOTK"];
 hintPanel=[[NSPanel alloc] initWithContentRect:NSMakeRect(0,0,470,270) styleMask:NSWindowStyleMaskBorderless|NSWindowStyleMaskNonactivatingPanel backing:NSBackingStoreBuffered defer:NO];
 hintPanel.backgroundColor=[NSColor colorWithCalibratedWhite:0.08 alpha:0.96];hintPanel.hasShadow=YES;
 hintPanel.collectionBehavior=NSWindowCollectionBehaviorFullScreenAuxiliary;
 hintText=[NSTextField wrappingLabelWithString:@""];hintText.frame=NSMakeRect(20,18,430,234);
 hintText.font=[NSFont systemFontOfSize:18];hintText.textColor=NSColor.whiteColor;
 [hintPanel.contentView addSubview:hintText];
 hintTimer=[NSTimer scheduledTimerWithTimeInterval:0.25 repeats:YES block:^(NSTimer *timer){(void)timer;hintPoll();}];
}
BOOL totk_hint_key(NSEvent *event, BOOL down) {
 if(!hintGame)return NO;
 BOOL escape=event.keyCode==53&&hintPanel.visible;
 if(event.keyCode!=28&&!escape)return NO; // macOS virtual key 28: 8
 if(!down||event.isARepeat)return YES;
 if(escape){
  if(hintWorking)hintWrite(@{@"id":hintID,@"session":hintSession,@"cancel":@YES});
  hintWorking=NO;[hintPanel orderOut:nil];return YES;
 }
 NSDictionary *config=hintJSON(hintPath(@"assistant.json"));
 if(![config[@"enabled"] boolValue]){
  hintShow(@"卡关助手尚未启用。\n在 assistant.json 设置 enabled 为 true 后按 8。\n提示会把当前存档摘要交给 Claude Code、Codex 或 Vertex AI；截图默认关闭。\nEsc 关闭");return YES;
 }
 if(hintWorking)return YES;
 if(![NSFileManager.defaultManager createDirectoryAtPath:hintFolder withIntermediateDirectories:YES attributes:nil error:nil]){
  hintShow(@"无法创建卡关助手的数据目录。");return YES;
 }
 if(!hintStart())return YES;
 BOOL fresh=!hintSession||!hintPanel.visible||(event.modifierFlags&NSEventModifierFlagShift);
 if(fresh){hintSession=NSUUID.UUID.UUIDString;hintTier=[config[@"tier_default"] integerValue];if(hintTier<1||hintTier>3)hintTier=1;}
 else if(hintDone&&hintTier<3)hintTier++;
 hintID=NSUUID.UUID.UUIDString;
 if(!hintWrite(@{@"id":hintID,@"session":hintSession,@"tier":@(hintTier),@"time":@(NSDate.date.timeIntervalSince1970)})){
  hintShow(@"无法写入求助请求。");return YES;
 }
 hintDone=NO;hintWorking=YES;hintStarted=NSDate.date;hintShow(@"正在查看存档和任务日志……\n\nEsc 取消");return YES;
}
