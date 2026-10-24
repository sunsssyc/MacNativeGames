/* Pages and 朗读. An answer (at most six lines, prompts.py) shows three lines at a time ending in ▼ (more in a panel the
   player made taller: hintPageLines, hint_panel_frame.inc): Return, a click on
   the text, or the voice reaching the next page moves on. 朗读 is off by default and remembered in assistant.json
   voice.enabled. It reads line by line, while the answer is still being written: the hint service makes each finished
   line's audio (tools/hint_assistant/totk_hint/voice.py: Google Chirp 3 HD, or the local Qwen3-TTS clone of a recorded
   voice); when it has no voice the macOS system voice reads instead. Google and the system voice go on reading after
   the panel closes; the local clone shares the GPU with the game and stops with it. */
static NSArray<NSString *> *hintPages;
static NSString *hintPagedAnswer;   // nil at each new request: the answer then starts on its first page
static NSUInteger hintPage;
static NSString *hintReadID;            // the reading job: the hint request's id while it streams, else its own
static NSString *hintReadEngine;        // the service's voice for it ("google", "local"), nil until it says
static BOOL hintReadSystem;             // the system voice reads it
static NSInteger hintReadLine;          // the next line to read
static NSInteger hintReadPlaying=-1;    // the line being read
static AVAudioPlayer *hintPlayer;
static AVSpeechSynthesizer *hintSpeaker;
static NSButton *hintVoiceSetup;        // 下载语音 / 录我的声音 / 完成
static NSString *hintSetupID;
static AVAudioEngine *hintRecorder;
static BOOL hintRecording;
static NSUInteger hintRecordGeneration;
static NSDate *hintRecordStarted;
static NSString *const hintReferenceText=@"今天天气不错，我们一起去海拉鲁平原走一走，看看远处的城堡。";

