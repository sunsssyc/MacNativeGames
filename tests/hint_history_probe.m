/* runtime/hint_history.inc alone: the panel's 历史 from hint-history.json (written by the hint service from assistant.db),
   with the few panel globals it reads. argv[1]: a folder to use as the game's data folder. */
#import <Cocoa/Cocoa.h>
#include <assert.h>
static NSMutableArray<NSString *> *hintHistory;
static BOOL hintWorking;
static NSString *hintLastQuestion, *hintFolder;
static NSString *hintPath(NSString *name) { return [hintFolder stringByAppendingPathComponent:name]; }
static NSDictionary *hintJSON(NSString *path) {
 NSData *data=[NSData dataWithContentsOfFile:path];
 id value=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
 return [value isKindOfClass:NSDictionary.class]?value:nil;
}
#include "../games/totk/runtime/hint_history.inc"

int main(int argc, const char **argv) { @autoreleasepool {
 if(argc!=2)return 2;
 hintFolder=@(argv[1]);hintHistory=[NSMutableArray new];
 /* No file (memory off, or before the service first ran): this run's own list. */
 assert(hintHistoryCount()==0 && [hintHistoryText() isEqualToString:@""]);
 [hintHistory addObjectsFromArray:@[@"你\n刚才的问题",@"露珠\n刚才的回答"]];
 assert(hintHistoryCount()==2 && [hintHistoryText() isEqualToString:@"你\n刚才的问题\n\n露珠\n刚才的回答"]);
 /* The service's file: two conversations from earlier runs, oldest first; the newest shows on top. */
 NSDictionary *file=@{@"turns":@[
  @{@"time":@1792800000,@"session":@"r1/1",@"question":@"这个神庙怎么过",@"answer":@"先往左走。",@"place":@"吉鲁塔古马奇神庙",@"channel":@"Claude Code（本机）"},
  @{@"time":@1792800060,@"session":@"r1/1",@"question":[NSNull null],@"answer":@"用翼和平台车。",@"place":@"吉鲁塔古马奇神庙",@"channel":@"Claude Code（本机）"},
  @{@"time":@1792900000,@"session":@"r2/3",@"question":@"雷之神殿头目怎么打",@"answer":@"先用雷击破甲。",@"channel":@"Gemini 4（Vertex AI）"},
  @{@"broken":@YES}, @"not a turn"]};
 assert([[NSJSONSerialization dataWithJSONObject:file options:0 error:nil] writeToFile:hintPath(@"hint-history.json") atomically:YES]);
 NSString *text=hintHistoryText();
 assert(hintHistoryCount()==5);   /* three saved turns and this run's two lines */
 NSRange gemini=[text rangeOfString:@"Gemini 4（Vertex AI）"],claude=[text rangeOfString:@"吉鲁塔古马奇神庙 · Claude Code（本机）"];
 assert(gemini.location!=NSNotFound && claude.location!=NSNotFound && gemini.location<claude.location);   /* newest first */
 assert([text containsString:@"你\n雷之神殿头目怎么打\n\n露珠\n先用雷击破甲。"]);
 assert([text containsString:@"你\n这个神庙怎么过\n\n露珠\n先往左走。\n\n你\n（按了提示键）\n\n露珠\n用翼和平台车。"]);   /* one conversation, in order */
 assert([text hasPrefix:@"—— "] && [text componentsSeparatedByString:@"—— "].count==3);   /* a heading per conversation */
 /* The question being answered now is not in the file yet: it shows first. */
 hintWorking=YES;hintLastQuestion=@"宝箱在哪";
 assert([hintHistoryText() hasPrefix:@"你\n宝箱在哪\n（正在回答）"]);
 hintWorking=NO;
 /* A broken file is the same as none. */
 assert([@"{ broken" writeToFile:hintPath(@"hint-history.json") atomically:YES encoding:NSUTF8StringEncoding error:nil]);
 assert(hintHistoryCount()==2 && [hintHistoryText() hasPrefix:@"你\n刚才的问题"]);
 puts("pass: panel history from hint-history.json");
 return 0;
}}
