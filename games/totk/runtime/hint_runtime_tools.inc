/* Request/reply bridge for small, composable runtime tools. No arbitrary memory writes. A press is taken only for the
   request in flight that the player allowed to act (hintActionsGranted), at most hintActionLimit per request; state and
   stop are always answered. */
#include "live_scene.h"
extern int runtime_live_player(float xyz[3]) __attribute__((weak_import));
extern int runtime_live_scene(RuntimeScene *out, float radius) __attribute__((weak_import));
extern void runtime_input_key_synthetic(unsigned code,int down) __attribute__((weak_import));
static NSString *runtimeSeen;
static NSInteger runtimeHeld=-1;
static NSUInteger runtimeActionGeneration;
static BOOL runtimeRestorePause;
static BOOL hintRuntimeActive(void){return runtimeHeld>=0;}
static NSDictionary *hintRuntimeState(void){
 float xyz[3]={0};int present=runtime_live_player?runtime_live_player(xyz):-1;
 NSMutableDictionary *s=[@{@"source":@"live_runtime",@"pid":@(getpid()),@"sample_time":@(NSDate.date.timeIntervalSince1970),
 @"player_present":@(present==1),@"world_state":@"unknown",
 @"note":@"Player objects may exist on the title screen; presence and position do not establish gameplay. Scene, health and live quests are unknown",
 @"assistant_paused":@(hintExpanded),@"action_active":@(runtimeHeld>=0),@"health":[NSNull null],@"quests":[NSNull null]} mutableCopy];
 if(present==1)s[@"position"]=@[@(xyz[0]),@(xyz[1]),@(xyz[2])];
 // The player's facing, the camera and the actors within 150 m (world_survey.c, 1.4.3); the assistant names them.
 RuntimeScene scene;
 if(present==1&&runtime_live_scene&&runtime_live_scene(&scene,150)==1){
  s[@"facing"]=@[@(scene.rot[2]),@(scene.rot[5]),@(scene.rot[8])];
  if(scene.has_camera)s[@"camera"]=@[@(scene.camera[0]),@(scene.camera[1]),@(scene.camera[2])];
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
static void hintRuntimeReply(NSString *id,NSString *error){
 NSDictionary *reply=@{@"id":id,@"ok":@(!error),@"error":error?:@"",@"state":hintRuntimeState()};
 NSData *data=[NSJSONSerialization dataWithJSONObject:reply options:0 error:nil];[data writeToFile:hintPath(@"runtime-response.json") options:NSDataWritingAtomic error:nil];
}
static void hintRuntimeStop(void){
 runtimeActionGeneration++;
 if(runtimeHeld>=0&&runtime_input_key_synthetic)runtime_input_key_synthetic((unsigned)runtimeHeld,0);
 runtimeHeld=-1;
 if(runtimeRestorePause&&hintExpanded&&runtime_assistant_pause)runtime_assistant_pause(1);
 runtimeRestorePause=NO;
}
static void hintRuntimePoll(void){
 NSDictionary *q=hintJSON(hintPath(@"runtime-request.json"));NSString *id=q[@"id"],*op=q[@"op"];
 if(![id isKindOfClass:NSString.class]||[id isEqual:runtimeSeen])return;runtimeSeen=id;
 if(fabs(NSDate.date.timeIntervalSince1970-[q[@"time"] doubleValue])>5){hintRuntimeReply(id,@"stale_request");return;}
 if([op isEqual:@"state"]){hintRuntimeReply(id,nil);return;}
 if([op isEqual:@"stop"]){hintRuntimeStop();hintRuntimeReply(id,nil);return;}
 if(![op isEqual:@"press"]){hintRuntimeReply(id,@"unknown_operation");return;}
 NSDictionary *buttons=@{@"a":@38,@"b":@40,@"x":@34,@"y":@32,@"l":@12,@"r":@14,@"zl":@58,@"zr":@56,@"plus":@36,@"minus":@48,@"up":@17,@"down":@5,@"left":@3,@"right":@4,@"forward":@13,@"backward":@1,@"strafe_left":@0,@"strafe_right":@2,@"look_left":@123,@"look_right":@124,@"look_up":@126,@"look_down":@125};
 NSNumber *code=buttons[q[@"button"]];double ms=[q[@"duration_ms"] doubleValue];
 if(!code||ms<30||ms>1000||!runtime_input_key_synthetic){hintRuntimeReply(id,@"invalid_button_or_duration");return;}
 if(!hintActionsGranted||!hintWorking){hintRuntimeReply(id,@"actions_not_allowed");return;}
 if(hintActionCount>=hintActionLimit){hintRuntimeReply(id,@"action_limit");return;}
 if(runtimeHeld>=0){hintRuntimeReply(id,@"action_busy");return;}
 hintActionCount++;
 runtimeRestorePause=hintExpanded;if(runtimeRestorePause&&runtime_assistant_pause)runtime_assistant_pause(0);
 hintSceneReady=NO;hintMarksHide();   // the game moves: the frame on screen is no longer the saved one
 runtimeHeld=code.integerValue;NSUInteger generation=++runtimeActionGeneration;
 runtime_input_key_synthetic((unsigned)runtimeHeld,1);
 dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(ms*NSEC_PER_MSEC)),dispatch_get_main_queue(),^{
  if(generation!=runtimeActionGeneration){hintRuntimeReply(id,@"interrupted");return;}
  hintRuntimeStop();hintRuntimeReply(id,nil);
 });
}
