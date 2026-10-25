/* Driving the assistant panel from the game's command channel, for automated tests of a test session only
   (TOTK_HINT_TEST=1): runtime/input.c hands every "hint ..." line here, and it runs on AppKit's main queue.
     hint open | close | ask <text> | point [<text>] | next | read | key <Mac key code> | snap <png> | state <json> |
     voicecheck (hint_voice.inc: permissions, 1.5 s of the microphone, a synthesized sentence through the recognizer) |
     voice (key 0: start listening, or stop and leave the words in the question field)
   snap draws what the player sees over the game window: the frame the panel opened on, the 指给我看 marks, the
   companion and the panel (the game's own window shot holds none of these windows). state writes what is on the
   panel for a script to check. Reading stays silent in a test session (volume 0); everything else runs as it does
   for the player, the model requests included. */
static BOOL hintTestMode(void){const char *v=getenv("TOTK_HINT_TEST");return v&&!strcmp(v,"1");}
static void hintTestKey(unsigned short code){
 NSString *chars=code==36?@"\r":code==53?@"\x1b":code==28?@"8":@"";
 for(int down=1;down>=0;down--){
  NSEvent *e=[NSEvent keyEventWithType:down?NSEventTypeKeyDown:NSEventTypeKeyUp location:NSZeroPoint modifierFlags:0 timestamp:0
   windowNumber:hintGame.windowNumber context:nil characters:chars charactersIgnoringModifiers:chars isARepeat:NO keyCode:code];
  totk_hint_key(e,down);
 }
}
static void hintTestSnap(NSString *path){
 NSRect game=[hintGame convertRectToScreen:hintGame.contentView.bounds];
 NSBitmapImageRep *canvas=[[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL pixelsWide:(NSInteger)NSWidth(game)
  pixelsHigh:(NSInteger)NSHeight(game) bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:0 bitsPerPixel:0];
 [NSGraphicsContext saveGraphicsState];[NSGraphicsContext setCurrentContext:[NSGraphicsContext graphicsContextWithBitmapImageRep:canvas]];
 NSImage *frame=hintSceneReady?[[NSImage alloc] initWithContentsOfFile:hintPath(@"hint-scene.png")]:nil;
 if(frame)[frame drawInRect:NSMakeRect(0,0,NSWidth(game),NSHeight(game))];
 else{[NSColor.darkGrayColor setFill];NSRectFill(NSMakeRect(0,0,NSWidth(game),NSHeight(game)));}
 for(NSWindow *w in @[hintMarksWindow?:(id)NSNull.null,hintDock?:(id)NSNull.null,hintPanel?:(id)NSNull.null]){
  if(![w isKindOfClass:NSWindow.class]||!w.visible)continue;
  NSView *v=w.contentView;NSBitmapImageRep *rep=[v bitmapImageRepForCachingDisplayInRect:v.bounds];[v cacheDisplayInRect:v.bounds toBitmapImageRep:rep];
  [rep drawInRect:NSMakeRect(NSMinX(w.frame)-NSMinX(game),NSMinY(w.frame)-NSMinY(game),NSWidth(w.frame),NSHeight(w.frame))
   fromRect:NSZeroRect operation:NSCompositingOperationSourceOver fraction:1 respectFlipped:YES hints:nil];
 }
 [NSGraphicsContext restoreGraphicsState];
 [[canvas representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:path atomically:YES];
}
static void hintTestState(NSString *path){
 NSMutableDictionary *buttons=[NSMutableDictionary new];
 NSDictionary *named=@{@"enable":hintEnable?:NSNull.null,@"point":hintPointButton?:NSNull.null,@"read":hintRead?:NSNull.null,
  @"actions":hintActionsButton?:NSNull.null,@"setup":hintVoiceSetup?:NSNull.null,@"history":hintHistoryButton?:NSNull.null,
  @"mic":hintMic?:NSNull.null,@"send":hintSend?:NSNull.null,@"back":hintBack?:NSNull.null};
 for(NSString *name in named){NSButton *b=named[name];if([b isKindOfClass:NSButton.class])buttons[name]=@{@"title":b.title?:@"",@"hidden":@(b.hidden),@"enabled":@(b.enabled)};}
 NSDictionary *state=@{@"expanded":@(hintExpanded),@"panel_visible":@(hintPanel.visible),@"working":@(hintWorking),@"done":@(hintDone),
  @"text":hintText.stringValue?:@"",@"bubble":hintBubble.stringValue?:@"",@"disclosure":hintDisclosure.stringValue?:@"",
  @"stage":hintStage?:@"",@"partial_chars":@(hintPartial.length),@"revealed":@(hintRevealed),
  @"page":@(hintPage),@"pages":@(hintPages.count),@"read_on":@(hintReadOn()),@"reading":@(hintReadID!=nil),
  @"read_system":@(hintReadSystem),@"read_engine":hintReadEngine?:@"",@"read_line":@(hintReadLine),@"read_playing":@(hintReadPlaying),
  @"scene_ready":@(hintSceneReady),@"marks":@(hintMarks.count),@"marks_visible":@(hintMarksWindow.visible),
  @"paused":@(hintPauseHeld),@"question":hintQuestion.stringValue?:@"",@"listening":@(hintListening),@"voice_finishing":@(hintVoiceFinishing),@"history":@(hintHistory.count),@"buttons":buttons,@"time":@(NSDate.date.timeIntervalSince1970)};
 NSData *data=[NSJSONSerialization dataWithJSONObject:state options:NSJSONWritingPrettyPrinted error:nil];
 [data writeToFile:path options:NSDataWritingAtomic error:nil];
}
int totk_hint_command(const char *line){
 if(strncmp(line,"hint ",5))return 0;
 if(!hintTestMode()){fprintf(stderr,"[hint-test] ignored: start the game with TOTK_HINT_TEST=1 to drive the panel\n");return 1;}
 NSString *command=[[NSString stringWithUTF8String:line+5]?:@"" stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
 dispatch_async(dispatch_get_main_queue(),^{
  NSRange space=[command rangeOfString:@" "];
  NSString *op=space.location==NSNotFound?command:[command substringToIndex:space.location];
  NSString *arg=space.location==NSNotFound?@"":[command substringFromIndex:space.location+1];
  if([op isEqual:@"open"])hintOpen();
  else if([op isEqual:@"close"])[hintActions close:nil];
  else if([op isEqual:@"ask"]){hintQuestion.stringValue=arg;[hintActions send:nil];}
  else if([op isEqual:@"point"]){hintQuestion.stringValue=arg;[hintActions point:nil];}
  else if([op isEqual:@"next"])hintPageNext();
  else if([op isEqual:@"read"])[hintActions read:nil];
  else if([op isEqual:@"key"])hintTestKey((unsigned short)arg.intValue);
  else if([op isEqual:@"snap"])hintTestSnap(arg);
  else if([op isEqual:@"state"])hintTestState(arg);
  else if([op isEqual:@"voicecheck"])hintVoiceCheck();
  else if([op isEqual:@"voice"])hintVoiceShortcut();
  else{fprintf(stderr,"[hint-test] unknown: %s\n",command.UTF8String);return;}
  fprintf(stderr,"[hint-test] %s\n",command.UTF8String);
 });
 return 1;
}
