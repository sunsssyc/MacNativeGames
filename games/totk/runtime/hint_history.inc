/* 历史: the panel's 历史 is a list of earlier conversations, as in a chat app: newest first, each named by its first
   question, with when, where, which channel answered and how many turns underneath. A click opens one in the panel; a
   question typed while it is open goes on with that conversation, after a restart too (the hint service finds its earlier
   turns in assistant.db). The list is hint-history.json, which the service writes from assistant.db when it starts and
   after every answer; without it (the assistant's memory off) 历史 shows this run's own turns as before. */
static void hintLayout(CGFloat height);
static NSDictionary *hintHistoryOpen;   // the conversation shown; nil: the list
static NSView *hintHistoryList;

/* The first version of the file (2026-10-24 19:55) listed turns, oldest first, each with "run/session": grouped here into
   conversations the same way, so 历史 shows them before the new service has written the file again. */
static NSArray<NSDictionary *> *hintSessionsFromTurns(NSArray *turns){
 NSMutableArray *order=[NSMutableArray array];NSMutableDictionary<NSString *,NSMutableArray *> *byId=[NSMutableDictionary dictionary];
 for(id turn in turns){
  if(![turn isKindOfClass:NSDictionary.class]||![turn[@"answer"] isKindOfClass:NSString.class])continue;
  NSString *key=[turn[@"session"] isKindOfClass:NSString.class]?turn[@"session"]:@"-";
  if(!byId[key]){byId[key]=[NSMutableArray array];[order addObject:key];}
  [byId[key] addObject:turn];
 }
 NSMutableArray *out=[NSMutableArray array];
 for(NSString *key in order.reverseObjectEnumerator){
  NSArray *ts=byId[key];NSDictionary *last=ts.lastObject;NSString *title=nil;
  for(NSDictionary *t in ts)if([t[@"question"] isKindOfClass:NSString.class]&&[t[@"question"] length]){title=t[@"question"];break;}
  NSString *sid=[key componentsSeparatedByString:@"/"].lastObject;   // "run/session": the panel's session id; "-": none
  NSMutableDictionary *session=[@{@"id":[sid isEqualToString:@"-"]?@"":sid,@"title":title?:@"按进度给的提示",@"turns":ts} mutableCopy];
  for(NSString *field in @[@"time",@"place",@"channel",@"tier"])if(last[field]&&last[field]!=NSNull.null)session[field]=last[field];
  [out addObject:session];
 }
 return out;
}
static NSArray<NSDictionary *> *hintSavedSessions(void){
 NSDictionary *file=hintJSON(hintPath(@"hint-history.json"));
 id sessions=file[@"sessions"];
 if(!sessions&&[file[@"turns"] isKindOfClass:NSArray.class])sessions=hintSessionsFromTurns(file[@"turns"]);
 NSMutableArray *out=[NSMutableArray array];
 if([sessions isKindOfClass:NSArray.class])for(id s in sessions)
  if([s isKindOfClass:NSDictionary.class]&&[s[@"id"] isKindOfClass:NSString.class]&&[s[@"turns"] isKindOfClass:NSArray.class]&&[s[@"turns"] count])[out addObject:s];
 return out;
}
static NSUInteger hintHistoryCount(void){return hintHistory.count+hintSavedSessions().count;}
static NSString *hintHistoryWhen(id time){
 if(![time isKindOfClass:NSNumber.class])return @"";
 NSDate *date=[NSDate dateWithTimeIntervalSince1970:[time doubleValue]];NSCalendar *calendar=NSCalendar.currentCalendar;
 NSDateFormatter *f=[NSDateFormatter new];
 f.dateFormat=[calendar isDateInToday:date]?@"今天 HH:mm":[calendar isDateInYesterday:date]?@"昨天 HH:mm":@"MM-dd HH:mm";
 return [f stringFromDate:date];
}
static NSString *hintHistoryText(NSString *value){return [value isKindOfClass:NSString.class]?value:@"";}
static NSString *hintHistoryDetail(NSDictionary *session){
 NSMutableArray *parts=[NSMutableArray arrayWithObject:hintHistoryWhen(session[@"time"])];
 for(NSString *key in @[@"place",@"channel"])if(hintHistoryText(session[key]).length)[parts addObject:session[key]];
 [parts addObject:[NSString stringWithFormat:@"%lu 轮",(unsigned long)[session[@"turns"] count]]];
 return [parts componentsJoinedByString:@" · "];
}
static NSString *hintHistoryTranscript(NSDictionary *session){
 NSMutableArray *blocks=[NSMutableArray array];
 for(NSDictionary *turn in session[@"turns"]){
  if(![turn isKindOfClass:NSDictionary.class])continue;
  NSString *question=hintHistoryText(turn[@"question"]);
  [blocks addObject:[@"你\n" stringByAppendingString:question.length?question:@"（按了提示键）"]];
  [blocks addObject:[@"露珠\n" stringByAppendingString:hintHistoryText(turn[@"answer"])]];
 }
 return [blocks componentsJoinedByString:@"\n\n"];
}
static CGFloat hintHistoryListHeight(void){   // the panel's body while 历史 shows the list: room for its rows (at most 7)
 return hintHistoryExpanded&&!hintHistoryOpen?MIN(7,hintSavedSessions().count)*50:0;
}
static NSString *hintHistoryButtonTitle(void){return !hintHistoryExpanded?@"历史":hintHistoryOpen?@"返回列表":@"最新回复";}

