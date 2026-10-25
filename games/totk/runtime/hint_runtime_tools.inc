/* Request/reply bridge for small, composable runtime tools. No arbitrary memory writes. A press is taken only for the
   request in flight that the player allowed to act (hintActionsGranted), at most hintActionLimit per request (the panel
   and assistant.json decide that number); state and stop are always answered. Each state reply carries "changes": what
   appeared, vanished or moved since the previous observation, so a run of inputs can be checked for an effect. */
#include "live_scene.h"
extern int runtime_live_player(float xyz[3]) __attribute__((weak_import));
extern int runtime_live_scene(RuntimeScene *out, float radius) __attribute__((weak_import));
extern void runtime_input_key_synthetic(unsigned code,int down) __attribute__((weak_import));
static NSString *runtimeSeen;
static NSInteger runtimeHeld=-1;
static NSUInteger runtimeActionGeneration;
static BOOL runtimeRestorePause;   // the panel held the game's pause when the press began (hintPauseHeld): put it back after
static NSArray *runtimeSteps;          // the 30..1000 ms presses of one sequence, one after another
static NSString *runtimeStepsID;
static NSUInteger runtimeStepsIndex;
static BOOL hintRuntimeActive(void){return runtimeHeld>=0||runtimeStepsID!=nil;}
static NSDictionary *hintRuntimeButtons(void){
 return @{@"a":@38,@"b":@40,@"x":@34,@"y":@32,@"l":@12,@"r":@14,@"zl":@58,@"zr":@56,@"plus":@36,@"minus":@48,@"up":@17,
          @"down":@5,@"left":@3,@"right":@4,@"forward":@13,@"backward":@1,@"strafe_left":@0,@"strafe_right":@2,
          @"look_left":@123,@"look_right":@124,@"look_up":@126,@"look_down":@125};
}
static NSDictionary *hintRuntimeState(void){
 float xyz[3]={0};int present=runtime_live_player?runtime_live_player(xyz):-1;
 NSMutableDictionary *s=[@{@"source":@"live_runtime",@"pid":@(getpid()),@"sample_time":@(NSDate.date.timeIntervalSince1970),
 @"player_present":@(present==1),@"world_state":@"unknown",
 @"note":@"Player objects may exist on the title screen; presence and position do not establish gameplay. Scene, health and live quests are unknown",
 @"assistant_paused":@(hintPauseHeld),@"action_active":@(hintRuntimeActive()),@"health":[NSNull null],@"quests":[NSNull null]} mutableCopy];
 RuntimePlayerActivity activity={0};
 if(runtime_live_activity&&runtime_live_activity(&activity)&&activity.valid){
  s[@"player_activity"]=@{@"source":@"player_animation_blackboard",@"action":@(activity.action),@"active":@(activity.active),
   @"speed_xz":@(activity.speed),@"vertical_velocity":@(activity.velocity[1]),@"airborne":@(activity.airborne),
   @"in_water":@(activity.water),@"combat_stance":@(activity.combat),@"aiming":@(activity.aiming),@"gliding":@(activity.gliding),@"standing_ride":@(activity.riding)};
 }
 if(present==1)s[@"position"]=@[@(xyz[0]),@(xyz[1]),@(xyz[2])];
 // The player's facing, the camera and the actors within 150 m (world_survey.c, 1.4.3); the assistant names them.
 RuntimeScene scene;
 if(present==1&&runtime_live_scene&&runtime_live_scene(&scene,150)==1){
  s[@"facing"]=@[@(scene.rot[2]),@(scene.rot[5]),@(scene.rot[8])];
  if(scene.has_camera)s[@"camera"]=@[@(scene.camera[0]),@(scene.camera[1]),@(scene.camera[2])];
  if(scene.has_cam_rot)s[@"camera_facing"]=@[@(-scene.cam_rot[2]),@(-scene.cam_rot[5]),@(-scene.cam_rot[8])];   // the camera looks down its own -Z
  s[@"actor_table"]=@(scene.table);
  NSMutableArray *nearby=[NSMutableArray new];
  for(int k=0;k<scene.actors;k++){
   RuntimeActor *a=&scene.near[k];
   [nearby addObject:@{@"name":@(a->name)?:@"?",@"position":@[@(a->xyz[0]),@(a->xyz[1]),@(a->xyz[2])],@"distance":@(round(a->distance*10)/10)}];
  }
  s[@"nearby"]=nearby;
 }
 return s;
}
/* What changed since the previous state reply: the game's own record of whether an input did anything. Names are the
   key (the table holds one actor per placed object); a name that moved more than 1.5 m counts as moved. */
