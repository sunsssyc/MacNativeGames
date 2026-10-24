/* 指给我看: the panel saves the frame it opens on (hint-scene.png) and only then pauses the game, so while it is open the
   window still shows exactly that frame. A question sent with 指给我看 attaches it (tools/hint_assistant/totk_hint/
   scene.py) and the model marks it with circles and arrows (mark_screen); the answer's marks, fractions of the picture,
   are drawn here over the paused window and go when the game moves again. */
extern void dm_gfx_window_shot(const char *path) __attribute__((weak_import));
static BOOL hintPauseHeld;              // the panel holds the game's pause, or is about to once its frame is saved
static BOOL hintSceneReady;             // hint-scene.png is the frame on screen
static BOOL hintPointNext;              // the next request is a 指给我看
static NSUInteger hintShotGeneration;
static NSButton *hintPointButton;
static NSPanel *hintMarksWindow;
static NSArray<NSDictionary *> *hintMarks;

static BOOL hintSceneSaved(NSString *path){   // the whole PNG is there: it ends in its IEND chunk
 NSFileHandle *file=[NSFileHandle fileHandleForReadingAtPath:path];
 unsigned long long end=[file seekToEndOfFile];
 if(end<12){[file closeFile];return NO;}
 [file seekToFileOffset:end-12];NSData *tail=[file readDataOfLength:12];[file closeFile];
 return tail.length==12&&!memcmp((const char *)tail.bytes+4,"IEND",4);
}
static void hintPauseWhenSaved(NSUInteger generation,NSDate *asked){
 if(generation!=hintShotGeneration||!hintPauseHeld)return;   // the panel closed meanwhile
 BOOL saved=hintSceneSaved(hintPath(@"hint-scene.png"));
 if(!saved&&-asked.timeIntervalSinceNow<0.6){   // no new frame (covered window, loading): pause without one
  dispatch_after(dispatch_time(DISPATCH_TIME_NOW,30*NSEC_PER_MSEC),dispatch_get_main_queue(),^{hintPauseWhenSaved(generation,asked);});
  return;
 }
 hintSceneReady=saved;
 if(runtime_assistant_pause)runtime_assistant_pause(1);
 hintLayout(0);
 // A 指给我看 asked before the panel captured anything waits here: the frame is on screen now, send it.
 if(hintPointNext&&hintPendingQuestion.length)[hintActions request:nil];
}
static void hintPause(void){   // the game stops behind the panel, on a frame that 指给我看 can show the model
 if(hintPauseHeld)return;
 hintPauseHeld=YES;hintSceneReady=NO;
 NSUInteger generation=++hintShotGeneration;
 if(!dm_gfx_window_shot||!hintGame.visible){if(runtime_assistant_pause)runtime_assistant_pause(1);return;}
 NSString *scene=hintPath(@"hint-scene.png");
 [NSFileManager.defaultManager createDirectoryAtPath:hintFolder withIntermediateDirectories:YES attributes:nil error:nil];
 [NSFileManager.defaultManager removeItemAtPath:scene error:nil];
 dm_gfx_window_shot(scene.fileSystemRepresentation);   // the next frame; the game runs on until it is saved
 hintPauseWhenSaved(generation,NSDate.date);
}