// One conversation in the list: its title, and when / where / who / how long in a smaller line; lit while hovered.
@interface TOTKHintHistoryRow:NSButton
@property(copy) NSString *heading,*detail;
@property(strong) NSDictionary *session;
@property BOOL hovered;
@property(strong) NSTrackingArea *area;
@end
@implementation TOTKHintHistoryRow
-(BOOL)isFlipped{return YES;}
-(BOOL)acceptsFirstResponder{return NO;}
-(void)updateTrackingAreas{
 [super updateTrackingAreas];if(self.area)[self removeTrackingArea:self.area];
 self.area=[[NSTrackingArea alloc] initWithRect:NSZeroRect options:NSTrackingMouseEnteredAndExited|NSTrackingActiveAlways|NSTrackingInVisibleRect owner:self userInfo:nil];[self addTrackingArea:self.area];
}
-(void)mouseEntered:(NSEvent *)e{(void)e;self.hovered=YES;self.needsDisplay=YES;}
-(void)mouseExited:(NSEvent *)e{(void)e;self.hovered=NO;self.needsDisplay=YES;}
-(void)drawRect:(NSRect)dirty{
 (void)dirty;NSRect r=NSInsetRect(self.bounds,0,2);
 if(self.hovered||self.highlighted){[[hintInk() colorWithAlphaComponent:self.highlighted?0.16:0.09] setFill];[[NSBezierPath bezierPathWithRoundedRect:r xRadius:4 yRadius:4] fill];}
 NSMutableParagraphStyle *p=[NSMutableParagraphStyle new];p.lineBreakMode=NSLineBreakByTruncatingTail;
 [self.heading drawInRect:NSMakeRect(10,7,NSWidth(r)-20,20) withAttributes:@{NSFontAttributeName:hintFont(14),NSForegroundColorAttributeName:hintInk(),NSParagraphStyleAttributeName:p}];
 [self.detail drawInRect:NSMakeRect(10,29,NSWidth(r)-20,16) withAttributes:@{NSFontAttributeName:hintFont(11),NSForegroundColorAttributeName:[hintInk() colorWithAlphaComponent:0.55],NSParagraphStyleAttributeName:p}];
}
@end
@interface TOTKHintHistoryList:NSView
@end
@implementation TOTKHintHistoryList
-(BOOL)isFlipped{return YES;}
@end
static void hintHistoryShow(NSDictionary *session);
@interface TOTKHintHistoryTarget:NSObject
-(void)open:(TOTKHintHistoryRow *)row;
@end
@implementation TOTKHintHistoryTarget
-(void)open:(TOTKHintHistoryRow *)row{hintHistoryShow(row.session);}
@end
static TOTKHintHistoryTarget *hintHistoryTarget;

