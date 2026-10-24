/* Pages and 朗读. An answer (at most six lines, prompts.py) shows three lines at a time ending in ▼: Return, a click on
   the text, or the end of the page being read moves on. 朗读 is off by default and remembered in assistant.json
   voice.enabled. With the voice installed and a reference voice recorded (录我的声音), the hint service's Qwen3-TTS
   clone reads each page (tools/hint_assistant/totk_hint/voice.py); until then the macOS system voice does. Reading
   happens only behind the open panel, while the game is paused (the model shares the GPU), and stops when it closes. */
static NSArray<NSString *> *hintPages;
static NSString *hintPagedAnswer;
static NSUInteger hintPage;
static NSString *hintReadID;            // the reading request for the answer on screen
static BOOL hintReadSystem;             // this answer is read by the system voice
static NSInteger hintReadPlaying=-1;    // the page being read
static NSInteger hintReadDone=-1;       // the last page whose reading finished
static AVAudioPlayer *hintPlayer;
static AVSpeechSynthesizer *hintSpeaker;
static NSButton *hintVoiceSetup;        // 下载语音 / 录我的声音 / 完成
static NSString *hintSetupID;
static AVAudioEngine *hintRecorder;
static BOOL hintRecording;
static NSUInteger hintRecordGeneration;
static NSDate *hintRecordStarted;
static NSString *const hintReferenceText=@"今天天气不错，我们一起去海拉鲁平原走一走，看看远处的城堡。";

