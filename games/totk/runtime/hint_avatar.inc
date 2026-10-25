#include "companion_activity.h"
extern int runtime_live_activity(RuntimePlayerActivity *out) __attribute__((weak_import));
// Transparent frames rendered from the skinned Riju model; no per-frame 3D renderer in the game.
// All frames share a camera/foot anchor, so animation never moves the click target or saved dock position.
// A shared, bounded 30 Hz read for dock and portrait. No model calls, screenshots or actor-table scan.
static PetActivityTracker hintActivityTracker;
static NSTimeInterval hintActivityPoll;
static NSString *hintActivityMotion(void){
 NSTimeInterval now=NSProcessInfo.processInfo.systemUptime;
 if(now-hintActivityPoll>=1.0/30){
  RuntimePlayerActivity a={0};if(runtime_live_activity)runtime_live_activity(&a);
  pet_activity_update(&hintActivityTracker,&a,now,now);hintActivityPoll=now;
 }
 PetActivity state=hintActivityTracker.state;
 // The airborne pose also covers gliding until a dedicated parasail clip is authored.
 if(state==PET_CLIMB)return @"climb"; // stable neutral visual until a matching climb clip exists
 return state==PET_GLIDE?@"fall":@(pet_activity_name(state));
}
static BOOL hintAvatarIsSpeaking(void);
static NSDictionary *hintAvatarManifest(void){
 static NSDictionary *manifest;static dispatch_once_t once;
 dispatch_once(&once,^{
  NSDictionary *m=hintJSON(@"runtime/assets/riju-actions/manifest.json");
  if([m[@"version"] integerValue]==1&&[m[@"width"] integerValue]>0&&[m[@"height"] integerValue]>0&&[m[@"columns"] integerValue]>0)
   manifest=m;
 });return manifest;
}
static NSImage *hintAvatarSheet(NSString *name){
 static NSCache *cache;static dispatch_once_t once;
 dispatch_once(&once,^{cache=[NSCache new];cache.totalCostLimit=48*1024*1024;});
 NSImage *im=[cache objectForKey:name];if(im)return im;
 NSDictionary *clip=hintAvatarManifest()[@"clips"][name];NSString *file=clip[@"file"];
 if(![file isKindOfClass:NSString.class]||![file.lastPathComponent isEqual:file])return nil;
 im=[[NSImage alloc] initWithContentsOfFile:[@"runtime/assets/riju-actions" stringByAppendingPathComponent:file]];
 if(im)[cache setObject:im forKey:name cost:(NSUInteger)(im.size.width*im.size.height*4)];return im;
}
static NSTimeInterval hintAvatarDuration(NSString *name){
 NSDictionary *clip=hintAvatarManifest()[@"clips"][name];double fps=[clip[@"fps"] doubleValue];
 return fps>0?MAX(.1,[clip[@"frames"] doubleValue]/fps):1.2;
}
@interface TOTKHintAvatar:NSButton
@property NSTimer *motionTimer;
@property NSTrackingArea *hoverArea;
@property BOOL hovered,held,moving,wasDone,portraitMode;
@property CGFloat motionTime,greeting,landing;
@property NSTimeInterval idleElapsed,speakingTime,workingTime,lastGreetingTime;
@property NSUInteger idleCycle,greetingCycle;
@property BOOL hasGreeted;
@property NSString *greetingMotion;
@property NSTimeInterval lastTick,clipStart,transitionStart,transitionDuration;
@property NSTimeInterval attackStarted;
@property NSString *motionState;
@property NSImage *previousSheet;
@property NSRect previousSource;
-(void)syncMotion;
-(NSString *)desiredMotion;
-(void)advanceMotion:(NSTimeInterval)dt;
-(NSString *)idleGesture;
-(NSTimeInterval)idleDelay;
-(void)greetWithMotion:(NSString *)name;
-(NSRect)sourceForState:(NSString *)state time:(NSTimeInterval)time sheet:(NSImage *)sheet;
@end
@implementation TOTKHintAvatar
-(BOOL)acceptsFirstResponder{return NO;}
-(BOOL)acceptsFirstMouse:(NSEvent *)event{(void)event;return YES;}
-(void)updateTrackingAreas{
 [super updateTrackingAreas];if(self.hoverArea)[self removeTrackingArea:self.hoverArea];
 self.hoverArea=[[NSTrackingArea alloc] initWithRect:NSZeroRect options:NSTrackingMouseEnteredAndExited|NSTrackingActiveAlways|NSTrackingInVisibleRect owner:self userInfo:nil];[self addTrackingArea:self.hoverArea];
}
-(void)greetWithMotion:(NSString *)name{
 self.greetingMotion=name;self.greeting=hintAvatarDuration(name);
 self.lastGreetingTime=self.motionTime;self.hasGreeted=YES;self.needsDisplay=YES;
}
-(void)mouseEntered:(NSEvent *)event{
 (void)event;self.hovered=YES;
 // Re-entering the hit target must not continually restart the gesture.
 if(!self.hasGreeted||self.motionTime-self.lastGreetingTime>=8){
  [self greetWithMotion:self.greetingCycle++%2?@"welcome":@"greeting"];
 }
}
-(void)mouseExited:(NSEvent *)event{(void)event;self.hovered=NO;}
-(void)mouseDown:(NSEvent *)event{if(self.portraitMode)return;self.held=YES;self.moving=NO;hintDragBegin(event);}
-(void)mouseDragged:(NSEvent *)event{if(self.portraitMode)return;self.moving=YES;hintDragMove(event);}
-(void)mouseUp:(NSEvent *)event{if(self.portraitMode)return;self.held=self.moving=NO;[self greetWithMotion:@"welcome"];hintDragEnd(event);}
-(NSString *)idleGesture{return @[@"fidget",@"relaxed",@"ponder"][self.idleCycle%3];}
-(NSTimeInterval)idleDelay{return [@[@22,@28,@24,@32][self.idleCycle%4] doubleValue];}
-(void)advanceMotion:(NSTimeInterval)dt{
 self.motionTime+=dt;self.greeting=MAX(0,self.greeting-dt);
 BOOL speaking=hintAvatarIsSpeaking();
 self.speakingTime=speaking?self.speakingTime+dt:0;
 self.workingTime=(hintWorking||hintVoiceFinishing)?self.workingTime+dt:0;
 if(self.held||hintListening||hintRecording||speaking||hintWorking||hintVoiceFinishing||self.greeting>0){
  self.idleElapsed=0;
 }else{
  self.idleElapsed+=dt;
  if(self.idleElapsed>=[self idleDelay]+hintAvatarDuration([self idleGesture])){
   self.idleElapsed=0;self.idleCycle++;
  }
 }
}
-(NSString *)desiredMotion{
 if(NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion)return @"idle";
 if(self.held)return @"surprised";
 if(hintListening||hintRecording)return @"listening";
 if(hintAvatarIsSpeaking())return @[@"reply",@"explain",@"cheerful"][(NSUInteger)(self.speakingTime/5)%3];
 // Enter the held thinking pose before ponder's return-to-idle tail.
 if(hintWorking||hintVoiceFinishing)return self.workingTime<MAX(.1,hintAvatarDuration(@"ponder")-.27)?@"ponder":@"thinking";
 if(self.greeting>0)return self.greetingMotion?:@"greeting";
 if(hintExpanded)return @"listening"; // stay present with the conversation, not the player's combat
 NSString *activity=hintActivityMotion();
 if([activity isEqual:@"climb"]){self.idleElapsed=0;return @"idle";}
 if(![activity isEqual:@"idle"]){self.idleElapsed=0;return activity;}
 if(self.idleElapsed>=[self idleDelay])return [self idleGesture];
 return @"idle";
}
-(void)syncMotion{
 BOOL active=self.window.visible&&!self.hidden&&!NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion;
 if(!active){[self.motionTimer invalidate];self.motionTimer=nil;self.lastTick=0;self.needsDisplay=YES;return;}
 if(hintDone&&!self.wasDone)[self greetWithMotion:@"welcome"];self.wasDone=hintDone;
 if(self.motionTimer)return;
 self.lastTick=NSProcessInfo.processInfo.systemUptime;
 __weak TOTKHintAvatar *weakSelf=self;
 self.motionTimer=[NSTimer timerWithTimeInterval:1.0/30 repeats:YES block:^(NSTimer *timer){
  TOTKHintAvatar *pet=weakSelf;if(!pet){[timer invalidate];return;}
  if(!pet.window.visible||pet.hidden||NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion){[pet syncMotion];return;}
  NSTimeInterval now=NSProcessInfo.processInfo.systemUptime,dt=MIN(.1,MAX(0,now-pet.lastTick));pet.lastTick=now;
  [pet advanceMotion:dt];pet.needsDisplay=YES;
 }];[NSRunLoop.mainRunLoop addTimer:self.motionTimer forMode:NSRunLoopCommonModes];
}
-(void)viewWillMoveToWindow:(NSWindow *)window{
 if(!window){[self.motionTimer invalidate];self.motionTimer=nil;}[super viewWillMoveToWindow:window];
}
-(NSRect)sourceForState:(NSString *)state time:(NSTimeInterval)time sheet:(NSImage *)sheet{
 NSDictionary *m=hintAvatarManifest(),*clip=m[@"clips"][state];
 NSInteger w=[m[@"width"] integerValue],h=[m[@"height"] integerValue],cols=[m[@"columns"] integerValue];
 NSInteger bodyWidth=w;
 if(clip[@"width"])w=[clip[@"width"] integerValue];
 NSInteger count=[clip[@"frames"] integerValue],fps=[clip[@"fps"] integerValue];
 if(w<1||h<1||cols<1||count<1||count>256||fps<1||fps>30||sheet.size.width<cols*w||sheet.size.height<((count+cols-1)/cols)*h)return NSZeroRect;
 double playbackFPS=[state isEqual:@"land"]?count/PET_LAND_SECONDS:fps;
 NSInteger frame=(NSInteger)(MAX(0,time)*playbackFPS);
 frame=[clip[@"loop"] boolValue]?frame%count:MIN(count-1,frame);
 if(self.held)frame=MIN(count-1,8);
 if(NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion)frame=0;
 NSRect r=NSMakeRect((frame%cols)*w,sheet.size.height-(frame/cols+1)*h,w,h);
 // The panel header uses a face crop from the same animated model, not the old illustration.
 if(self.portraitMode){r.origin.x+=(w-bodyWidth)*.5+bodyWidth*.22;r.origin.y+=h*.63;r.size=NSMakeSize(bodyWidth*.56,h*.34);}
 return r;
}
-(void)drawSheet:(NSImage *)sheet source:(NSRect)source alpha:(CGFloat)alpha operation:(NSCompositingOperation)operation{
 if(NSIsEmptyRect(source))return;
 NSRect area=NSInsetRect(self.bounds,2,2);CGFloat scale=MIN(area.size.width/(self.portraitMode?source.size.width:MAX(256,source.size.width)),area.size.height/source.size.height);
 NSRect target=NSMakeRect(NSMidX(area)-source.size.width*scale/2,NSMidY(area)-source.size.height*scale/2,source.size.width*scale,source.size.height*scale);
 [sheet drawInRect:target fromRect:source operation:operation fraction:alpha respectFlipped:YES hints:@{NSImageHintInterpolation:@(NSImageInterpolationHigh)}];
}
// Weighted premultiplied colors must be added in an isolated transparent layer.
// Two source-over draws at 50% only produce 75% alpha, making the pet flash translucent.
-(void)drawTransitionFrom:(NSImage *)old source:(NSRect)oldSource to:(NSImage *)next source:(NSRect)nextSource blend:(CGFloat)blend{
 CGContextRef context=NSGraphicsContext.currentContext.CGContext;
 CGContextSaveGState(context);CGContextBeginTransparencyLayer(context,NULL);
 [self drawSheet:old source:oldSource alpha:1-blend operation:NSCompositingOperationSourceOver];
 [self drawSheet:next source:nextSource alpha:blend operation:NSCompositingOperationPlusLighter];
 CGContextEndTransparencyLayer(context);CGContextRestoreGState(context);
}
-(void)drawRect:(NSRect)dirty{
 (void)dirty;NSString *state=[self desiredMotion];NSImage *sheet=hintAvatarSheet(state);
 if(!sheet){state=@"idle";sheet=hintAvatarSheet(state);}
 if(!sheet){if(self.image)[self drawSheet:self.image source:NSMakeRect(0,0,self.image.size.width,self.image.size.height) alpha:1 operation:NSCompositingOperationSourceOver];return;}
 BOOL newStrike=[state isEqual:@"attack"]&&self.attackStarted!=hintActivityTracker.attack_started;
 if(![state isEqual:self.motionState]||newStrike){
  self.previousSheet=hintAvatarSheet(self.motionState?:@"idle");
  self.previousSource=[self sourceForState:self.motionState?:@"idle" time:self.motionTime-self.clipStart sheet:self.previousSheet];
  NSSet *airClips=[NSSet setWithObjects:@"jump",@"fall",@"land",@"attack",nil];
  self.transitionDuration=([airClips containsObject:state]||[airClips containsObject:self.motionState?:@""])? .05:.16;
  self.motionState=state;self.clipStart=self.motionTime;self.transitionStart=self.motionTime;
  self.attackStarted=hintActivityTracker.attack_started;
 }
 CGFloat blend=MIN(1,MAX(0,(self.motionTime-self.transitionStart)/MAX(.01,self.transitionDuration)));
 if(NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion||!self.previousSheet)blend=1;
 NSRect source=[self sourceForState:state time:self.motionTime-self.clipStart sheet:sheet];
 if(blend<1)[self drawTransitionFrom:self.previousSheet source:self.previousSource to:sheet source:source blend:blend];
 else{self.previousSheet=nil;[self drawSheet:sheet source:source alpha:1 operation:NSCompositingOperationSourceOver];}
}
@end