// marks -----------------------------------------------------------------------------------------------------------------
static NSPoint hintMarkPoint(NSArray *at,NSRect r){   // a fraction of the picture, from its top left
 return NSMakePoint(NSMinX(r)+[at[0] doubleValue]*NSWidth(r),NSMaxY(r)-[at[1] doubleValue]*NSHeight(r));
}
static void hintMarkStroke(NSBezierPath *path){   // dark under orange, readable on bright and dark scenes alike
 [[NSColor colorWithWhite:0 alpha:0.55] setStroke];path.lineWidth=7;[path stroke];
 [hintAccent() setStroke];path.lineWidth=3.5;[path stroke];
}
@interface TOTKHintMarks:NSView
@end
@implementation TOTKHintMarks
-(void)drawRect:(NSRect)dirty{
 (void)dirty;NSRect r=self.bounds;CGFloat radius=MAX(26,0.045*MIN(NSWidth(r),NSHeight(r)));
 NSArray *numbers=@[@"①",@"②",@"③",@"④"];NSUInteger n=0;
 for(NSDictionary *mark in hintMarks){
  NSPoint at=hintMarkPoint(mark[@"at"],r),labelAt=at;
  if([mark[@"kind"] isEqual:@"arrow"]&&[mark[@"to"] isKindOfClass:NSArray.class]){
   NSPoint to=hintMarkPoint(mark[@"to"],r);CGFloat angle=atan2(to.y-at.y,to.x-at.x),head=MAX(16,radius*0.6);
   NSBezierPath *line=[NSBezierPath bezierPath];line.lineCapStyle=NSLineCapStyleRound;line.lineJoinStyle=NSLineJoinStyleRound;
   [line moveToPoint:at];[line lineToPoint:to];
   [line moveToPoint:NSMakePoint(to.x-head*cos(angle-0.45),to.y-head*sin(angle-0.45))];[line lineToPoint:to];
   [line lineToPoint:NSMakePoint(to.x-head*cos(angle+0.45),to.y-head*sin(angle+0.45))];
   hintMarkStroke(line);
  }else{
   hintMarkStroke([NSBezierPath bezierPathWithOvalInRect:NSMakeRect(at.x-radius,at.y-radius,2*radius,2*radius)]);
   labelAt.y+=radius;
  }
  NSString *label=[NSString stringWithFormat:@"%@ %@",hintMarks.count>1?numbers[MIN(n,numbers.count-1)]:@"",mark[@"label"]];
  label=[label stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];n++;
  NSDictionary *a=@{NSFontAttributeName:hintFont(16),NSForegroundColorAttributeName:hintInk()};
  NSSize size=[label sizeWithAttributes:a];
  NSRect box=NSMakeRect(labelAt.x-size.width/2-10,labelAt.y+8,size.width+20,size.height+8);
  box.origin.x=MIN(MAX(NSMinX(r)+6,box.origin.x),NSMaxX(r)-NSWidth(box)-6);
  box.origin.y=MIN(MAX(NSMinY(r)+6,box.origin.y),NSMaxY(r)-NSHeight(box)-6);
  [[hintSurface() colorWithAlphaComponent:0.88] setFill];[[NSBezierPath bezierPathWithRoundedRect:box xRadius:6 yRadius:6] fill];
  [label drawAtPoint:NSMakePoint(NSMinX(box)+10,NSMinY(box)+4) withAttributes:a];
 }
}
@end
static void hintMarksHide(void){hintMarks=nil;if(hintMarksWindow.visible)[hintMarksWindow orderOut:nil];}
static void hintMarksShow(NSArray *marks){   // over the paused game window, under the panel
 NSMutableArray<NSDictionary *> *kept=[NSMutableArray new];
 for(NSDictionary *mark in [marks isKindOfClass:NSArray.class]?marks:@[]){
  BOOL ok=[mark isKindOfClass:NSDictionary.class]&&[mark[@"label"] isKindOfClass:NSString.class]&&[mark[@"at"] isKindOfClass:NSArray.class]&&[mark[@"at"] count]==2;
  if(ok&&kept.count<4)[kept addObject:mark];
 }
 if(!kept.count||!hintSceneReady){hintMarksHide();return;}
 hintMarks=kept;
 if(!hintMarksWindow){
  hintMarksWindow=[[NSPanel alloc] initWithContentRect:NSZeroRect styleMask:NSWindowStyleMaskBorderless|NSWindowStyleMaskNonactivatingPanel backing:NSBackingStoreBuffered defer:NO];
  hintMarksWindow.backgroundColor=NSColor.clearColor;hintMarksWindow.opaque=NO;hintMarksWindow.hasShadow=NO;hintMarksWindow.ignoresMouseEvents=YES;
  hintMarksWindow.contentView=[TOTKHintMarks new];
 }
 [hintMarksWindow setFrame:[hintGame convertRectToScreen:hintGame.contentView.bounds] display:YES];
 hintMarksWindow.contentView.needsDisplay=YES;
 [hintGame addChildWindow:hintMarksWindow ordered:NSWindowAbove];[hintMarksWindow orderFront:nil];
 if(hintPanel.visible)[hintPanel orderFront:nil];
}
static void hintResume(void){   // the game moves on: the frame and its marks are gone
 BOOL held=hintPauseHeld;
 hintPauseHeld=NO;hintSceneReady=NO;hintShotGeneration++;hintMarksHide();
 if(held&&runtime_assistant_pause)runtime_assistant_pause(0);   // never release a pause this panel does not hold
}
