/* The panel's place and size, the player's: drag its header to move it, a lower corner (the grips drawn there) to resize
   it, double-click the header to go back to the automatic size and place. Kept in hint-panel.json next to the game's
   other files, as fractions of where it can go in the game window (like the companion's companion-position.json), so it
   survives a window resize; a size larger than the window shrinks to fit. Until the player sets them, hintLayout sizes
   the panel to its text and places it on the right. While 指给我看 marks would be under it (hintPanelLeft), the panel
   keeps its size but goes to the automatic left place. A taller panel than the automatic one shows an answer whole
   (hintPageLines) instead of three lines at a time. */
static void hintLayout(CGFloat height);
enum { HINT_GRIP=18, HINT_HEADER=62, HINT_MIN_W=320, HINT_MIN_H=248 };
static BOOL hintPanelLoaded, hintPanelSized, hintPanelPlaced;
static NSSize hintPanelSize;
static NSPoint hintPanelPosition;   // fractions of hintPanelTravel
static int hintPanelGrab;           // 0 none, 1 move, 2 resize from the lower left corner, 3 from the lower right
static NSPoint hintPanelGrabPointer;
static NSRect hintPanelGrabFrame;

static NSRect hintPanelTravel(NSSize size){   // where the panel's origin can go: inside the game window, 12 pt in
 NSRect r=[hintGame convertRectToScreen:hintGame.contentView.bounds];
 return NSMakeRect(NSMinX(r)+12,NSMinY(r)+12,MAX(0,NSWidth(r)-size.width-24),MAX(0,NSHeight(r)-size.height-24));
}
static void hintPanelLoad(void){
 if(hintPanelLoaded)return;
 hintPanelLoaded=YES;
 NSDictionary *p=hintJSON(hintPath(@"hint-panel.json"));
 double x=[p[@"x"] isKindOfClass:NSNumber.class]?[p[@"x"] doubleValue]:NAN,y=[p[@"y"] isKindOfClass:NSNumber.class]?[p[@"y"] doubleValue]:NAN;
 double w=[p[@"w"] isKindOfClass:NSNumber.class]?[p[@"w"] doubleValue]:NAN,h=[p[@"h"] isKindOfClass:NSNumber.class]?[p[@"h"] doubleValue]:NAN;
 if(isfinite(x)&&isfinite(y)){hintPanelPosition=NSMakePoint(MAX(0,MIN(1,x)),MAX(0,MIN(1,y)));hintPanelPlaced=YES;}
 if(isfinite(w)&&isfinite(h)&&w>=HINT_MIN_W&&h>=HINT_MIN_H){hintPanelSize=NSMakeSize(w,h);hintPanelSized=YES;}
}
static void hintPanelSave(void){
 NSMutableDictionary *p=[NSMutableDictionary dictionary];
 if(hintPanelPlaced){p[@"x"]=@(hintPanelPosition.x);p[@"y"]=@(hintPanelPosition.y);}
 if(hintPanelSized){p[@"w"]=@(round(hintPanelSize.width));p[@"h"]=@(round(hintPanelSize.height));}
 NSString *path=hintPath(@"hint-panel.json");
 if(!p.count){[NSFileManager.defaultManager removeItemAtPath:path error:nil];return;}
 [[NSJSONSerialization dataWithJSONObject:p options:0 error:nil] writeToFile:path options:NSDataWritingAtomic error:nil];
}
static CGFloat hintPanelMaxWidth(void){return MAX(HINT_MIN_W,NSWidth(hintGame.contentView.bounds)-40);}
static CGFloat hintPanelMaxHeight(void){return MAX(HINT_MIN_H,NSHeight(hintGame.contentView.bounds)-40);}
/* hintLayout's width and height: the player's (fitted to the window) when set, else the automatic ones. */
static CGFloat hintPanelWidth(CGFloat automatic){hintPanelLoad();return hintPanelSized?MIN(hintPanelSize.width,hintPanelMaxWidth()):automatic;}
static CGFloat hintPanelHeight(CGFloat automatic){hintPanelLoad();return hintPanelSized?MIN(hintPanelSize.height,hintPanelMaxHeight()):automatic;}
/* hintLayout's frame: the automatic one moved to the player's place, unless 指给我看 needs the panel on the left. */
static NSRect hintPanelPlace(NSRect automatic){
 hintPanelLoad();
 if(!hintPanelPlaced||hintPanelLeft)return automatic;
 NSRect travel=hintPanelTravel(automatic.size);
 automatic.origin=NSMakePoint(round(NSMinX(travel)+hintPanelPosition.x*NSWidth(travel)),round(NSMinY(travel)+hintPanelPosition.y*NSHeight(travel)));
 return automatic;
}
/* Lines on one page of an answer: three in the automatic panel, as many as fit (up to the answer's six) in a taller one. */
static NSUInteger hintPageLines(void){
 hintPanelLoad();
 if(!hintPanelSized)return 3;
 return (NSUInteger)MAX(3,MIN(6,floor(hintScroll.contentSize.height/24)));
}