/* hintLayout: the list in the text's place while 历史 shows it, the text otherwise. */
static void hintHistoryLayout(CGFloat width){
 NSArray<NSDictionary *> *sessions=hintHistoryExpanded&&!hintHistoryOpen?hintSavedSessions():@[];
 if(!sessions.count){if(hintScroll.documentView!=hintText)hintScroll.documentView=hintText;return;}
 if(!hintHistoryTarget)hintHistoryTarget=[TOTKHintHistoryTarget new];
 if(!hintHistoryList)hintHistoryList=[TOTKHintHistoryList new];
 for(NSView *v in [hintHistoryList.subviews copy])[v removeFromSuperview];
 CGFloat y=0,row=50;
 for(NSDictionary *session in sessions){
  TOTKHintHistoryRow *b=[TOTKHintHistoryRow new];b.bordered=NO;b.title=@"";b.target=hintHistoryTarget;b.action=@selector(open:);
  b.session=session;b.heading=hintHistoryText(session[@"title"]).length?session[@"title"]:@"按进度给的提示";b.detail=hintHistoryDetail(session);
  b.toolTip=b.heading;b.accessibilityLabel=[NSString stringWithFormat:@"%@，%@",b.heading,b.detail];
  b.frame=NSMakeRect(0,y,width,row);[hintHistoryList addSubview:b];y+=row;
 }
 hintHistoryList.frame=NSMakeRect(0,0,width,MAX(y,hintScroll.contentSize.height));
 if(hintScroll.documentView!=hintHistoryList)hintScroll.documentView=hintHistoryList;
}
static void hintHistoryTop(void){[hintScroll.contentView scrollToPoint:NSMakePoint(0,hintScroll.documentView.isFlipped?0:MAX(0,NSHeight(hintScroll.documentView.frame)-hintScroll.contentSize.height))];[hintScroll reflectScrolledClipView:hintScroll.contentView];}
/* The 历史 button: latest reply -> the list -> (a conversation -> back to the list) -> latest reply. */
static void hintHistoryToggle(void){
 if(!hintHistoryExpanded){
  hintHistoryExpanded=YES;hintHistoryOpen=nil;
  if(!hintSavedSessions().count)hintText.stringValue=[hintHistory componentsJoinedByString:@"\n\n"];
  else hintDisclosure.stringValue=@"点一条打开 · 打开后输入问题可以接着聊";
 }else if(hintHistoryOpen){hintHistoryOpen=nil;hintDisclosure.stringValue=@"点一条打开 · 打开后输入问题可以接着聊";}
 else{hintHistoryExpanded=NO;hintText.stringValue=hintDone?hintPageText(hintLatest):hintLatest;}
 hintLayout(0);hintHistoryTop();
}
static void hintHistoryShow(NSDictionary *session){
 hintHistoryOpen=session;hintText.stringValue=hintHistoryTranscript(session);
 hintDisclosure.stringValue=[NSString stringWithFormat:@"%@ · 输入问题接着这次对话聊",hintHistoryDetail(session)];
 hintLayout(0);hintHistoryTop();
}
/* Before a question is sent: when a conversation from 历史 is open, the question goes on with it. */
static void hintHistoryAdopt(void){
 if(!hintHistoryExpanded||!hintHistoryOpen||!hintPendingQuestion.length)return;
 NSString *sid=hintHistoryOpen[@"id"];hintSession=sid.length?sid:nil;[hintHistory removeAllObjects];   // no id: a new conversation
 NSInteger tier=[hintHistoryOpen[@"tier"] isKindOfClass:NSNumber.class]?[hintHistoryOpen[@"tier"] integerValue]:1;hintTier=tier>=1&&tier<=3?tier:1;
 for(NSDictionary *turn in hintHistoryOpen[@"turns"]){   // this run's own list, for the panel's fallback
  if(![turn isKindOfClass:NSDictionary.class])continue;
  if(hintHistoryText(turn[@"question"]).length)[hintHistory addObject:[@"你\n" stringByAppendingString:turn[@"question"]]];
  [hintHistory addObject:[@"露珠\n" stringByAppendingString:hintHistoryText(turn[@"answer"])]];
 }
 hintHistoryOpen=nil;
}
