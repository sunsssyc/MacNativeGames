#include <assert.h>
#include <stdio.h>
#include "../games/totk/runtime/companion_activity.h"
static unsigned char memory[8192];
static int read_fake(uintptr_t p,void *out,size_t size){if(p<0x1000||p>0x1000+sizeof memory-size)return 0;memcpy(out,memory+p-0x1000,size);return 1;}
static void put(uintptr_t p,const void *v,size_t n){memcpy(memory+p-0x1000,v,n);}
static void u32(uintptr_t p,uint32_t v){put(p,&v,4);}
static void ptr(uintptr_t p,uintptr_t v){put(p,&v,8);}
int main(void){
 const uintptr_t actor=0x1000,components=0x1500,component=0x1600,set=0x1800,controller=0x1900,bb=0x1a00;
 u32(actor+0x24,4);u32(actor+0x10,17);u32(actor+0x220,32);ptr(actor+0x228,components);ptr(components+64,component);
 ptr(component+0x90,actor);ptr(component+0x18,set);ptr(set+0x18,controller);ptr(controller+0x40,bb);
 ptr(bb+0x18,0x1b00);u32(0x1b00,15);ptr(bb+0x20,0x1c00);u32(0x1c00,77);
 ptr(bb+0x28,0x1e00);u32(0x1e00,65);ptr(bb+0x30,0x1f00);u32(0x1f00,1);
 u32(controller+0x18,7);ptr(controller+0x20,0x2200);ptr(0x2200,0x2300);
 ptr(0x2300+0x10,0x2500);ptr(0x2300+0x28,bb);ptr(0x2300+0x90,controller);
 put(0x2500,"Wait",5);
 RuntimePlayerActivity a;assert(activity_decode143(read_fake,actor,&a)&&a.active&&a.valid);
 memory[0xe00+4+14]=1;assert(activity_decode143(read_fake,actor,&a)&&a.airborne);
 memory[0xe00+4+14]=2;assert(!activity_decode143(read_fake,actor,&a)&&!a.valid);
 memory[0xe00+4+14]=0;u32(0x1c00,78);assert(!activity_decode143(read_fake,actor,&a));u32(0x1c00,77);
 ptr(component+0x90,0x1008);assert(!activity_decode143(read_fake,actor,&a));ptr(component+0x90,actor);
 ptr(set+0x18,0xffff);assert(!activity_decode143(read_fake,actor,&a));ptr(set+0x18,controller);
 assert(activity_decode143(read_fake,actor,&a));
 assert(!strcmp(a.action,"Wait"));
 ptr(0x2300+0x90,controller+8);assert(!activity_decode143(read_fake,actor,&a));ptr(0x2300+0x90,controller);
 ptr(0x2300+0x28,bb+8);assert(!activity_decode143(read_fake,actor,&a));ptr(0x2300+0x28,bb);
 u32(controller+0x18,8);assert(!activity_decode143(read_fake,actor,&a));u32(controller+0x18,7);
 memset(memory+0x1500,'X',64);assert(!activity_decode143(read_fake,actor,&a));put(0x2500,"Wait",5);
 assert(activity_decode143(read_fake,actor,&a));a.action[0]=0;
 PetActivityTracker t={0};double now=1;
 #define STEP(dt) (a.observation++,now+=(dt),pet_activity_update(&t,&a,now,now))
 assert(STEP(.1)==PET_IDLE);a.speed=2;STEP(.1);assert(STEP(.15)==PET_WALK);
 a.speed=5;STEP(.1);assert(STEP(.15)==PET_RUN);a.speed=3.5;assert(STEP(.1)==PET_RUN);
 a.airborne=1;a.velocity[1]=3;assert(STEP(.1)==PET_JUMP);
 a.velocity[1]=-2;assert(STEP(.1)==PET_FALL);a.gliding=1;assert(STEP(.1)==PET_GLIDE);
 a.gliding=a.airborne=0;a.speed=0;assert(STEP(.1)==PET_GLIDE);assert(STEP(.1)==PET_LAND);
 assert(STEP(.1)==PET_LAND);assert(STEP(.11)==PET_IDLE);
 // Recovery ends on the first eligible sample; do not debounce locomotion again.
 a.airborne=1;a.velocity[1]=-2;a.speed=5;assert(STEP(.1)==PET_FALL);
 a.airborne=0;assert(STEP(.1)==PET_FALL);assert(STEP(.1)==PET_LAND);
 assert(STEP(.1)==PET_LAND);assert(STEP(.11)==PET_RUN);
 // A new jump interrupts recovery immediately, even in a rapid jump sequence.
 a.airborne=1;a.velocity[1]=3;assert(STEP(.1)==PET_JUMP);
 a.airborne=0;STEP(.1);assert(STEP(.1)==PET_LAND);
 a.airborne=1;assert(STEP(.05)==PET_JUMP);
 a.airborne=0;a.speed=0;STEP(.1);assert(STEP(.1)==PET_LAND);assert(STEP(.31)==PET_IDLE);
 a.combat=1;STEP(.1);assert(STEP(.15)==PET_COMBAT);
 a.speed=4;STEP(.1);assert(STEP(.15)==PET_COMBAT_RUN);
 a.active=0;assert(STEP(.1)==PET_IDLE);a.active=1;
 assert(pet_activity_update(&t,&a,now-1,now)==PET_IDLE);
 a.generation++;assert(STEP(.1)==PET_IDLE);
 a.water=1;assert(STEP(.15)==PET_IDLE);
 a.water=0;a.speed=5;STEP(.1);STEP(.15);
 now+=.2;assert(pet_activity_update(&t,&a,now,now)==PET_COMBAT_RUN);
 now+=.5;assert(pet_activity_update(&t,&a,now,now)==PET_IDLE);
 a.observation++;STEP(.1);assert(STEP(.15)==PET_COMBAT_RUN);
 // Apex jitter and one false contact cannot alternate jump/fall/land every sample.
 t=(PetActivityTracker){0};a.combat=0;a.speed=0;a.airborne=1;a.velocity[1]=3;
 assert(STEP(.1)==PET_JUMP);
 for(int i=0;i<6;i++){a.velocity[1]=i%2?.05:-.05;assert(STEP(.1)==PET_JUMP);}
 a.velocity[1]=-2;assert(STEP(.1)==PET_FALL);
 a.velocity[1]=.3;assert(STEP(.1)==PET_FALL);
 a.airborne=0;assert(STEP(.1)==PET_FALL);
 a.airborne=1;assert(STEP(.1)==PET_FALL);
 a.valid=0;assert(STEP(.1)==PET_FALL);assert(STEP(.1)==PET_IDLE);a.valid=1;
 a.airborne=0;STEP(.1);a.airborne=1;a.velocity[1]=4;assert(STEP(.1)==PET_JUMP);
 a.airborne=0;assert(STEP(.1)==PET_JUMP);assert(STEP(.1)==PET_LAND);
 a.active=0;assert(STEP(.01)==PET_IDLE);
 // Verified primary commands override misleading InAir and climbing velocity.
 a.active=1;a.airborne=1;a.speed=2;strcpy(a.action,"ClimbMove");a.velocity[1]=2;
 assert(STEP(.033)==PET_CLIMB);a.velocity[1]=-2;assert(STEP(.033)==PET_CLIMB);
 strcpy(a.action,"ClimbWait");a.velocity[1]=.000033f;assert(STEP(.033)==PET_CLIMB);
 strcpy(a.action,"WallOff");assert(STEP(.033)==PET_CLIMB);
 strcpy(a.action,"Fall");a.velocity[1]=-2;assert(STEP(.033)==PET_FALL);
 strcpy(a.action,"Land");a.airborne=0;assert(STEP(.033)==PET_LAND);
 strcpy(a.action,"Move");a.speed=5;assert(STEP(.033)==PET_RUN); // no extra landing hold
 strcpy(a.action,"Jump");a.velocity[1]=4;assert(STEP(.033)==PET_JUMP); // before InAir flips
 a.airborne=1;a.velocity[1]=0;assert(STEP(.033)==PET_JUMP);
 a.velocity[1]=-.2;assert(STEP(.033)==PET_FALL);
 a.velocity[1]=.05;assert(STEP(.033)==PET_FALL); // no apex chatter
 strcpy(a.action,"ClimbMove");assert(STEP(.033)==PET_CLIMB);
 strcpy(a.action,"Wait");a.airborne=0;a.speed=0;assert(STEP(.033)==PET_IDLE); // no fake landing
 strcpy(a.action,"UnknownAirAction");a.airborne=1;a.velocity[1]=-3;assert(STEP(.033)==PET_IDLE);
 // Grounded sword combos trigger once per command and stop immediately.
 a.airborne=0;a.combat=1;strcpy(a.action,"CutS1");assert(STEP(.033)==PET_ATTACK);
 double strike=t.attack_started;assert(STEP(.033)==PET_ATTACK&&t.attack_started==strike);
 strcpy(a.action,"CutS2");assert(STEP(.033)==PET_ATTACK&&t.attack_started>strike);
 strcpy(a.action,"Wait");assert(STEP(.033)==PET_COMBAT);
 strcpy(a.action,"WeaponEquipOn");assert(STEP(.033)==PET_COMBAT);
 strcpy(a.action,"ChargeWait");assert(STEP(.033)==PET_COMBAT);
 strcpy(a.action,"CutS1");a.airborne=1;assert(STEP(.033)==PET_IDLE);
 a.airborne=0;assert(STEP(.033)==PET_ATTACK);
 a.active=0;assert(STEP(.033)==PET_IDLE);
 puts("PASS: guarded layout, invalid reads, hysteresis, jump/land, combat, pause, stale data and actor replacement");
}