static int hintPanelGrabAt(NSPoint p,NSSize size){   // in the panel's own coordinates
 if(p.y<HINT_GRIP&&p.x<HINT_GRIP)return 2;
 if(p.y<HINT_GRIP&&p.x>size.width-HINT_GRIP)return 3;
 if(p.y>size.height-HINT_HEADER)return 1;
 return 0;
}
static void hintPanelGrabStart(int grab,NSPoint pointer){hintPanelGrab=grab;hintPanelGrabPointer=pointer;hintPanelGrabFrame=hintPanel.frame;}
/* The pointer (in screen coordinates) moved to `pointer` while the panel is held. */
static void hintPanelGrabTo(NSPoint pointer){
 if(!hintPanelGrab)return;
 CGFloat dx=pointer.x-hintPanelGrabPointer.x,dy=pointer.y-hintPanelGrabPointer.y;
 NSRect f=hintPanelGrabFrame;
 if(hintPanelGrab==1){f.origin.x+=dx;f.origin.y+=dy;}
 else{   // a lower corner: the opposite upper corner stays where it is
  CGFloat w=MAX(HINT_MIN_W,MIN(hintPanelMaxWidth(),NSWidth(f)+(hintPanelGrab==2?-dx:dx)));
  CGFloat h=MAX(HINT_MIN_H,MIN(hintPanelMaxHeight(),NSHeight(f)-dy));
  if(hintPanelGrab==2)f.origin.x=NSMaxX(f)-w;
  f.origin.y=NSMaxY(f)-h;f.size=NSMakeSize(w,h);
  hintPanelSize=f.size;hintPanelSized=YES;
 }
 NSRect travel=hintPanelTravel(f.size);
 CGFloat x=MAX(NSMinX(travel),MIN(NSMaxX(travel),NSMinX(f))),y=MAX(NSMinY(travel),MIN(NSMaxY(travel),NSMinY(f)));
 hintPanelPosition=NSMakePoint(NSWidth(travel)?(x-NSMinX(travel))/NSWidth(travel):0,NSHeight(travel)?(y-NSMinY(travel))/NSHeight(travel):0);
 hintPanelPlaced=YES;hintPanelLeft=NO;
 hintLayout(0);
}
static void hintPanelGrabStop(void){if(hintPanelGrab)hintPanelSave();hintPanelGrab=0;}
static void hintPanelReset(void){hintPanelGrab=0;hintPanelSized=hintPanelPlaced=NO;hintPanelSave();hintLayout(0);}
// The surface's mouse events.
static void hintPanelGrabBegin(NSEvent *event,NSView *surface){
 int grab=hintPanelGrabAt([surface convertPoint:event.locationInWindow fromView:nil],surface.bounds.size);
 if(grab==1&&event.clickCount==2){hintPanelReset();return;}   // the header, twice: back to automatic
 hintPanelGrabStart(grab,[event.window convertPointToScreen:event.locationInWindow]);
}
static void hintPanelGrabMove(NSEvent *event){hintPanelGrabTo([event.window convertPointToScreen:event.locationInWindow]);}
static void hintPanelGrabEnd(NSEvent *event){(void)event;hintPanelGrabStop();}
/* The grips: three short diagonal strokes in each lower corner. */
static void hintPanelDrawGrips(NSSize size){
 [[hintInk() colorWithAlphaComponent:0.28] setStroke];
 for(int right=0;right<2;right++)for(int i=1;i<=3;i++){
  CGFloat d=i*4.0;NSBezierPath *line=[NSBezierPath bezierPath];line.lineWidth=0.8;
  if(right){[line moveToPoint:NSMakePoint(size.width-4-d,4)];[line lineToPoint:NSMakePoint(size.width-4,4+d)];}
  else{[line moveToPoint:NSMakePoint(4+d,4)];[line lineToPoint:NSMakePoint(4,4+d)];}
  [line stroke];
 }
}
static void hintPanelCursorRects(NSView *surface){
 NSSize s=surface.bounds.size;
 [surface addCursorRect:NSMakeRect(0,0,HINT_GRIP,HINT_GRIP) cursor:[NSCursor frameResizeCursorFromPosition:NSCursorFrameResizePositionBottomLeft inDirections:NSCursorFrameResizeDirectionsAll]];
 [surface addCursorRect:NSMakeRect(s.width-HINT_GRIP,0,HINT_GRIP,HINT_GRIP) cursor:[NSCursor frameResizeCursorFromPosition:NSCursorFrameResizePositionBottomRight inDirections:NSCursorFrameResizeDirectionsAll]];
 [surface addCursorRect:NSMakeRect(0,s.height-HINT_HEADER,s.width,HINT_HEADER) cursor:NSCursor.openHandCursor];
}
