/* 指路: the service answers with the nearest visible target of an active quest (no model, no screenshot); the arrow
   turns with the player camera and the distance updates while the game runs, so the panel can be closed and Link walks
   on with the arrow on screen. Its own files, guide-request.json / guide-response.json, keep it out of the hint session.
   The target is a map position from the save; the bearing comes from the live camera (world_survey.c), with the
   player's facing as the fallback when the camera cannot be read. */
#include <math.h>
extern int runtime_live_player(float xyz[3]) __attribute__((weak_import));
extern int runtime_live_facing(float player_rot[9], float camera_rot[9], float camera_pos[3]) __attribute__((weak_import));
static NSPanel *hintGuidePanel;
static NSArray *hintGuideTarget;      // xyz of the target, in world metres
static NSString *hintGuideLabel, *hintGuideID;
static double hintGuideAngle, hintGuideDistance;
static NSDate *hintGuideExpiry;

/* Degrees clockwise from north (north is -z on the map), the same convention as harness.relation. */
static double hintGuideHeading(double x, double z) { return atan2(x, -z) * 180.0 / M_PI; }
static NSString *hintGuideDistanceText(double meters) {
 if (meters < 1000) return [NSString stringWithFormat:@"%.0f 米", meters];
 return [NSString stringWithFormat:@"%.1f 公里", meters / 1000];
}
@interface TOTKHintGuide:NSView
@end
@implementation TOTKHintGuide
-(void)drawRect:(NSRect)dirty{
 (void)dirty;NSRect r=self.bounds;
 [[hintSurface() colorWithAlphaComponent:0.9] setFill];
 [[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(r,1,1) xRadius:9 yRadius:9] fill];
 [[hintInk() colorWithAlphaComponent:0.28] setStroke];
 NSBezierPath *border=[NSBezierPath bezierPathWithRoundedRect:NSInsetRect(r,1,1) xRadius:9 yRadius:9];border.lineWidth=0.7;[border stroke];
 NSPoint center=NSMakePoint(56,NSMidY(r));CGFloat radius=34;
 [[hintInk() colorWithAlphaComponent:0.25] setStroke];
 NSBezierPath *ring=[NSBezierPath bezierPathWithOvalInRect:NSMakeRect(center.x-radius,center.y-radius,radius*2,radius*2)];
 ring.lineWidth=1;[ring stroke];
 // 12 dim ticks, so the ring reads as a compass even when the arrow sits still.
 for(int i=0;i<12;i++){
  CGFloat a=i*M_PI/6;NSBezierPath *tick=[NSBezierPath bezierPath];
  [tick moveToPoint:NSMakePoint(center.x+cos(a)*(radius-5),center.y+sin(a)*(radius-5))];
  [tick lineToPoint:NSMakePoint(center.x+cos(a)*radius,center.y+sin(a)*radius)];
  tick.lineWidth=1;[tick stroke];
 }
 // The arrow points up when the target is straight ahead; relative is clockwise, and AppKit turns counter-clockwise.
 NSAffineTransform *turn=[NSAffineTransform transform];
 [turn translateXBy:center.x yBy:center.y];[turn rotateByDegrees:-hintGuideAngle];
 NSBezierPath *arrow=[NSBezierPath bezierPath];
 [arrow moveToPoint:NSMakePoint(0,radius-9)];
 [arrow lineToPoint:NSMakePoint(12,-3)];
 [arrow lineToPoint:NSMakePoint(0,2)];
 [arrow lineToPoint:NSMakePoint(-12,-3)];
 [arrow closePath];[arrow transformUsingAffineTransform:turn];
 [hintAccent() setFill];[arrow fill];
 NSMutableParagraphStyle *tight=[NSMutableParagraphStyle new];tight.lineBreakMode=NSLineBreakByTruncatingTail;
 NSDictionary *small=@{NSFontAttributeName:hintFont(12),NSForegroundColorAttributeName:[hintInk() colorWithAlphaComponent:0.72],NSParagraphStyleAttributeName:tight};
 NSDictionary *big=@{NSFontAttributeName:hintFont(21),NSForegroundColorAttributeName:hintInk()};
 NSDictionary *name=@{NSFontAttributeName:hintFont(13),NSForegroundColorAttributeName:hintInk(),NSParagraphStyleAttributeName:tight};
 [@"露珠指路" drawInRect:NSMakeRect(108,NSHeight(r)-30,112,16) withAttributes:small];
 [(hintGuideLabel ?: @"目标") drawInRect:NSMakeRect(108,NSHeight(r)-54,112,18) withAttributes:name];
 [hintGuideDistanceText(hintGuideDistance) drawInRect:NSMakeRect(106,NSHeight(r)-86,120,26) withAttributes:big];
 [@"跟着箭头走" drawInRect:NSMakeRect(108,14,112,16) withAttributes:small];
}
@end
static void hintGuideHide(void){
 hintGuideTarget=nil;hintGuideLabel=nil;hintGuideID=nil;hintGuideDistance=0;
 if(hintGuidePanel.visible)[hintGuidePanel orderOut:nil];
}
static void hintGuideLayout(void){
 if(!hintGuideTarget)return;
 NSRect g=[hintGame convertRectToScreen:hintGame.contentView.bounds];
 NSRect f=NSMakeRect(NSMidX(g)-116,NSMaxY(g)-152,232,116);   // top centre: clear of the hearts and the minimap
 if(!NSEqualRects(f,hintGuidePanel.frame))[hintGuidePanel setFrame:f display:YES];
 if(!hintGuidePanel.visible){[hintGame addChildWindow:hintGuidePanel ordered:NSWindowAbove];[hintGuidePanel orderFront:nil];}
 hintGuidePanel.contentView.needsDisplay=YES;
}
// A new request for the same target is answered by the service from the newest save; nothing is sent to a model.
static void hintGuideAsk(void){
 if(!hintStart())return;
 hintGuideID=NSUUID.UUID.UUIDString;
 NSData *data=[NSJSONSerialization dataWithJSONObject:@{@"id":hintGuideID,@"time":@(NSDate.date.timeIntervalSince1970)}
                                              options:0 error:nil];
 if(!data||![data writeToFile:hintPath(@"guide-request.json") options:NSDataWritingAtomic error:nil]){
  hintDisclosure.stringValue=@"暂时无法写入指路请求。";return;
 }
 hintDisclosure.stringValue=@"正在找当前任务里最近的目标…";
}
static void hintGuidePoll(void){
 if(!hintGuideID)return;
 NSDictionary *answer=hintJSON(hintPath(@"guide-response.json"));
 if(![answer[@"id"] isEqual:hintGuideID])return;
 hintGuideID=nil;
 NSDictionary *target=answer[@"target"];
 if(![answer[@"ok"] boolValue]||![target isKindOfClass:NSDictionary.class]||![target[@"xyz"] isKindOfClass:NSArray.class]){
  hintDisclosure.stringValue=[answer[@"error"] isKindOfClass:NSString.class]?answer[@"error"]
   :@"没有找到可以指路的目标 · 换一个任务或先推进剧情";
  return;
 }
 hintGuideTarget=target[@"xyz"];hintGuideLabel=target[@"name"];
 hintGuideDistance=[target[@"distance_m"] doubleValue];
 hintGuideExpiry=[NSDate dateWithTimeIntervalSinceNow:900];   // 15 minutes, then the arrow steps out of the way
 hintGuideLayout();
 hintDisclosure.stringValue=@"已指路 · 收起面板，跟着箭头走";
}
static void hintGuideTick(void){
 if(!hintGuidePanel.visible||!hintGuideTarget)return;
 if(hintGuideExpiry&&hintGuideExpiry.timeIntervalSinceNow<=0){hintGuideHide();return;}
 float pos[3]={0},rot[9]={0},cam[9]={0},campos[3]={0};
 if(!runtime_live_player||runtime_live_player(pos)!=1)return;
 if(!runtime_live_facing)return;
 int got=runtime_live_facing(rot,cam,campos);
 if(!(got&1))return;
 double dx=[hintGuideTarget[0] doubleValue]-pos[0],dz=[hintGuideTarget[2] doubleValue]-pos[2];
 hintGuideDistance=hypot(dx,dz);
 if(hintGuideDistance<12){hintGuideHide();return;}   // close enough: nothing left to point at
 double bearing=hintGuideHeading(dx,dz);
 double facing;
 if(got&2){
  // The third column of the camera's rotation, with the sign the geometry decides: the camera always frames Link, so
  // the direction from the camera to the player is the way it looks. This keeps the arrow right whichever way the
  // game stores the camera's forward axis.
  double fx=-cam[2],fz=-cam[8],tx=pos[0]-campos[0],tz=pos[2]-campos[2];
  if(fx*tx+fz*tz<0){fx=-fx;fz=-fz;}
  facing=hintGuideHeading(fx,fz);
 }else facing=hintGuideHeading(rot[2],-rot[8]);   // no camera: Link's own facing
 hintGuideAngle=fmod(bearing-facing+540,360)-180;
 hintGuidePanel.contentView.needsDisplay=YES;
}