static BOOL hintReadOn(void){
 id voice=hintJSON(hintPath(@"assistant.json"))[@"voice"];
 return [voice isKindOfClass:NSDictionary.class]&&[voice[@"enabled"] boolValue];
}
static BOOL hintReadSet(BOOL on){
 NSString *path=hintPath(@"assistant.json");NSDictionary *existing=hintJSON(path);if(!existing)return NO;
 NSMutableDictionary *config=[existing mutableCopy];
 NSMutableDictionary *voice=[config[@"voice"] isKindOfClass:NSDictionary.class]?[config[@"voice"] mutableCopy]:[NSMutableDictionary new];
 voice[@"enabled"]=@(on);config[@"voice"]=voice;
 NSData *data=[NSJSONSerialization dataWithJSONObject:config options:NSJSONWritingPrettyPrinted error:nil];
 return data&&[data writeToFile:path options:NSDataWritingAtomic error:nil];
}
static void hintVoiceWrite(NSDictionary *value){
 NSData *data=[NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
 [data writeToFile:hintPath(@"hint-voice-request.json") options:NSDataWritingAtomic error:nil];
}

// pages ---------------------------------------------------------------------------------------------------------------
static NSArray<NSString *> *hintPagesOf(NSString *text){
 NSMutableArray<NSString *> *lines=[NSMutableArray new],*pages=[NSMutableArray new];
 for(NSString *line in [text componentsSeparatedByString:@"\n"])
  if([line stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet].length)[lines addObject:line];
 for(NSUInteger i=0;i<lines.count;i+=3)
  [pages addObject:[[lines subarrayWithRange:NSMakeRange(i,MIN(3,lines.count-i))] componentsJoinedByString:@"\n"]];
 return pages.count?pages:@[text];
}
static NSString *hintPageText(NSString *answer){   // the page on screen of answer, ▼ when more follow
 if(![answer isEqual:hintPagedAnswer]){hintPagedAnswer=answer;hintPages=hintPagesOf(answer);hintPage=0;}
 return hintPage+1<hintPages.count?[hintPages[hintPage] stringByAppendingString:@"  ▼"]:hintPages[hintPage];
}
static BOOL hintPagesRemain(void){return hintDone&&!hintHistoryExpanded&&hintPage+1<hintPages.count;}

// reading -------------------------------------------------------------------------------------------------------------
static AVSpeechSynthesisVoice *hintSystemVoice(void){
 AVSpeechSynthesisVoice *best=[AVSpeechSynthesisVoice voiceWithLanguage:@"zh-CN"];
 for(AVSpeechSynthesisVoice *voice in AVSpeechSynthesisVoice.speechVoices)
  if([voice.language isEqual:@"zh-CN"]&&!(voice.voiceTraits&AVSpeechSynthesisVoiceTraitIsPersonalVoice)&&voice.quality>best.quality)best=voice;
 return best;
}
static void hintReadHalt(void){
 if(hintPlayer.playing)[hintPlayer stop];
 hintPlayer=nil;
 if(hintSpeaker.speaking)[hintSpeaker stopSpeakingAtBoundary:AVSpeechBoundaryImmediate];
 hintReadPlaying=-1;
}
static void hintReadStop(void){   // and the service stops making the rest
 hintReadHalt();
 if(hintReadID)hintVoiceWrite(@{@"id":hintReadID,@"cancel":@YES});
 hintReadID=nil;
}
static void hintReadPage(void){   // read the page on screen once its audio is there (hintVoicePoll asks again)
 if(!hintExpanded||hintReadPlaying==(NSInteger)hintPage||hintReadDone>=(NSInteger)hintPage||hintPage>=hintPages.count)return;
 hintReadHalt();
 if(hintReadSystem){
  if(!hintSpeaker){hintSpeaker=[AVSpeechSynthesizer new];hintSpeaker.delegate=(id)hintActions;}
  AVSpeechUtterance *utterance=[AVSpeechUtterance speechUtteranceWithString:hintPages[hintPage]];
  utterance.voice=hintSystemVoice();hintReadPlaying=hintPage;[hintSpeaker speakUtterance:utterance];return;
 }
 NSDictionary *reply=hintJSON(hintPath(@"hint-voice.json"));
 if(![reply[@"id"] isEqual:hintReadID])return;
 NSArray *files=reply[@"files"];
 id file=[files isKindOfClass:NSArray.class]&&hintPage<files.count?files[hintPage]:nil;
 if(![file isKindOfClass:NSString.class])return;
 hintPlayer=[[AVAudioPlayer alloc] initWithContentsOfURL:[NSURL fileURLWithPath:file] error:nil];
 hintPlayer.delegate=(id)hintActions;
 if([hintPlayer play])hintReadPlaying=hintPage;
}
static void hintReadAnswer(void){   // a new answer on screen, or 朗读 switched on
 hintReadStop();hintReadDone=-1;
 if(!hintDone||!hintPages.count||!hintExpanded)return;
 hintReadSystem=!hintService.running;   // answers come from the service, so it runs; never start it just to read
 if(!hintReadSystem){hintReadID=NSUUID.UUID.UUIDString;hintVoiceWrite(@{@"id":hintReadID,@"pages":hintPages});}
 hintReadPage();
}
static void hintShowSetup(NSString *title){
 hintVoiceSetup.title=title?:@"";hintVoiceSetup.hidden=!title;hintLayout(0);
}
static BOOL hintPageNext(void){
 if(!hintPagesRemain())return NO;
 hintPage++;hintShow(hintPagedAnswer);
 if(hintReadOn())hintReadPage();
 return YES;
}
static void hintReadFinished(void){
 NSInteger page=hintReadPlaying;hintReadPlaying=-1;
 if(page!=(NSInteger)hintPage)return;
 hintReadDone=page;hintPageNext();
}
static void hintVoicePoll(void){
 if(hintSetupID){
  NSDictionary *setup=hintJSON(hintPath(@"hint-voice-setup.json"));
  if([setup[@"id"] isEqual:hintSetupID]){
   NSString *status=setup[@"status"],*text=[setup[@"text"] isKindOfClass:NSString.class]?setup[@"text"]:@"";
   if([status isEqual:@"installing"])hintDisclosure.stringValue=text;
   else{
    hintSetupID=nil;hintDisclosure.stringValue=text;
    if([status isEqual:@"installed"])hintShowSetup([setup[@"reference"] boolValue]?nil:@"录我的声音");
    if([status isEqual:@"reference_saved"])hintShowSetup([setup[@"installed"] boolValue]?nil:@"下载语音");
    if([status isEqual:@"installed"]||[status isEqual:@"reference_saved"])
     if(hintReadOn()&&hintDone)hintReadAnswer();   // the page on screen again, in the new voice
   }
  }
 }
 if(!hintReadID)return;
 NSDictionary *reply=hintJSON(hintPath(@"hint-voice.json"));
 if(![reply[@"id"] isEqual:hintReadID])return;
 NSString *status=reply[@"status"];
 if([status isEqual:@"missing"]||[status isEqual:@"no_reference"]||[status isEqual:@"error"]){
  hintReadID=nil;hintReadSystem=YES;
  if([status isEqual:@"missing"]&&!hintSetupID)hintShowSetup(@"下载语音");
  if([status isEqual:@"no_reference"])hintShowSetup(@"录我的声音");
  if(hintReadPlaying<0)hintReadPage();   // the system voice reads from the page on screen
  return;
 }
 if(hintReadPlaying<0)hintReadPage();    // this page's audio may have just arrived
}

// 录我的声音 -----------------------------------------------------------------------------------------------------------
static void hintRecordEnd(BOOL save){
 if(!hintRecording)return;
 hintRecordGeneration++;hintRecording=NO;
 [hintRecorder stop];[hintRecorder.inputNode removeTapOnBus:0];hintRecorder=nil;
 NSString *take=hintPath(@"tts-take.caf");
 double seconds=-hintRecordStarted.timeIntervalSinceNow;
 hintShow(hintLatest?:@"");
 if(!save){[NSFileManager.defaultManager removeItemAtPath:take error:nil];hintShowSetup(@"录我的声音");
  hintDisclosure.stringValue=@"已取消录音，没有保存";return;}
 if(seconds<3){hintShowSetup(@"录我的声音");hintDisclosure.stringValue=@"录音太短，请把整句读完再点「完成」";return;}
 if(!hintStart()){hintShowSetup(@"录我的声音");return;}
 hintSetupID=NSUUID.UUID.UUIDString;hintShowSetup(nil);hintDisclosure.stringValue=@"正在保存你的声音……";
 hintVoiceWrite(@{@"id":hintSetupID,@"reference":take,@"text":hintReferenceText});
}
static void hintRecordBegin(void){
 if(hintRecording||hintListening||hintVoiceFinishing||hintWorking)return;
 AVAuthorizationStatus mic=[AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio];
 if(mic==AVAuthorizationStatusNotDetermined){
  [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL allowed){dispatch_async(dispatch_get_main_queue(),^{
   hintDisclosure.stringValue=allowed?@"麦克风已授权 · 再点「录我的声音」开始":@"麦克风未授权，无法录音";});}];return;
 }
 if(mic!=AVAuthorizationStatusAuthorized){hintDisclosure.stringValue=@"麦克风未授权 · 可在系统设置中开启";return;}
 hintReadStop();
 AVAudioEngine *engine=[AVAudioEngine new];AVAudioFormat *format=[engine.inputNode outputFormatForBus:0];
 if(format.channelCount==0||format.sampleRate<=0){hintDisclosure.stringValue=@"未找到可用麦克风";return;}
 NSString *take=hintPath(@"tts-take.caf");[NSFileManager.defaultManager removeItemAtPath:take error:nil];
 NSError *error=nil;
 AVAudioFile *file=[[AVAudioFile alloc] initForWriting:[NSURL fileURLWithPath:take] settings:format.settings error:&error];
 if(!file){hintDisclosure.stringValue=@"无法创建录音文件";return;}
 [engine.inputNode installTapOnBus:0 bufferSize:4096 format:format block:^(AVAudioPCMBuffer *buffer,AVAudioTime *when){(void)when;[file writeFromBuffer:buffer error:nil];}];
 [engine prepare];
 if(![engine startAndReturnError:&error]){[engine.inputNode removeTapOnBus:0];hintDisclosure.stringValue=@"麦克风暂时无法使用";return;}
 hintRecorder=engine;hintRecording=YES;hintRecordStarted=NSDate.date;NSUInteger generation=++hintRecordGeneration;
 hintText.stringValue=[NSString stringWithFormat:@"请用平常的语气读出下面这句话：\n「%@」\n\n只录你自己，或已经同意的人的声音。",hintReferenceText];
 hintShowSetup(@"完成");hintDisclosure.stringValue=@"正在录音 · 读完点「完成」· Esc 取消";
 dispatch_after(dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC),dispatch_get_main_queue(),^{
  if(generation==hintRecordGeneration)hintRecordEnd(YES);});
}

