/* 历史: the panel's 历史 shows the conversations the hint service keeps (hint-history.json, which it writes from
   assistant.db when it starts and after every answer), so they are there after the game restarts too, whichever channel
   answered them; the question being worked out right now comes from this run's own list. Newest conversation first, each
   under a line with its day, place and channel; without the file (the assistant's memory off), this run's list alone. */
static NSArray<NSDictionary *> *hintSavedTurns(void){
 id turns=hintJSON(hintPath(@"hint-history.json"))[@"turns"];
 NSMutableArray *out=[NSMutableArray array];
 if([turns isKindOfClass:NSArray.class])for(id turn in turns)if([turn isKindOfClass:NSDictionary.class]&&[turn[@"answer"] isKindOfClass:NSString.class])[out addObject:turn];
 return out;
}
static NSUInteger hintHistoryCount(void){return hintHistory.count+hintSavedTurns().count;}
static NSString *hintHistoryText(void){
 NSArray<NSDictionary *> *turns=hintSavedTurns();
 if(!turns.count)return [hintHistory componentsJoinedByString:@"\n\n"];
 NSDateFormatter *day=[NSDateFormatter new];day.dateFormat=@"MM-dd HH:mm";
 NSMutableArray<NSMutableArray<NSString *> *> *sessions=[NSMutableArray array];NSString *current=nil;
 for(NSDictionary *turn in turns){   // oldest first in the file: grouped into conversations
  NSString *session=[turn[@"session"] isKindOfClass:NSString.class]?turn[@"session"]:@"";
  if(![session isEqual:current]||!sessions.count){
   current=session;NSMutableArray *parts=[NSMutableArray array];
   if([turn[@"time"] isKindOfClass:NSNumber.class])[parts addObject:[day stringFromDate:[NSDate dateWithTimeIntervalSince1970:[turn[@"time"] doubleValue]]]];
   for(NSString *key in @[@"place",@"channel"])if([turn[key] isKindOfClass:NSString.class]&&[turn[key] length])[parts addObject:turn[key]];
   [sessions addObject:[NSMutableArray arrayWithObject:[NSString stringWithFormat:@"—— %@ ——",[parts componentsJoinedByString:@" · "]]]];
  }
  NSString *question=[turn[@"question"] isKindOfClass:NSString.class]&&[turn[@"question"] length]?turn[@"question"]:@"（按了提示键）";
  [sessions.lastObject addObject:[@"你\n" stringByAppendingString:question]];
  [sessions.lastObject addObject:[@"露珠\n" stringByAppendingString:turn[@"answer"]]];
 }
 NSMutableArray<NSString *> *blocks=[NSMutableArray array];
 if(hintWorking&&hintLastQuestion.length)[blocks addObject:[NSString stringWithFormat:@"你\n%@\n（正在回答）",hintLastQuestion]];
 for(NSArray *session in sessions.reverseObjectEnumerator)[blocks addObject:[session componentsJoinedByString:@"\n\n"]];
 return [blocks componentsJoinedByString:@"\n\n\n"];
}
