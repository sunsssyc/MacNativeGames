/* runtime/hint_panel_frame.inc alone: the panel's place and size, the player's (dragged header, dragged lower corners,
   double-clicked header), kept in hint-panel.json. A plain game window and panel stand in for the game's. argv[1]: a
   folder to use as the game's data folder. */
#import <Cocoa/Cocoa.h>
#include <assert.h>
static NSWindow *hintGame;
static NSPanel *hintPanel;
static NSScrollView *hintScroll;
static BOOL hintPanelLeft;
static NSString *hintFolder;
static int layouts;
static NSString *hintPath(NSString *name) { return [hintFolder stringByAppendingPathComponent:name]; }
static NSDictionary *hintJSON(NSString *path) { NSData *d=[NSData dataWithContentsOfFile:path]; id v=d?[NSJSONSerialization JSONObjectWithData:d options:0 error:nil]:nil; return [v isKindOfClass:NSDictionary.class]?v:nil; }
static NSColor *hintInk(void){return NSColor.whiteColor;}
#include "../games/totk/runtime/hint_panel_frame.inc"
/* As the panel's hintLayout does: automatic 380 x 300 on the right, the player's when set. */
static void hintLayout(CGFloat height){
 (void)height;layouts++;
 CGFloat w=hintPanelWidth(380),h=hintPanelHeight(300);NSRect f=[hintGame convertRectToScreen:hintGame.contentView.bounds];
 [hintPanel setFrame:hintPanelPlace(NSMakeRect(hintPanelLeft?NSMinX(f)+24:NSMaxX(f)-w-24,NSMinY(f)+100,w,h)) display:NO];
 hintScroll.frame=NSMakeRect(0,0,w-40,h-224);
}
static BOOL near(CGFloat a,CGFloat b){return fabs(a-b)<0.6;}

int main(int argc,const char **argv){@autoreleasepool{
 if(argc!=2)return 2;
 [NSApplication sharedApplication];hintFolder=@(argv[1]);
 hintGame=[[NSWindow alloc] initWithContentRect:NSMakeRect(100,100,1000,560) styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:YES];
 hintPanel=[[NSPanel alloc] initWithContentRect:NSZeroRect styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:YES];
 hintScroll=[NSScrollView new];
 /* Nothing set: automatic, three lines a page, no file. */
 hintLayout(0);NSRect automatic=hintPanel.frame;
 assert(near(NSWidth(automatic),380) && near(NSMaxX(automatic),1076) && hintPageLines()==3);
 assert(hintPanelGrabAt(NSMakePoint(5,5),automatic.size)==2 && hintPanelGrabAt(NSMakePoint(375,5),automatic.size)==3);
 assert(hintPanelGrabAt(NSMakePoint(190,280),automatic.size)==1 && hintPanelGrabAt(NSMakePoint(190,150),automatic.size)==0);
 /* The header dragged 200 pt left and 50 up: moved, the size stays automatic. */
 hintPanelGrabStart(1,NSMakePoint(800,400));hintPanelGrabTo(NSMakePoint(600,450));hintPanelGrabStop();
 assert(near(NSMinX(hintPanel.frame),NSMinX(automatic)-200) && near(NSMinY(hintPanel.frame),NSMinY(automatic)+50));
 assert(near(NSWidth(hintPanel.frame),380) && !hintPanelSized && hintPanelPlaced);
 /* The lower left corner dragged 100 left and 120 down: wider and taller, the upper right corner stays. */
 NSRect before=hintPanel.frame;
 hintPanelGrabStart(2,before.origin);hintPanelGrabTo(NSMakePoint(NSMinX(before)-100,NSMinY(before)-120));hintPanelGrabStop();
 NSRect after=hintPanel.frame;
 assert(near(NSWidth(after),480) && near(NSHeight(after),420) && near(NSMaxX(after),NSMaxX(before)) && near(NSMaxY(after),NSMaxY(before)));
 assert(hintPanelSized && hintPageLines()==6);   /* 196 pt of text: an answer's six lines on one page */
 /* Not smaller than the minimum, not larger than the game window, not outside it. */
 hintPanelGrabStart(3,NSMakePoint(NSMaxX(after),NSMinY(after)));hintPanelGrabTo(NSMakePoint(NSMaxX(after)-900,NSMinY(after)+900));hintPanelGrabStop();
 assert(near(NSWidth(hintPanel.frame),HINT_MIN_W) && near(NSHeight(hintPanel.frame),HINT_MIN_H));
 hintPanelGrabStart(1,NSMakePoint(500,300));hintPanelGrabTo(NSMakePoint(-3000,-3000));hintPanelGrabStop();
 assert(near(NSMinX(hintPanel.frame),112) && near(NSMinY(hintPanel.frame),112));   /* the game window's corner, 12 in */
 /* Kept: the file holds the fractions and the size, a later run starts from them. */
 NSDictionary *saved=hintJSON(hintPath(@"hint-panel.json"));
 assert([saved[@"x"] doubleValue]==0 && [saved[@"y"] doubleValue]==0 && [saved[@"w"] intValue]==HINT_MIN_W);
 hintPanelLoaded=NO;hintPanelSized=hintPanelPlaced=NO;hintLayout(0);
 assert(near(NSMinX(hintPanel.frame),112) && near(NSWidth(hintPanel.frame),HINT_MIN_W));
 /* 指给我看 needs the left side: the automatic place for now, the player's size kept. */
 hintPanelLeft=YES;hintLayout(0);assert(near(NSMinX(hintPanel.frame),124) && near(NSWidth(hintPanel.frame),HINT_MIN_W));hintPanelLeft=NO;
 /* A smaller game window: the panel shrinks to fit it. */
 hintPanelSize=NSMakeSize(900,500);hintLayout(0);[hintGame setContentSize:NSMakeSize(700,400)];hintLayout(0);
 assert(near(NSWidth(hintPanel.frame),660) && near(NSHeight(hintPanel.frame),360));
 /* Double-clicked header: automatic again, and the file is gone. */
 hintPanelReset();
 assert(!hintPanelSized && !hintPanelPlaced && ![NSFileManager.defaultManager fileExistsAtPath:hintPath(@"hint-panel.json")]);
 puts("pass: panel drag and resize");
 return 0;
}}