@interface TOTKHintActions (Voice)<AVAudioPlayerDelegate,AVSpeechSynthesizerDelegate>
@end
@implementation TOTKHintActions (Voice)
-(void)audioPlayerDidFinishPlaying:(AVAudioPlayer *)player successfully:(BOOL)flag{
 (void)flag;dispatch_async(dispatch_get_main_queue(),^{if(player==hintPlayer)hintReadFinished();});
}
-(void)speechSynthesizer:(AVSpeechSynthesizer *)synthesizer didFinishSpeechUtterance:(AVSpeechUtterance *)utterance{
 (void)synthesizer;(void)utterance;dispatch_async(dispatch_get_main_queue(),^{if(hintReadPlaying>=0)hintReadFinished();});
}
-(void)pageNext:(id)sender{(void)sender;hintPageNext();}
-(void)voiceSetup:(id)sender{
 (void)sender;
 if(hintRecording){hintRecordEnd(YES);return;}
 if([hintVoiceSetup.title isEqual:@"录我的声音"]){hintRecordBegin();return;}
 if(hintSetupID||!hintStart())return;
 hintSetupID=NSUUID.UUID.UUIDString;hintShowSetup(nil);hintDisclosure.stringValue=@"正在准备下载语音……";
 hintVoiceWrite(@{@"id":hintSetupID,@"install":@YES});
}
@end
static void hintVoiceInstall(void){
 hintVoiceSetup=[TOTKHintButton buttonWithTitle:@"" target:hintActions action:@selector(voiceSetup:)];
 ((TOTKHintButton *)hintVoiceSetup).quiet=YES;hintVoiceSetup.hidden=YES;[hintPanel.contentView addSubview:hintVoiceSetup];
 [hintScroll addGestureRecognizer:[[NSClickGestureRecognizer alloc] initWithTarget:hintActions action:@selector(pageNext:)]];
}
