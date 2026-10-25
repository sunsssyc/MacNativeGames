#define main hint_existing_probe_main
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wreturn-type"
#include "hint_overlay_probe.m"
#pragma clang diagnostic pop
#undef main
static void avatarCapture(TOTKHintAvatar *pet,NSString *path){
 NSBitmapImageRep *rep=[pet bitmapImageRepForCachingDisplayInRect:pet.bounds];
 [pet cacheDisplayInRect:pet.bounds toBitmapImageRep:rep];
 [[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:path atomically:YES];
}
static void avatarTransitionProbe(TOTKHintAvatar *pet){
 NSRect saved=pet.frame;pet.frame=NSMakeRect(0,0,64,64);
 NSImage *(^solid)(NSColor *)=^NSImage *(NSColor *color){
  return [NSImage imageWithSize:NSMakeSize(32,32) flipped:NO drawingHandler:^BOOL(NSRect rect){[color setFill];NSRectFill(rect);return YES;}];
 };
 NSImage *red=solid(NSColor.redColor),*blue=solid(NSColor.blueColor);
 for(int background=0;background<2;background++)for(int step=0;step<=4;step++){
  NSBitmapImageRep *rep=[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:64 pixelsHigh:64 bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:0 bitsPerPixel:0];
  [NSGraphicsContext saveGraphicsState];[NSGraphicsContext setCurrentContext:[NSGraphicsContext graphicsContextWithBitmapImageRep:rep]];
  if(background){[NSColor.greenColor setFill];NSRectFill(NSMakeRect(0,0,64,64));}
  [pet drawTransitionFrom:red source:NSMakeRect(0,0,32,32) to:blue source:NSMakeRect(0,0,32,32) blend:step/4.0];
  [NSGraphicsContext restoreGraphicsState];
  NSColor *c=[[rep colorAtX:32 y:32] colorUsingColorSpace:NSColorSpace.sRGBColorSpace];
  assert(c.alphaComponent>.98);assert(c.greenComponent<.02); // no 75% opacity dip or game-background leak
 }
 pet.frame=saved;
}
int main(int argc,const char **argv){@autoreleasepool{
 assert(argc==2);[NSApplication sharedApplication];
 NSWindow *w=[[NSWindow alloc] initWithContentRect:NSMakeRect(160,180,1000,680) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
 w.title=@"露珠动作验证";[w orderFront:nil];totk_hint_install(w);hintFolder=@(argv[1]);
 TOTKHintAvatar *pet=(TOTKHintAvatar *)hintAvatar;avatarTransitionProbe(pet);
 assert(hintAvatarManifest()[@"clips"]!=nil);
 assert([hintAvatarManifest()[@"clips"] count]==19);
 for(NSString *name in hintAvatarManifest()[@"clips"]){
  NSImage *sheet=hintAvatarSheet(name);assert(sheet);
  NSRect first=[pet sourceForState:name time:0 sheet:sheet],last=[pet sourceForState:name time:100 sheet:sheet];
  assert(first.size.width==192&&first.size.height==288);
  assert(NSContainsRect(NSMakeRect(0,0,sheet.size.width,sheet.size.height),first));
  assert(NSContainsRect(NSMakeRect(0,0,sheet.size.width,sheet.size.height),last));
 }
 pet.motionTime=1;pet.greeting=0;hintWorking=hintDone=hintListening=hintVoiceFinishing=hintRecording=NO;
 assert([[pet desiredMotion] isEqual:@"idle"]);
 fakeActivity=(RuntimePlayerActivity){.valid=1,.active=1,.actor=1,.speed=5};
 hintActivityTracker=(PetActivityTracker){.state=PET_RUN,.pending=PET_RUN,.actor=1,.last=NSProcessInfo.processInfo.systemUptime,.changed=NSProcessInfo.processInfo.systemUptime};hintActivityPoll=hintActivityTracker.last;
 assert([[pet desiredMotion] isEqual:@"run"]);
 hintListening=YES;assert([[pet desiredMotion] isEqual:@"listening"]);hintListening=NO;
 fakeActivity=(RuntimePlayerActivity){0};hintActivityTracker=(PetActivityTracker){0};hintActivityPoll=0;
 hintRecording=YES;assert([[pet desiredMotion] isEqual:@"listening"]);hintRecording=NO;
 hintWorking=YES;assert([[pet desiredMotion] isEqual:@"ponder"]);
 [pet advanceMotion:2];assert([[pet desiredMotion] isEqual:@"thinking"]);
 FakeSpeaker *speaker=[FakeSpeaker new];speaker.talking=YES;hintSpeaker=speaker;
 assert([[pet desiredMotion] isEqual:@"reply"]);
 [pet advanceMotion:5];assert([[pet desiredMotion] isEqual:@"explain"]);
 [pet advanceMotion:5];assert([[pet desiredMotion] isEqual:@"cheerful"]);
 hintRecording=YES;assert([[pet desiredMotion] isEqual:@"listening"]);hintRecording=NO;
 pet.held=YES;assert([[pet desiredMotion] isEqual:@"surprised"]);pet.held=NO;
 speaker.talking=NO;hintWorking=NO;[pet advanceMotion:.1];
 // A busy state interrupts idle variety and restarts its quiet interval.
 [pet advanceMotion:22];assert([[pet desiredMotion] isEqual:@"fidget"]);
 hintWorking=YES;[pet advanceMotion:.1];assert(pet.idleElapsed==0);
 hintWorking=NO;[pet advanceMotion:.1];assert([[pet desiredMotion] isEqual:@"idle"]);
 // Three different idle gestures, with non-uniform quiet intervals.
 for(NSString *expected in @[@"fidget",@"relaxed",@"ponder"]){
  pet.idleElapsed=0;[pet advanceMotion:[pet idleDelay]];
  assert([[pet desiredMotion] isEqual:expected]);
  [pet advanceMotion:hintAvatarDuration(expected)+.01];
  assert([[pet desiredMotion] isEqual:@"idle"]);
 }
 NSEvent *hover=[NSEvent enterExitEventWithType:NSEventTypeMouseEntered location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:w.windowNumber context:nil eventNumber:1 trackingNumber:0 userData:NULL];
 [pet mouseEntered:hover];NSString *firstGreeting=pet.greetingMotion;CGFloat remaining=pet.greeting;
 [pet mouseExited:hover];[pet mouseEntered:hover];assert(pet.greeting==remaining);
 [pet advanceMotion:8.01];[pet mouseEntered:hover];assert(![pet.greetingMotion isEqual:firstGreeting]);
 pet.greeting=0;pet.idleElapsed=0;
 // The displayed animation has actual differing frames, without changing its hit rectangle.
 pet.motionTime=1;pet.motionState=nil;NSRect hit=pet.frame;
 avatarCapture(pet,[@(argv[1]) stringByAppendingPathComponent:@"idle-first.png"]);
 pet.motionTime+=.8;avatarCapture(pet,[@(argv[1]) stringByAppendingPathComponent:@"idle-next.png"]);
 assert(NSEqualRects(hit,pet.frame));
 assert(![[NSData dataWithContentsOfFile:[@(argv[1]) stringByAppendingPathComponent:@"idle-first.png"]] isEqual:[NSData dataWithContentsOfFile:[@(argv[1]) stringByAppendingPathComponent:@"idle-next.png"]]]);
 [pet syncMotion];assert(pet.motionTimer);
 hintExpanded=YES;[pet syncMotion];assert(!pet.motionTimer);
 [hintPanel orderFront:nil];[hintPortrait syncMotion];assert(hintPortrait.portraitMode&&hintPortrait.motionTimer);
 hintWorking=YES;assert([[hintPortrait desiredMotion] isEqual:@"ponder"]);
 [hintPortrait advanceMotion:2];assert([[hintPortrait desiredMotion] isEqual:@"thinking"]);
 [hintPanel orderOut:nil];[hintPortrait syncMotion];assert(!hintPortrait.motionTimer);
 [hintTimer invalidate];[hintDock orderOut:nil];[w orderOut:nil];puts("pass: 19 skeletal clips, constant-opacity crossfades, gesture scheduling/interruption, speech variants, hover cooldown, stationary hit area, portrait and hidden timer lifecycle");
}}