static char changeName[40][48];
static float changePos[40][3];
static int changeCount=0;
static BOOL changeReady=NO;
static NSDictionary *hintRuntimeChanges(NSArray *nearby){
 if(![nearby isKindOfClass:NSArray.class])return nil;
 NSMutableArray *appeared=[NSMutableArray new],*vanished=[NSMutableArray new],*moved=[NSMutableArray new];
 BOOL seen[40]={NO};
 for(NSDictionary *a in nearby){
  NSString *name=a[@"name"];NSArray *p=a[@"position"];
  if(![name isKindOfClass:NSString.class]||![p isKindOfClass:NSArray.class]||p.count!=3)continue;
  int match=-1;
  for(int i=0;i<changeCount;i++)if(!strcmp(changeName[i],name.UTF8String)){match=i;break;}
  if(match<0){if(appeared.count<6)[appeared addObject:name];continue;}
  seen[match]=YES;
  float dx=[p[0] floatValue]-changePos[match][0],dy=[p[1] floatValue]-changePos[match][1],dz=[p[2] floatValue]-changePos[match][2];
  if(dx*dx+dy*dy+dz*dz>2.25f&&moved.count<6)[moved addObject:@{@"name":name,@"meters":@(roundf(sqrtf(dx*dx+dy*dy+dz*dz)*10)/10)}];
 }
 for(int i=0;i<changeCount;i++)if(!seen[i]&&vanished.count<6)[vanished addObject:@(changeName[i])];
 changeCount=0;
 for(NSDictionary *a in nearby){
  NSString *name=a[@"name"];NSArray *p=a[@"position"];
  if(![name isKindOfClass:NSString.class]||![p isKindOfClass:NSArray.class]||p.count!=3||changeCount>=40)continue;
  strlcpy(changeName[changeCount],name.UTF8String,sizeof changeName[0]);
  for(int k=0;k<3;k++)changePos[changeCount][k]=[p[k] floatValue];
  changeCount++;
 }
 if(!changeReady){changeReady=YES;return nil;}   // the first observation is the baseline, not a change
 if(!appeared.count&&!vanished.count&&!moved.count)return nil;
 return @{@"appeared":appeared,@"vanished":vanished,@"moved":moved,
          @"note":@"since the previous observation; omit an empty list when reading this"};
}
static void hintRuntimeReply(NSString *id,NSString *error){
 NSDictionary *state=hintRuntimeState();
 NSMutableDictionary *reply=[@{@"id":id,@"ok":@(!error),@"error":error?:@"",@"state":state} mutableCopy];
 NSDictionary *changes=hintRuntimeChanges(state[@"nearby"]);
 if(changes)reply[@"changes"]=changes;
 NSData *data=[NSJSONSerialization dataWithJSONObject:reply options:0 error:nil];
 [data writeToFile:hintPath(@"runtime-response.json") options:NSDataWritingAtomic error:nil];
}
static void hintRuntimeRelease(void){
 if(runtimeHeld>=0&&runtime_input_key_synthetic)runtime_input_key_synthetic((unsigned)runtimeHeld,0);
 runtimeHeld=-1;
}
static void hintRuntimeRestore(void){
 if(runtimeRestorePause&&hintPauseHeld&&runtime_assistant_pause)runtime_assistant_pause(1);   // back to the pause the panel still holds
 runtimeRestorePause=NO;
}
static void hintRuntimeStop(void){
 runtimeActionGeneration++;
 NSString *pending=runtimeStepsID;
 runtimeSteps=nil;runtimeStepsID=nil;runtimeStepsIndex=0;
 hintRuntimeRelease();hintRuntimeRestore();
 if(pending)hintRuntimeReply(pending,@"interrupted");   // Esc, a closed panel or a new request stopped a sequence
}
/* One 30..1000 ms press, then the step's wait, then the next step; the panel's pause is released for the whole sequence
   and restored at its end. Every step counts against the request's budget and is checked before it is sent. */
