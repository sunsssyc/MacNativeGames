/* The running game seen from memory, read-only, for the hint assistant (runtime_state in tools/hint_assistant):
   the player, the camera and the nearest actors. Read on the caller's thread while the game runs, so every pointer is
   checked on the way and a value may be one frame old. */
#pragma once

typedef struct { char name[48]; float xyz[3]; float distance; } RuntimeActor;
typedef struct {
    float player[3], rot[9];      /* rot: 3x3 row-major; its columns are the player's axes, the third the facing */
    float camera[3]; int has_camera;
    int table;                    /* slots in the game's actor table, 0 when it was not found (not 1.4.3, or moved) */
    int actors;                   /* entries in near, nearest first */
    RuntimeActor near[40];
} RuntimeScene;

/* 1: filled; 0: no player (title screen, loading); -1: not available here (other games and versions). Actors are
   within radius metres of the player, without the player, parked actors (at the origin), what sits on the player
   (within 1.5 m: worn and held gear, system actors) and cameras (the player camera is in camera). */
int runtime_live_scene(RuntimeScene *out, float radius);
