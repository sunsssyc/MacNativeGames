#ifndef TOTK_COMPANION_ACTIVITY_H
#define TOTK_COMPANION_ACTIVITY_H
#include "player_activity.h"
typedef enum { PET_IDLE,PET_WALK,PET_RUN,PET_JUMP,PET_FALL,PET_GLIDE,PET_LAND,PET_COMBAT,PET_COMBAT_RUN } PetActivity;
// Shared with sprite playback: finish the recovery before returning to locomotion.
#define PET_LAND_SECONDS .30
typedef struct {
 PetActivity state,pending;double since,last,last_valid,grounded_since,land_until;uint64_t actor,observation;double changed;uint32_t generation;int was_air,falling;
} PetActivityTracker;
static inline const char *pet_activity_name(PetActivity state){
 const char *names[]={"idle","walk","run","jump","fall","glide","land","combat","combat_run"};
 return state>=PET_IDLE&&state<=PET_COMBAT_RUN?names[state]:"idle";
}
/* Ten samples/second. The observation's age is supplied independently of polling time.
   A single failed read gets at most 180 ms grace; paused/old samples reset immediately. */
static inline PetActivity pet_activity_update(PetActivityTracker *t,const RuntimePlayerActivity *a,double sample_time,double now){
 if(!isfinite(now)||!isfinite(sample_time)||now-sample_time>.3||now<sample_time||now<t->last){memset(t,0,sizeof *t);return PET_IDLE;}
 if(!a||!a->valid){
  if(t->actor&&now-t->last_valid<=.18)return t->state;
  memset(t,0,sizeof *t);return PET_IDLE;
 }
 if(!a->active){memset(t,0,sizeof *t);return PET_IDLE;}
 if(t->actor!=a->actor||t->generation!=a->generation||now-t->last>.4){
  memset(t,0,sizeof *t);t->actor=a->actor;t->generation=a->generation;
 }
 if(t->observation!=a->observation||!t->changed){t->observation=a->observation;t->changed=now;}
 t->last=t->last_valid=now;
 // In-game menus can retain an active Actor and old airborne/velocity flags.
 // Stop reacting if the whole AS sample plus position has stopped changing.
 if(now-t->changed>.6){t->state=t->pending=PET_IDLE;t->was_air=0;t->land_until=0;return PET_IDLE;}
 PetActivity desired=PET_IDLE;
 if(a->water||a->riding){t->was_air=t->falling=0;t->grounded_since=t->land_until=0;}
 else if(a->airborne||a->gliding){
  // One-way apex: noise around zero must not restart jump/fall clips.
  if(!t->was_air)t->falling=a->velocity[1]<=.5;
  else if(a->velocity[1]<-.5)t->falling=1;
  desired=a->gliding?PET_GLIDE:t->falling?PET_FALL:PET_JUMP;
  t->was_air=1;t->grounded_since=t->land_until=0;
 }else{
  if(t->was_air){
   if(!t->grounded_since)t->grounded_since=now;
   if(now-t->grounded_since<.08)return t->state; // confirm contact across two samples
   t->land_until=now+PET_LAND_SECONDS;t->was_air=t->falling=0;t->grounded_since=0;
  }
  int moving=a->speed>(t->state==PET_WALK||t->state==PET_RUN||t->state==PET_COMBAT_RUN?.25:.55);
  int running=a->speed>(t->state==PET_RUN?3.0:3.8);
  desired=now<t->land_until?PET_LAND:(a->combat||a->aiming)?(moving?PET_COMBAT_RUN:PET_COMBAT):moving?(running?PET_RUN:PET_WALK):PET_IDLE;
 }
 if(desired==PET_LAND||desired==PET_JUMP||desired==PET_FALL||desired==PET_GLIDE){t->state=t->pending=desired;t->since=now;}
 else if(t->state==PET_LAND){t->state=t->pending=desired;t->since=now;}
 else if(desired!=t->pending){t->pending=desired;t->since=now;}
 else if(now-t->since>=.12)t->state=desired;
 return t->state;
}
#endif
