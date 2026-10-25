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
 RuntimePlayerActivity a;assert(activity_decode143(read_fake,actor,&a)&&a.active&&a.valid);
 memory[0xe00+4+14]=1;assert(activity_decode143(read_fake,actor,&a)&&a.airborne);
 memory[0xe00+4+14]=2;assert(!activity_decode143(read_fake,actor,&a)&&!a.valid);
 memory[0xe00+4+14]=0;u32(0x1c00,78);assert(!activity_decode143(read_fake,actor,&a));u32(0x1c00,77);
 ptr(component+0x90,0x1008);assert(!activity_decode143(read_fake,actor,&a));ptr(component+0x90,actor);
 ptr(set+0x18,0xffff);assert(!activity_decode143(read_fake,actor,&a));ptr(set+0x18,controller);
 assert(activity_decode143(read_fake,actor,&a));
 PetActivityTracker t={0};double now=1;
 #define STEP(dt) (a.observation++,now+=(dt),pet_activity_update(&t,&a,now,now))
 assert(STEP(.1)==PET_IDLE);a.speed=2;STEP(.1);assert(STEP(.15)==PET_WALK);
 a.speed=5;STEP(.1);assert(STEP(.15)==PET_RUN);a.speed=3.5;assert(STEP(.1)==PET_RUN);
 a.airborne=1;a.velocity[1]=3;assert(STEP(.1)==PET_JUMP);
 a.velocity[1]=-2;assert(STEP(.1)==PET_FALL);a.gliding=1;assert(STEP(.1)==PET_GLIDE);
 a.gliding=a.airborne=0;a.speed=0;assert(STEP(.1)==PET_GLIDE);assert(STEP(.1)==PET_LAND);
 STEP(.25);STEP(.25);assert(STEP(.15)==PET_IDLE);
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
 for(int i=0;i<6;i++){a.velocity[1]=i%2?.2:-.2;assert(STEP(.1)==PET_JUMP);}
 a.velocity[1]=-2;assert(STEP(.1)==PET_FALL);
 a.velocity[1]=.3;assert(STEP(.1)==PET_FALL);
 a.airborne=0;assert(STEP(.1)==PET_FALL);
 a.airborne=1;assert(STEP(.1)==PET_FALL);
 a.valid=0;assert(STEP(.1)==PET_FALL);assert(STEP(.1)==PET_IDLE);a.valid=1;
 a.airborne=0;STEP(.1);a.airborne=1;a.velocity[1]=4;assert(STEP(.1)==PET_JUMP);
 a.airborne=0;assert(STEP(.1)==PET_JUMP);assert(STEP(.1)==PET_LAND);
 a.active=0;assert(STEP(.01)==PET_IDLE);
 puts("PASS: guarded layout, invalid reads, hysteresis, jump/land, combat, pause, stale data and actor replacement");
}
