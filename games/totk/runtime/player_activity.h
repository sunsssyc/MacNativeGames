#ifndef TOTK_PLAYER_ACTIVITY_H
#define TOTK_PLAYER_ACTIVITY_H
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <string.h>
/* Live AS blackboard, TOTK 1.4.3 only. No controller-input or save-file inference. */
typedef struct {
 uint64_t actor, observation; uint32_t generation;
 float speed, velocity[3];
 int valid, active, airborne, water, combat, aiming, gliding, riding;
 char action[64]; /* primary AS command, read with controller/blackboard ownership guards */
 int diagnostic; /* 1 actor, 2 AS component, 3 controller, 4 schema, 5 values, 6 changed */
} RuntimePlayerActivity;
typedef int (*ActivityRead)(uintptr_t,void *,size_t);
static inline uintptr_t activity_ptr(ActivityRead read,uintptr_t at){uintptr_t p=0;return at&&read(at,&p,8)?p:0;}
static inline int activity_array(ActivityRead read,uintptr_t bb,unsigned offset,uint32_t count,void *out,size_t bytes){
 uintptr_t p=activity_ptr(read,bb+offset);uint32_t n=0;
 return p&&read(p,&n,4)&&n==count&&read(p+4,out,bytes);
}
static inline int activity_decode143(ActivityRead read,uintptr_t actor,RuntimePlayerActivity *out){
 RuntimePlayerActivity a={0};a.diagnostic=1;*out=a;
 uint32_t state=0,count=0,id=0;
 if(!actor||!read(actor+0x24,&state,4)||state>11||!read(actor+0x10,&id,4)||!read(actor+0x220,&count,4)||count<9||count>256)return 0;
 a.actor=actor;a.generation=id;a.active=state==3||state==4;a.diagnostic=2;*out=a;
 uintptr_t components=activity_ptr(read,actor+0x228),component=components?activity_ptr(read,components+8*8):0;
 if(!component||activity_ptr(read,component+0x90)!=actor)return 0;
 a.diagnostic=3;*out=a;
 uintptr_t set=activity_ptr(read,component+0x18),controller=set?activity_ptr(read,set+0x18):0,bb=controller?activity_ptr(read,controller+0x40):0;
 if(!bb)return 0;
 a.diagnostic=4;*out=a;
 uint8_t flags[65];float floats[77],vel[3];int32_t ints[15];
 if(!activity_array(read,bb,0x18,15,ints,sizeof ints)||!activity_array(read,bb,0x20,77,floats,sizeof floats)||!activity_array(read,bb,0x28,65,flags,sizeof flags)||!activity_array(read,bb,0x30,1,vel,sizeof vel))return 0;
 // Verified on 1.4.3: controller slot 0 is the primary animation graph instance.
 // The instance owns its command name and points back to this controller and BB.
 uint32_t slots=0;uintptr_t entries=activity_ptr(read,controller+0x20);
 uintptr_t instance=entries?activity_ptr(read,entries):0;
 uintptr_t command=instance?activity_ptr(read,instance+0x10):0;
 if(!read(controller+0x18,&slots,4)||slots!=7||!instance||!command||
    activity_ptr(read,instance+0x28)!=bb||activity_ptr(read,instance+0x90)!=controller)return 0;
 unsigned len=0;
 for(;len<sizeof a.action;len++){
  unsigned char ch=0;if(!read(command+len,&ch,1))return 0;
  if(!ch)break;
  if(!((ch>='A'&&ch<='Z')||(ch>='a'&&ch<='z')||(ch>='0'&&ch<='9')||ch=='_'))return 0;
  a.action[len]=(char)ch;
 }
 if(!len||len==sizeof a.action||activity_ptr(read,instance+0x10)!=command||activity_ptr(read,entries)!=instance)return 0;
 a.diagnostic=5;*out=a;
 for(unsigned i=0;i<65;i++)if(flags[i]>1)return 0;
 for(unsigned i=0;i<3;i++)if(!isfinite(vel[i])||fabsf(vel[i])>150)return 0;
 if(!isfinite(floats[4])||floats[4]<0||floats[4]>150)return 0;
 a.diagnostic=6;*out=a;
 uint32_t afterID=0,afterState=0;
 if(!read(actor+0x10,&afterID,4)||afterID!=id||!read(actor+0x24,&afterState,4)||afterState!=state||activity_ptr(read,set+0x18)!=controller||activity_ptr(read,controller+0x40)!=bb)return 0;
 // A successful memory read is not proof that the game is updating it. Include
 // world position so steady-speed travel stays fresh even when AS values are constant.
 float position[3];if(!read(actor+0x2b4,position,sizeof position))return 0;
 for(unsigned i=0;i<3;i++)if(!isfinite(position[i]))return 0;
 uint64_t hash=14695981039346656037ull;
 const void *parts[]={ints,floats,flags,vel,position,a.action};const size_t sizes[]={sizeof ints,sizeof floats,sizeof flags,sizeof vel,sizeof position,sizeof a.action};
 for(unsigned k=0;k<6;k++)for(size_t j=0;j<sizes[k];j++){hash^=((const unsigned char *)parts[k])[j];hash*=1099511628211ull;}
 a.observation=hash;
 a.speed=floats[4];memcpy(a.velocity,vel,sizeof vel);
 a.airborne=flags[14];a.water=flags[15]||flags[41];a.combat=flags[16];a.aiming=flags[19];
 a.gliding=flags[45]||flags[46]||flags[47];a.riding=flags[63];a.valid=1;a.diagnostic=0;*out=a;return 1;
}
#endif