static void hintRuntimeSequenceFinish(NSString *error){
 NSString *id=runtimeStepsID;runtimeSteps=nil;runtimeStepsID=nil;runtimeStepsIndex=0;
 hintRuntimeRelease();hintRuntimeRestore();
 hintRuntimeReply(id,error);
}
static void hintRuntimeSequencePress(void){
 if(!runtimeStepsID)return;
 if(!hintActionsGranted||!hintWorking){hintRuntimeSequenceFinish(@"actions_not_allowed");return;}
 if(runtimeStepsIndex>=runtimeSteps.count){hintRuntimeSequenceFinish(nil);return;}
 if(hintActionCount>=hintActionLimit){hintRuntimeSequenceFinish(@"action_limit");return;}
 NSDictionary *step=runtimeSteps[runtimeStepsIndex++];
 NSNumber *code=hintRuntimeButtons()[step[@"button"]];double ms=[step[@"duration_ms"] doubleValue];double wait=[step[@"wait_ms"] doubleValue];
 if(!code||ms<30||ms>1000||wait<0||wait>1000){hintRuntimeSequenceFinish(@"invalid_button_or_duration");return;}
 hintActionCount++;
 runtimeHeld=code.integerValue;NSUInteger generation=++runtimeActionGeneration;
 runtime_input_key_synthetic((unsigned)runtimeHeld,1);
 dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(ms*NSEC_PER_MSEC)),dispatch_get_main_queue(),^{
  if(generation!=runtimeActionGeneration||!runtimeStepsID){hintRuntimeRelease();return;}
  hintRuntimeRelease();
  dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(wait*NSEC_PER_MSEC)),dispatch_get_main_queue(),^{
   if(generation!=runtimeActionGeneration)return;
   hintRuntimeSequencePress();
  });
 });
}
static void hintRuntimePoll(void){
 NSDictionary *q=hintJSON(hintPath(@"runtime-request.json"));NSString *id=q[@"id"],*op=q[@"op"];
 if(![id isKindOfClass:NSString.class]||[id isEqual:runtimeSeen])return;runtimeSeen=id;
 if(fabs(NSDate.date.timeIntervalSince1970-[q[@"time"] doubleValue])>5){hintRuntimeReply(id,@"stale_request");return;}
 if([op isEqual:@"state"]){hintRuntimeReply(id,nil);return;}
 if([op isEqual:@"stop"]){hintRuntimeStop();hintRuntimeReply(id,nil);return;}
 if([op isEqual:@"sequence"]){
  NSArray *steps=q[@"steps"];
  if(![steps isKindOfClass:NSArray.class]||steps.count<1||steps.count>8){hintRuntimeReply(id,@"invalid_steps");return;}
  for(NSDictionary *step in steps){
   if(![step isKindOfClass:NSDictionary.class]||!hintRuntimeButtons()[step[@"button"]]||
      [step[@"duration_ms"] doubleValue]<30||[step[@"duration_ms"] doubleValue]>1000||
      ![step[@"wait_ms"] isKindOfClass:NSNumber.class]||[step[@"wait_ms"] doubleValue]<0||[step[@"wait_ms"] doubleValue]>1000){
    hintRuntimeReply(id,@"invalid_steps");return;}
  }
  if(!hintActionsGranted||!hintWorking){hintRuntimeReply(id,@"actions_not_allowed");return;}
  if(runtimeStepsID||runtimeHeld>=0){hintRuntimeReply(id,@"action_busy");return;}
  if(hintActionCount+steps.count>hintActionLimit){hintRuntimeReply(id,@"action_limit");return;}
  runtimeSteps=steps;runtimeStepsID=id;runtimeStepsIndex=0;
  runtimeRestorePause=hintPauseHeld;if(runtimeRestorePause&&runtime_assistant_pause)runtime_assistant_pause(0);
  hintSceneReady=NO;hintMarksHide();   // the game moves: the frame on screen is no longer the saved one
  hintRuntimeSequencePress();return;
 }
 if(![op isEqual:@"press"]){hintRuntimeReply(id,@"unknown_operation");return;}
 NSNumber *code=hintRuntimeButtons()[q[@"button"]];double ms=[q[@"duration_ms"] doubleValue];
 if(!code||ms<30||ms>1000||!runtime_input_key_synthetic){hintRuntimeReply(id,@"invalid_button_or_duration");return;}
 if(!hintActionsGranted||!hintWorking){hintRuntimeReply(id,@"actions_not_allowed");return;}
 if(hintActionCount>=hintActionLimit){hintRuntimeReply(id,@"action_limit");return;}
 if(runtimeHeld>=0||runtimeStepsID){hintRuntimeReply(id,@"action_busy");return;}
 hintActionCount++;
 runtimeRestorePause=hintPauseHeld;if(runtimeRestorePause&&runtime_assistant_pause)runtime_assistant_pause(0);
 hintSceneReady=NO;hintMarksHide();
 runtimeHeld=code.integerValue;NSUInteger generation=++runtimeActionGeneration;
 runtime_input_key_synthetic((unsigned)runtimeHeld,1);
 dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(ms*NSEC_PER_MSEC)),dispatch_get_main_queue(),^{
  if(generation!=runtimeActionGeneration){hintRuntimeReply(id,@"interrupted");return;}
  hintRuntimeStop();hintRuntimeReply(id,nil);
 });
}