static NSDictionary *hintVoiceConfig(void){
 id voice=hintJSON(hintPath(@"assistant.json"))[@"voice"];
 return [voice isKindOfClass:NSDictionary.class]?voice:@{};
}
static BOOL hintReadOn(void){return [hintVoiceConfig()[@"enabled"] boolValue];}
static BOOL hintReadSet(BOOL on){
 NSString *path=hintPath(@"assistant.json");NSDictionary *existing=hintJSON(path);if(!existing)return NO;
 NSMutableDictionary *config=[existing mutableCopy];
 NSMutableDictionary *voice=[hintVoiceConfig() mutableCopy];
 voice[@"enabled"]=@(on);config[@"voice"]=voice;
 NSData *data=[NSJSONSerialization dataWithJSONObject:config options:NSJSONWritingPrettyPrinted error:nil];
 return data&&[data writeToFile:path options:NSDataWritingAtomic error:nil];
}
static void hintVoiceWrite(NSDictionary *value){
 NSData *data=[NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
 [data writeToFile:hintPath(@"hint-voice-request.json") options:NSDataWritingAtomic error:nil];
}

// pages ---------------------------------------------------------------------------------------------------------------
static NSArray<NSString *> *hintLinesOf(NSString *text){   // voice.py lines_of: the same lines, so line i is file i
 NSMutableArray<NSString *> *lines=[NSMutableArray new];
 for(NSString *line in [text?:@"" componentsSeparatedByString:@"\n"]){
  NSString *trimmed=[line stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
  if(trimmed.length)[lines addObject:trimmed];
 }
 return lines;
}
static NSArray<NSString *> *hintPagesOf(NSString *text){   // hintPageLines lines each (hint_panel_frame.inc)
 NSArray<NSString *> *lines=hintLinesOf(text);NSMutableArray<NSString *> *pages=[NSMutableArray new];NSUInteger per=hintPageLines();
 for(NSUInteger i=0;i<lines.count;i+=per)
  [pages addObject:[[lines subarrayWithRange:NSMakeRange(i,MIN(per,lines.count-i))] componentsJoinedByString:@"\n"]];
 return pages.count?pages:@[text];
}
static NSString *hintPageText(NSString *answer){   // the page on screen of answer, ▼ when more follow
 if(![answer isEqual:hintPagedAnswer]){
  if(!hintPagedAnswer)hintPage=0;   // the same answer growing as it is typed out keeps the page the player is on
  hintPagedAnswer=answer;hintPages=hintPagesOf(answer);hintPage=MIN(hintPage,hintPages.count-1);
 }
 return hintPage+1<hintPages.count?[hintPages[hintPage] stringByAppendingString:@"  ▼"]:hintPages[hintPage];
}
static BOOL hintPagesRemain(void){return (hintDone||hintWorking)&&!hintHistoryExpanded&&hintPage+1<hintPages.count;}
static void hintShowPage(void){hintShow(hintWorking?@"":hintPagedAnswer?:@"");}

// reading -------------------------------------------------------------------------------------------------------------
static AVSpeechSynthesisVoice *hintSystemVoice(void){
 AVSpeechSynthesisVoice *best=[AVSpeechSynthesisVoice voiceWithLanguage:@"zh-CN"];
 for(AVSpeechSynthesisVoice *voice in AVSpeechSynthesisVoice.speechVoices)
  if([voice.language isEqual:@"zh-CN"]&&!(voice.voiceTraits&AVSpeechSynthesisVoiceTraitIsPersonalVoice)&&voice.quality>best.quality)best=voice;
 return best;
}
static void hintReadHalt(void){   // the line being read stops; reading goes on from hintReadLine
 if(hintPlayer.playing)[hintPlayer stop];
 hintPlayer=nil;
 if(hintSpeaker.speaking)[hintSpeaker stopSpeakingAtBoundary:AVSpeechBoundaryImmediate];
 hintReadPlaying=-1;
}
static void hintReadStop(void){   // reading ends, and the service stops making the rest
 hintReadHalt();
 if(hintReadID&&!hintReadSystem)hintVoiceWrite(@{@"id":hintReadID,@"cancel":@YES});
 hintReadID=hintReadEngine=nil;hintReadSystem=NO;
}
static NSArray<NSString *> *hintAnswerLines(void){return hintLinesOf(hintWorking?hintPartial:hintPagedAnswer);}
static BOOL hintLineFinished(NSArray<NSString *> *lines,NSInteger i){   // voice.py finished_lines
 return i+1<(NSInteger)lines.count||(i<(NSInteger)lines.count&&(!hintWorking||[@"。！？!?…" rangeOfString:[lines[i] substringFromIndex:lines[i].length-1]].location!=NSNotFound));
}
static void hintReadTick(void){   // start the next line once it can be read (hintVoicePoll asks again)
 if(!hintReadID||hintReadPlaying>=0)return;
 NSArray<NSString *> *lines=hintAnswerLines();
 if(hintReadLine<(NSInteger)(hintPage*hintPageLines()))hintReadLine=hintPage*hintPageLines();   // the player turned ahead
 if(hintReadLine>=(NSInteger)lines.count){   // all read once the answer is complete
  if(!hintWorking&&hintDone&&lines.count){hintReadID=hintReadEngine=nil;hintReadSystem=NO;}
  return;
 }
 NSString *file=nil;
 if(!hintReadSystem){
  NSDictionary *reply=hintJSON(hintPath(@"hint-voice.json"));
  if(![reply[@"id"] isEqual:hintReadID])return;
  if([reply[@"engine"] isKindOfClass:NSString.class])hintReadEngine=reply[@"engine"];
  NSArray *files=reply[@"files"];
  if([files isKindOfClass:NSArray.class]&&hintReadLine<(NSInteger)files.count&&[files[hintReadLine] isKindOfClass:NSString.class])file=files[hintReadLine];
  else if([reply[@"status"] isEqual:@"system"]){   // no voice in the service, or it failed: the system voice goes on
   hintReadSystem=YES;
   NSString *local=reply[@"local"];
   if([hintVoiceConfig()[@"engine"] isEqual:@"local"]&&[local isKindOfClass:NSString.class]&&!hintSetupID){
    if([local isEqual:@"missing"])hintShowSetup(@"下载语音");
    if([local isEqual:@"no_reference"])hintShowSetup(@"录我的声音");
   }
  }
  else return;   // this line's audio is still being made
 }
 if(hintReadSystem&&!hintLineFinished(lines,hintReadLine))return;
 if(hintReadLine/(NSInteger)hintPageLines()>(NSInteger)hintPage){hintPage=hintReadLine/hintPageLines();hintShowPage();}   // the page follows the voice
 if(file){
  hintPlayer=[[AVAudioPlayer alloc] initWithContentsOfURL:[NSURL fileURLWithPath:file] error:nil];
  hintPlayer.delegate=(id)hintActions;if(hintTestMode())hintPlayer.volume=0;   // a test session reads silently
  if([hintPlayer play])hintReadPlaying=hintReadLine;else{hintReadSystem=YES;hintPlayer=nil;}
  if(hintReadPlaying>=0)return;
 }
 if(!hintSpeaker){hintSpeaker=[AVSpeechSynthesizer new];hintSpeaker.delegate=(id)hintActions;}
 AVSpeechUtterance *utterance=[AVSpeechUtterance speechUtteranceWithString:lines[hintReadLine]];
 utterance.voice=hintSystemVoice();if(hintTestMode())utterance.volume=0;
 hintReadPlaying=hintReadLine;[hintSpeaker speakUtterance:utterance];
}
static void hintReadBegin(NSString *jobID,BOOL sendLines){
 hintReadStop();
 hintReadID=jobID;hintReadLine=hintPage*hintPageLines();
 hintReadSystem=!hintService.running;   // answers come from the service, so it runs; never start it just to read
 if(sendLines&&!hintReadSystem){
  NSArray<NSString *> *lines=hintAnswerLines();
  if(lines.count)hintVoiceWrite(@{@"id":jobID,@"lines":lines});
 }
 hintReadTick();
}
static void hintReadFollow(NSString *requestID){hintReadBegin(requestID,NO);}   // the service reads it as it streams
static void hintReadAnswer(void){   // the answer on screen, from its page on (朗读 switched on, or after the answer)
 if(hintDone&&hintPagedAnswer)hintReadBegin(NSUUID.UUID.UUIDString,YES);
}
static void hintReadPanelClosed(void){   // the local clone needs the paused game's GPU; the others read on
 if(!hintReadSystem&&![hintReadEngine isEqual:@"google"])hintReadStop();
}
static void hintShowSetup(NSString *title){
 hintVoiceSetup.title=title?:@"";hintVoiceSetup.hidden=!title;hintLayout(0);
}
static BOOL hintPageNext(void){
 if(!hintPagesRemain())return NO;
 hintPage++;hintShowPage();
 if(hintReadID){hintReadHalt();hintReadLine=hintPage*hintPageLines();hintReadTick();}   // the voice moves with the player
 return YES;
}
static void hintReadFinished(void){
 hintReadPlaying=-1;hintReadLine++;hintReadTick();
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
    if(([status isEqual:@"installed"]||[status isEqual:@"reference_saved"])&&hintReadOn()&&hintDone)
     hintReadAnswer();   // the page on screen again, in the new voice
   }
  }
 }
 hintReadTick();
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
 (void)flag;dispatch_async(dispatch_get_main_queue(),^{if(player==hintPlayer){hintPlayer=nil;hintReadFinished();}});
}
-(void)speechSynthesizer:(AVSpeechSynthesizer *)synthesizer didFinishSpeechUtterance:(AVSpeechUtterance *)utterance{
 (void)synthesizer;(void)utterance;dispatch_async(dispatch_get_main_queue(),^{if(hintReadPlaying>=0&&!hintPlayer)hintReadFinished();});
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
