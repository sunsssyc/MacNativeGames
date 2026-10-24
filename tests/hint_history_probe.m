/* runtime/hint_history.inc alone: the panel's 历史 as a list of conversations from hint-history.json (written by the hint
   service from assistant.db), with the few panel pieces it uses. argv[1]: a folder to use as the game's data folder. */
#import <Cocoa/Cocoa.h>
#include <assert.h>
static NSMutableArray<NSString *> *hintHistory;
static BOOL hintDone, hintHistoryExpanded;
static NSString *hintFolder, *hintLatest, *hintSession, *hintPendingQuestion;
static NSInteger hintTier;
static NSTextField *hintText, *hintDisclosure;
static NSScrollView *hintScroll;
static int layouts;
static NSString *hintPath(NSString *name) { return [hintFolder stringByAppendingPathComponent:name]; }
static NSDictionary *hintJSON(NSString *path) {
 NSData *data=[NSData dataWithContentsOfFile:path];
 id value=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
 return [value isKindOfClass:NSDictionary.class]?value:nil;
}
static NSColor *hintInk(void){return NSColor.whiteColor;}
static NSFont *hintFont(CGFloat size){return [NSFont systemFontOfSize:size];}
static NSString *hintPageText(NSString *answer){return answer;}
#include "../games/totk/runtime/hint_history.inc"
static void hintLayout(CGFloat height){(void)height;layouts++;hintHistoryLayout(300);}   // as the panel's does

int main(int argc, const char **argv) { @autoreleasepool {
 if(argc!=2)return 2;
 [NSApplication sharedApplication];
 hintFolder=@(argv[1]);hintHistory=[NSMutableArray new];
 hintText=[NSTextField wrappingLabelWithString:@""];hintDisclosure=[NSTextField labelWithString:@""];
 hintScroll=[[NSScrollView alloc] initWithFrame:NSMakeRect(0,0,300,200)];hintScroll.documentView=hintText;
 hintLatest=@"最新的回答";hintDone=YES;
 /* No file (memory off, or before the service first ran): this run's own turns, as text. */
 assert(hintHistoryCount()==0);
 [hintHistory addObjectsFromArray:@[@"你\n刚才的问题",@"露珠\n刚才的回答"]];
 hintHistoryToggle();
 assert(hintHistoryExpanded && hintScroll.documentView==hintText && [hintText.stringValue isEqualToString:@"你\n刚才的问题\n\n露珠\n刚才的回答"]);
 hintHistoryToggle();assert(!hintHistoryExpanded && [hintText.stringValue isEqualToString:@"最新的回答"]);
 /* The service's file: conversations newest first. */
 NSDictionary *file=@{@"sessions":@[
  @{@"id":@"S2",@"title":@"雷之神殿头目怎么打",@"time":@1792900000,@"place":@"雷之神殿",@"channel":@"Gemini 4（Vertex AI）",@"tier":@2,
    @"turns":@[@{@"question":@"雷之神殿头目怎么打",@"answer":@"先用雷击破甲。",@"tier":@2}]},
  @{@"id":@"S1",@"title":@"这个神庙怎么过",@"time":@1792800060,@"place":@"吉鲁塔古马奇神庙",@"channel":@"Claude Code（本机）",@"tier":@1,
    @"turns":@[@{@"question":@"这个神庙怎么过",@"answer":@"先往左走。",@"tier":@1},@{@"question":[NSNull null],@"answer":@"用翼和平台车。",@"tier":@2}]},
  @{@"id":@"broken"},@"not a session"]};
 assert([[NSJSONSerialization dataWithJSONObject:file options:0 error:nil] writeToFile:hintPath(@"hint-history.json") atomically:YES]);
 assert(hintHistoryCount()==4);   /* two saved conversations and this run's two lines */
 assert([hintHistoryButtonTitle() isEqualToString:@"历史"]);
 hintHistoryToggle();   /* the list */
 assert(hintScroll.documentView==hintHistoryList && hintHistoryList.subviews.count==2);
 TOTKHintHistoryRow *first=(TOTKHintHistoryRow *)hintHistoryList.subviews[0],*second=(TOTKHintHistoryRow *)hintHistoryList.subviews[1];
 assert([first.heading isEqualToString:@"雷之神殿头目怎么打"] && [first.detail hasSuffix:@" · 雷之神殿 · Gemini 4（Vertex AI） · 1 轮"]);
 assert([second.detail hasSuffix:@"吉鲁塔古马奇神庙 · Claude Code（本机） · 2 轮"] && NSMinY(second.frame)>NSMinY(first.frame));
 assert([hintHistoryButtonTitle() isEqualToString:@"最新回复"]);
 [second performClick:nil];   /* one conversation */
 assert(hintHistoryOpen==second.session && hintScroll.documentView==hintText);
 assert([hintText.stringValue isEqualToString:@"你\n这个神庙怎么过\n\n露珠\n先往左走。\n\n你\n（按了提示键）\n\n露珠\n用翼和平台车。"]);
 assert([hintHistoryButtonTitle() isEqualToString:@"返回列表"] && [hintDisclosure.stringValue containsString:@"接着这次对话"]);
 hintHistoryToggle();assert(!hintHistoryOpen && hintScroll.documentView==hintHistoryList);   /* back to the list */
 [second performClick:nil];
 /* A question typed now goes on with that conversation: its id, its last tier, its turns. */
 hintSession=@"current";hintTier=1;hintPendingQuestion=@"宝箱呢";
 hintHistoryAdopt();
 assert([hintSession isEqualToString:@"S1"] && hintTier==1 && !hintHistoryOpen && hintHistory.count==3);
 /* Without a question, nothing is adopted. */
 hintHistoryOpen=first.session;hintPendingQuestion=nil;hintHistoryAdopt();assert([hintSession isEqualToString:@"S1"]);
 hintHistoryExpanded=YES;hintHistoryOpen=nil;hintHistoryToggle();assert(!hintHistoryExpanded && [hintText.stringValue isEqualToString:@"最新的回答"]);
 /* A broken file is the same as none. */
 assert([@"{ broken" writeToFile:hintPath(@"hint-history.json") atomically:YES encoding:NSUTF8StringEncoding error:nil]);
 assert(hintHistoryCount()==3);
 puts("pass: panel history list from hint-history.json");
 return 0;
}}
