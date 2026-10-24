/* Companion presentation and click-to-record dictation. All state transitions run on AppKit's main queue. */
static AVAudioEngine *hintAudio;
static SFSpeechRecognizer *hintRecognizer;
static SFSpeechAudioBufferRecognitionRequest *hintRecognition;
static SFSpeechRecognitionTask *hintSpeechTask;
static NSUInteger hintVoiceGeneration;
static NSString *hintVoiceDraft;
static NSString *hintTranscript;
static void hintDockLayout(void){
 if(!hintDock)return;
 NSRect r=[hintGame convertRectToScreen:hintGame.contentView.bounds];
 NSFont *font=hintFont(13);
 NSMutableParagraphStyle *paragraph=[NSMutableParagraphStyle new];paragraph.lineSpacing=3;paragraph.lineBreakMode=NSLineBreakByWordWrapping;
 NSDictionary *style=@{NSFontAttributeName:font,NSForegroundColorAttributeName:hintInk(),NSParagraphStyleAttributeName:paragraph};
 /* Up to six lines, the answer's own limit (prompts.py MAX_LINES), measured by the cell that draws them: the fixed 80 pt
    held three lines of PingFang 13 with the 3 pt spacing and dropped the fourth without a mark (user, 2026-10-24), and a
    string measurement comes out shorter than the cell's own lines. Longer text ends in "…" on the last line (the cell
    truncates it); the whole answer is in the panel. */
 CGFloat textWidth=MIN(260,MAX(144,[hintBubble.stringValue sizeWithAttributes:style].width));
 NSString *text=hintBubble.stringValue;
 hintBubble.attributedStringValue=[[NSAttributedString alloc] initWithString:@"一\n一\n一\n一\n一\n一" attributes:style];
 CGFloat sixLines=ceil([hintBubble.cell cellSizeForBounds:NSMakeRect(0,0,textWidth,CGFLOAT_MAX)].height);
 hintBubble.attributedStringValue=[[NSAttributedString alloc] initWithString:text attributes:style];
 CGFloat need=ceil([hintBubble.cell cellSizeForBounds:NSMakeRect(0,0,textWidth,CGFLOAT_MAX)].height);
 CGFloat textHeight=MIN(sixLines,MAX(36,need));
 CGFloat bubbleWidth=textWidth+36,bubbleHeight=textHeight+24;
 CGFloat height=MAX(96,bubbleHeight+8),width=bubbleWidth+78;
 hintBubbleSurface.frame=NSMakeRect(0,(height-bubbleHeight)/2,bubbleWidth,bubbleHeight);
 hintBubble.frame=NSMakeRect(14,12,textWidth,textHeight);
 hintAvatar.frame=NSMakeRect(width-72,(height-92)/2,72,92);
 NSRect frame=NSMakeRect(NSMaxX(r)-width-24,NSMinY(r)+MAX(156,NSHeight(r)*0.29),width,height);
 if(!NSEqualRects(frame,hintDock.frame))[hintDock setFrame:frame display:YES];
 if(hintExpanded){if(hintDock.visible)[hintDock orderOut:nil];}
 else if(hintGame.visible&&!hintDock.visible){[hintGame addChildWindow:hintDock ordered:NSWindowAbove];[hintDock orderFront:nil];}
}
static void hintOpen(void){
 hintExpanded=YES;hintPause();
 if(![hintJSON(hintPath(@"assistant.json"))[@"enabled"] boolValue]){hintShowWelcome();return;}
 if(hintSession||hintWorking||hintDone){hintLayout(540);[hintPanel makeKeyWindow];[hintPanel makeFirstResponder:hintQuestion];}
 else hintShowReady();
}
static void hintVoiceNotice(NSString *message){
 hintBubble.stringValue=message;hintDisclosure.stringValue=message;hintDockLayout();
}
static void hintVoiceStopAudio(void){
 if(hintAudio){[hintAudio stop];[hintAudio.inputNode removeTapOnBus:0];hintAudio=nil;}
}
static void hintVoiceControls(BOOL active){
 hintQuestion.enabled=!active;hintMic.enabled=!hintVoiceFinishing;
 hintMic.title=hintListening?@"停止":@"语音";
 hintSend.enabled=!active&&hintQuestion.stringValue.length>0;
 hintEnable.hidden=active||hintWorking;hintHistoryButton.hidden=active||!hintHistory.count;
 hintRead.hidden=active;hintVoiceCancel.hidden=!active;
 hintVoiceCancel.frame=NSMakeRect(20,104,92,28);
}
static void hintVoiceSubmit(NSUInteger generation){
 if(generation!=hintVoiceGeneration||!hintVoiceFinishing)return;
 NSString *text=[hintTranscript stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
 hintVoiceStopAudio();hintVoiceFinishing=NO;hintListening=NO;hintVoiceGeneration++;
 [hintSpeechTask cancel];hintSpeechTask=nil;hintRecognition=nil;
 hintQuestion.stringValue=text.length?(hintVoiceDraft.length?[hintVoiceDraft stringByAppendingFormat:@" %@",text]:text):hintVoiceDraft?:@"";
 hintVoiceControls(NO);
 hintVoiceNotice(text.length?@"录音已停止 · 检查文字后点击发送":@"没有听清 · 可以重新录音或输入文字");
 [hintPanel makeFirstResponder:hintQuestion];
}
static void hintVoiceEnd(BOOL cancel){
 if(!hintListening&&!hintVoiceFinishing)return;
 hintVoiceStopAudio();hintListening=NO;
 if(cancel){hintVoiceGeneration++;hintVoiceFinishing=NO;[hintSpeechTask cancel];hintSpeechTask=nil;hintRecognition=nil;hintQuestion.stringValue=hintVoiceDraft?:@"";hintVoiceControls(NO);hintVoiceNotice(@"已取消录音 · 原有文字已保留");return;}
 hintVoiceFinishing=YES;hintVoiceControls(YES);[hintRecognition endAudio];hintVoiceNotice(@"麦克风已关闭 · 正在整理文字…");
 NSUInteger generation=hintVoiceGeneration;
 dispatch_after(dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC),dispatch_get_main_queue(),^{hintVoiceSubmit(generation);});
}
static void hintVoiceBegin(void){
 if(hintListening||hintVoiceFinishing||hintWorking)return;
 if(![hintJSON(hintPath(@"assistant.json"))[@"enabled"] boolValue]){hintOpen();return;}
 SFSpeechRecognizerAuthorizationStatus speech=[SFSpeechRecognizer authorizationStatus];
 if(speech==SFSpeechRecognizerAuthorizationStatusNotDetermined){
  hintVoiceNotice(@"首次使用需要语音识别授权。授权后再次点击语音。");
  [SFSpeechRecognizer requestAuthorization:^(SFSpeechRecognizerAuthorizationStatus status){dispatch_async(dispatch_get_main_queue(),^{hintVoiceNotice(status==SFSpeechRecognizerAuthorizationStatusAuthorized?@"语音识别已授权 · 再次点击语音继续":@"语音识别未授权 · 仍可点击露珠打字");});}];return;
 }
 if(speech!=SFSpeechRecognizerAuthorizationStatusAuthorized){hintVoiceNotice(@"语音识别未授权 · 可在系统设置中开启，或直接打字");return;}
 AVAuthorizationStatus mic=[AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio];
 if(mic==AVAuthorizationStatusNotDetermined){
  [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL allowed){dispatch_async(dispatch_get_main_queue(),^{hintVoiceNotice(allowed?@"麦克风已授权 · 点击语音开始":@"麦克风未授权 · 仍可点击露珠打字");});}];return;
 }
 if(mic!=AVAuthorizationStatusAuthorized){hintVoiceNotice(@"麦克风未授权 · 可在系统设置中开启，或直接打字");return;}
 hintRecognizer=[[SFSpeechRecognizer alloc] initWithLocale:[NSLocale localeWithLocaleIdentifier:@"zh-CN"]];
 if(!hintRecognizer.available||!hintRecognizer.supportsOnDeviceRecognition){hintVoiceNotice(@"本机中文语音识别暂不可用 · 请先输入文字");return;}
 hintRecognition=[SFSpeechAudioBufferRecognitionRequest new];hintRecognition.requiresOnDeviceRecognition=YES;hintRecognition.shouldReportPartialResults=YES;
 hintAudio=[AVAudioEngine new];AVAudioInputNode *input=hintAudio.inputNode;AVAudioFormat *format=[input outputFormatForBus:0];
 if(format.channelCount==0||format.sampleRate<=0){hintAudio=nil;hintVoiceNotice(@"未找到可用麦克风 · 请先输入文字");return;}
 SFSpeechAudioBufferRecognitionRequest *request=hintRecognition;
 [input installTapOnBus:0 bufferSize:1024 format:format block:^(AVAudioPCMBuffer *buffer,AVAudioTime *when){(void)when;[request appendAudioPCMBuffer:buffer];}];
 NSError *error=nil;[hintAudio prepare];if(![hintAudio startAndReturnError:&error]){hintVoiceStopAudio();hintVoiceNotice(@"麦克风暂时无法使用 · 请先输入文字");return;}
 hintVoiceDraft=[hintQuestion.stringValue copy];hintListening=YES;hintTranscript=@"";hintVoiceGeneration++;NSUInteger generation=hintVoiceGeneration;hintVoiceControls(YES);[hintPanel makeFirstResponder:nil];
 hintVoiceNotice(@"正在听… 点击停止结束 · Esc 取消");
 hintSpeechTask=[hintRecognizer recognitionTaskWithRequest:request resultHandler:^(SFSpeechRecognitionResult *result,NSError *failure){dispatch_async(dispatch_get_main_queue(),^{
  if(generation!=hintVoiceGeneration)return;
  if(result){hintTranscript=result.bestTranscription.formattedString;if(hintListening){hintQuestion.stringValue=hintVoiceDraft.length?[hintVoiceDraft stringByAppendingFormat:@" %@",hintTranscript]:hintTranscript;}}
  if(result.isFinal){hintVoiceStopAudio();hintListening=NO;hintVoiceFinishing=YES;hintVoiceSubmit(generation);}
  else if(failure){hintVoiceStopAudio();if(hintVoiceFinishing)hintVoiceSubmit(generation);else{hintVoiceEnd(YES);hintVoiceNotice(@"语音识别中断 · 请重试或输入文字");}}
 });}];
 dispatch_after(dispatch_time(DISPATCH_TIME_NOW,60*NSEC_PER_SEC),dispatch_get_main_queue(),^{if(generation==hintVoiceGeneration&&hintListening)hintVoiceEnd(NO);});
}
