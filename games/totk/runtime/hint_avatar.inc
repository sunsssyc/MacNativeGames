// Transparent frames rendered from the skinned Riju model; no per-frame 3D renderer in the game.
// All frames share a camera/foot anchor, so animation never moves the click target or saved dock position.
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
@property NSTimeInterval lastTick,clipStart,transitionStart;
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
 if(self.idleElapsed>=[self idleDelay])return [self idleGesture];
 return @"idle";
}
-(void)syncMotion{
 BOOL active=self.window.visible&&!self.hidden&&(self.portraitMode?hintExpanded:!hintExpanded)&&!NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion;
 if(!active){[self.motionTimer invalidate];self.motionTimer=nil;self.lastTick=0;self.needsDisplay=YES;return;}
 if(hintDone&&!self.wasDone)[self greetWithMotion:@"welcome"];self.wasDone=hintDone;
 if(self.motionTimer)return;
 self.lastTick=NSProcessInfo.processInfo.systemUptime;
 __weak TOTKHintAvatar *weakSelf=self;
 self.motionTimer=[NSTimer timerWithTimeInterval:1.0/30 repeats:YES block:^(NSTimer *timer){
  TOTKHintAvatar *pet=weakSelf;if(!pet){[timer invalidate];return;}
  if(!pet.window.visible||pet.hidden||(pet.portraitMode?!hintExpanded:hintExpanded)||NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion){[pet syncMotion];return;}
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
 NSInteger count=[clip[@"frames"] integerValue],fps=[clip[@"fps"] integerValue];
 if(w<1||h<1||cols<1||count<1||count>256||fps<1||fps>30||sheet.size.width<cols*w||sheet.size.height<((count+cols-1)/cols)*h)return NSZeroRect;
 NSInteger frame=(NSInteger)(MAX(0,time)*fps);
 frame=[clip[@"loop"] boolValue]?frame%count:MIN(count-1,frame);
 if(self.held)frame=MIN(count-1,8);
 if(NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion)frame=0;
 NSRect r=NSMakeRect((frame%cols)*w,sheet.size.height-(frame/cols+1)*h,w,h);
 // The panel header uses a face crop from the same animated model, not the old illustration.
 if(self.portraitMode){r.origin.x+=w*.22;r.origin.y+=h*.63;r.size=NSMakeSize(w*.56,h*.34);}
 return r;
}
-(void)drawSheet:(NSImage *)sheet source:(NSRect)source alpha:(CGFloat)alpha{
 if(NSIsEmptyRect(source))return;
 NSRect area=NSInsetRect(self.bounds,2,2);CGFloat scale=MIN(area.size.width/source.size.width,area.size.height/source.size.height);
 NSRect target=NSMakeRect(NSMidX(area)-source.size.width*scale/2,NSMidY(area)-source.size.height*scale/2,source.size.width*scale,source.size.height*scale);
 [sheet drawInRect:target fromRect:source operation:NSCompositingOperationSourceOver fraction:alpha respectFlipped:YES hints:@{NSImageHintInterpolation:@(NSImageInterpolationHigh)}];
}
-(void)drawRect:(NSRect)dirty{
 (void)dirty;NSString *state=[self desiredMotion];NSImage *sheet=hintAvatarSheet(state);
 if(!sheet){state=@"idle";sheet=hintAvatarSheet(state);}
 if(!sheet){if(self.image)[self drawSheet:self.image source:NSMakeRect(0,0,self.image.size.width,self.image.size.height) alpha:1];return;}
 if(![state isEqual:self.motionState]){
  self.previousSheet=hintAvatarSheet(self.motionState?:@"idle");
  self.previousSource=[self sourceForState:self.motionState?:@"idle" time:self.motionTime-self.clipStart sheet:self.previousSheet];
  self.motionState=state;self.clipStart=self.motionTime;self.transitionStart=self.motionTime;
 }
 CGFloat blend=MIN(1,MAX(0,(self.motionTime-self.transitionStart)/.16));
 if(NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion||!self.previousSheet)blend=1;
 if(blend<1)[self drawSheet:self.previousSheet source:self.previousSource alpha:1-blend];else self.previousSheet=nil;
 [self drawSheet:sheet source:[self sourceForState:state time:self.motionTime-self.clipStart sheet:sheet] alpha:blend];
}
@end
