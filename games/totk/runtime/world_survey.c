/* Live map survey for the selected TOTK version. No arbitrary memory writes and no raw position pokes.
   Offset leads: aquacluck/totk-lotuskit 59dcfcc; independently checked against our main in
   analysis/continuous-survey-entry-named.c. forceSetMatrix routes through the physics component,
   or queues a next transform, unlike merely changing the actor's displayed position.
   Only called after the actual game frame-end GPU wait, never from the input file thread. */
#include "world_survey.h"
#include "live_scene.h"
#include "player_activity.h"
#include "game_version.h"
#include <ctype.h>
#include <limits.h>
#include <mach/mach.h>
#include "mach_vm_compat.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifdef GAME_BOTW
int runtime_live_activity(RuntimePlayerActivity *out){memset(out,0,sizeof *out);return 0;}
int runtime_live_player(float xyz[3]){(void)xyz;return -1;}
int runtime_live_scene(RuntimeScene *out,float radius){(void)out;(void)radius;return -1;}
int runtime_live_facing(float player_rot[9],float camera_rot[9],float camera_pos[3]){(void)player_rot;(void)camera_rot;(void)camera_pos;return -1;}
/* Breath of the Wild 1.6.0: no frame-end hook (the survey sync object is never found, see runtime_survey_sync), so
   "survey pos" reads and "survey move" writes the player's position from the command thread. The pointer chains from
   main's data segment are the ones Bloom (Swiffy22) found for 1.6.0 (the botw-save-state tool uses them); the code is
   our own. Chains: Havok position = [[[main+0x2d37af0]+0xf0]+0xd28]+0x5e0 (float xyz);
                    world matrix   = [[main+0x2ca1140]+0x60]+0x398 (3x4 row-major, translation at [3], [7], [11]);
                    camera         = [[main+0x2ce1090]+0x60]+0x20 {position, look-at, up, fovy, ?, aspect}.
   Writing those two is not enough: the actor and the Havok object keep a dozen more copies of the position (feet,
   previous positions, swept transforms), so a move shifts every copy near the player by the same offset ("survey scan"
   lists them). A far place is not loaded, and the player freezes there; the move is therefore a flight at a speed the
   streaming keeps up with (2 m per frame worked, 8 m did not): survey move <tag> X Y Z <frames>, 1200 frames for 2.3 km.
   Verified on the Mac 2026-10-21 (5 m step: walks, camera follows; Hebra to Oman Au shrine: lands, in control). */
_Atomic int runtime_survey_pending;
const int32_t runtime_survey_sync[2] = {0, -1};   /* read by hle_nvn.c only once the survey found the system object, which it never does here */
void runtime_survey_tick(uint64_t frame) { (void)frame; }
void runtime_survey_cancel_user(void) { }
#if defined(GAME_BOTW160)
enum { HAVOK_ROOT = 0x2d37af0, HAVOK_STEP1 = 0xf0, HAVOK_STEP2 = 0xd28, HAVOK_POS = 0x5e0,
       MATRIX_ROOT = 0x2ca1140, MATRIX_STEP1 = 0x60, MATRIX_OFF = 0x398,
       CAMERA_ROOT = 0x2ce1090, CAMERA_STEP1 = 0x60, CAMERA_OFF = 0x20 };   /* camera pan matrix (same research) */
static uintptr_t survey_main;
static _Atomic int survey_enabled;
static int read_mem(uintptr_t address, void *out, size_t size) {
    if (!address || address > UINTPTR_MAX - size) return 0;
    mach_vm_size_t got = 0;
    return mach_vm_read_overwrite(mach_task_self(), address, size, (uintptr_t)out, &got) == KERN_SUCCESS && got == size;
}
static uintptr_t read_ptr(uintptr_t address) { uintptr_t p = 0; return read_mem(address, &p, sizeof p) ? p : 0; }
static int valid_xyz(const float xyz[3]) {
    return isfinite(xyz[0]) && isfinite(xyz[1]) && isfinite(xyz[2]) &&
           fabsf(xyz[0]) <= 6000 && xyz[1] >= -1000 && xyz[1] <= 3000 && fabsf(xyz[2]) <= 6000;
}
/* The two positions, or 0 when a link of a chain is missing (before the world is up) or the values are not a place. */
static uintptr_t havok_position(void) {
    uintptr_t a = read_ptr(survey_main + HAVOK_ROOT); if (a) a = read_ptr(a + HAVOK_STEP1); if (a) a = read_ptr(a + HAVOK_STEP2);
    float xyz[3];
    return a && read_mem(a + HAVOK_POS, xyz, sizeof xyz) && valid_xyz(xyz) ? a + HAVOK_POS : 0;
}
static uintptr_t world_matrix(void) {
    uintptr_t a = read_ptr(survey_main + MATRIX_ROOT); if (a) a = read_ptr(a + MATRIX_STEP1);
    float m[12];
    if (!a || !read_mem(a + MATRIX_OFF, m, sizeof m)) return 0;
    for (int i = 0; i < 12; i++) if (!isfinite(m[i])) return 0;
    float t[3] = {m[3], m[7], m[11]};
    return valid_xyz(t) ? a + MATRIX_OFF : 0;
}
void runtime_survey_init(Module *m) {
    const char *enabled = getenv("TOTK_SURVEY");
    if (!enabled || strcmp(enabled, "1")) return;
    const char *owner = getenv("TOTK_SLOT_OWNER"), *profile = getenv("TOTK_PROFILE_DIR");
    char target[PATH_MAX];
    if (!owner || !strcmp(owner, "user") || !profile || !realpath(profile, target))
        runtime_fail("TOTK_SURVEY requires an agent-owned session and a separate test profile");
    if (strcmp(m->name, "main") || HAVOK_ROOT + 8u > m->size || MATRIX_ROOT + 8u > m->size)
        runtime_fail("survey: Breath of the Wild 1.6.0 main expected");
    survey_main = (uintptr_t)m->base;
    atomic_store(&survey_enabled, 1);
    fprintf(stderr, "[survey] enabled (Breath of the Wild 1.6.0): pos and move act on the player's Havok position and world matrix\n");
}
static void report(const char *tag, const char *status) {
    uintptr_t h = havok_position(), w = world_matrix();
    float xyz[3] = {0}, m[12] = {0};
    if (h) read_mem(h, xyz, sizeof xyz);
    if (w) read_mem(w, m, sizeof m);
    fprintf(stderr, "[survey] tag=%s status=%s havok=%#llx xyz=%.6f,%.6f,%.6f matrix=%#llx xyz=%.6f,%.6f,%.6f\n",
            tag, status, (unsigned long long)h, xyz[0], xyz[1], xyz[2], (unsigned long long)w, m[3], m[7], m[11]);
}
/* survey scan X Y Z: diagnostic, lists every float triple within 2 m of X Y Z in the player actor (first 0x4000 bytes of
   [[main+0x2ca1140]+0x60]), the Havok object ([[main+0x2d37af0]+0xf0]+0xd28, 0x1000 bytes) and the actor's +0xf0 object. */
static void scan_block(const char *what, uintptr_t base, size_t size, const float xyz[3]) {
    float *buf = malloc(size); if (!buf) return;
    if (read_mem(base, buf, size)) {
        for (size_t i = 0; i + 3 <= size / 4; i++)
            if (fabsf(buf[i] - xyz[0]) < 2 && fabsf(buf[i + 1] - xyz[1]) < 2 && fabsf(buf[i + 2] - xyz[2]) < 2)
                fprintf(stderr, "[survey-scan] %s+%#zx = %.3f,%.3f,%.3f\n", what, i * 4, buf[i], buf[i + 1], buf[i + 2]);
    } else fprintf(stderr, "[survey-scan] %s at %#llx unreadable\n", what, (unsigned long long)base);
    free(buf);
}
static void survey_scan(const float xyz[3]) {
    uintptr_t actor = read_ptr(survey_main + MATRIX_ROOT); if (actor) actor = read_ptr(actor + MATRIX_STEP1);
    uintptr_t h = read_ptr(survey_main + HAVOK_ROOT); if (h) h = read_ptr(h + HAVOK_STEP1); if (h) h = read_ptr(h + HAVOK_STEP2);
    fprintf(stderr, "[survey-scan] actor=%#llx havok=%#llx looking for %.2f,%.2f,%.2f\n", (unsigned long long)actor, (unsigned long long)h, xyz[0], xyz[1], xyz[2]);
    if (actor) scan_block("actor", actor, 0x4000, xyz);
    if (h) scan_block("havok", h, 0x1000, xyz);
    uintptr_t h1 = read_ptr(survey_main + HAVOK_ROOT); if (h1) h1 = read_ptr(h1 + HAVOK_STEP1);
    if (h1) scan_block("havok1", h1, 0x1000, xyz);
}
int runtime_survey_command(const char *line) {
    if (strncmp(line, "survey ", 7)) return 0;
    char op[16], tag[64]; float xyz[3] = {0}; unsigned hold = 0; int used = 0, kind = 0;
    if (sscanf(line, "survey %15s %63s %n", op, tag, &used) == 2 && used && !line[used] && !strcmp(op, "pos")) kind = 1;
    used = 0;
    if (sscanf(line, "survey move %63s %f %f %f %u %n", tag, &xyz[0], &xyz[1], &xyz[2], &hold, &used) == 5 &&
        used && !line[used] && valid_xyz(xyz) && hold >= 1 && hold <= 3000) kind = 2;
    used = 0;
    if (sscanf(line, "survey scan %f %f %f %n", &xyz[0], &xyz[1], &xyz[2], &used) == 3 && used && !line[used]) {
        if (atomic_load(&survey_enabled)) survey_scan(xyz); return 1;
    }
    if (!kind) { fprintf(stderr, "[survey] rejected: expected pos <tag> or move <tag> X Y Z <1..3000 frames>\n"); return 1; }
    for (const char *p = tag; *p; ++p) if (!isalnum((unsigned char)*p) && *p != '_' && *p != '-') {
        fprintf(stderr, "[survey] rejected: invalid tag\n"); return 1;
    }
    if (!atomic_load(&survey_enabled)) { fprintf(stderr, "[survey] tag=%s status=disabled\n", tag); return 1; }
    if (kind == 1) { report(tag, havok_position() ? "position" : "no_player"); return 1; }
    uintptr_t h = havok_position(), w = world_matrix();
    if (!h || !w) { report(tag, "no_player"); return 1; }
    report(tag, "move_begin");
    /* Every float triple within 2 m of the player's position in the actor, the Havok object and its parent, plus the
       world matrix and the camera matrix translations, keeps its offset from the player and moves with him: one pass
       collects them, then they are written for <hold> frames (30 Hz) so the physics settles on the new place. */
    float cur[3]; read_mem(h, cur, sizeof cur);
    struct { uintptr_t at; float rel[3]; } slot[160]; unsigned n = 0;
    uintptr_t actor = read_ptr(survey_main + MATRIX_ROOT); if (actor) actor = read_ptr(actor + MATRIX_STEP1);
    uintptr_t hk1 = read_ptr(survey_main + HAVOK_ROOT); if (hk1) hk1 = read_ptr(hk1 + HAVOK_STEP1);
    uintptr_t hk = hk1 ? read_ptr(hk1 + HAVOK_STEP2) : 0;
    uintptr_t cam0 = read_ptr(survey_main + CAMERA_ROOT), cam = cam0 ? read_ptr(cam0 + CAMERA_STEP1) : 0;
    fprintf(stderr, "[survey] actor=%#llx havok=%#llx havok1=%#llx cam0=%#llx cam=%#llx\n", (unsigned long long)actor, (unsigned long long)hk, (unsigned long long)hk1, (unsigned long long)cam0, (unsigned long long)cam);
    /* the camera block at CAMERA_OFF is {position, look-at, up, fovy, ?, aspect}: position and look-at sit within 10 m of the player */
    struct { uintptr_t base; size_t size; float window; } blocks[4] = {{actor, 0x4000, 2}, {hk, 0x1000, 2}, {hk1, 0x1000, 2}, {cam ? cam + CAMERA_OFF : 0, 0x18, 12}};
    for (unsigned b = 0; b < 4; b++) {
        if (!blocks[b].base) continue;
        float *buf = malloc(blocks[b].size); if (!buf) continue;
        float win = blocks[b].window;
        if (read_mem(blocks[b].base, buf, blocks[b].size))
            for (size_t k = 0; k + 3 <= blocks[b].size / 4 && n < 150; k++)
                if (fabsf(buf[k] - cur[0]) < win && fabsf(buf[k + 1] - cur[1]) < win && fabsf(buf[k + 2] - cur[2]) < win) {
                    slot[n].at = blocks[b].base + k * 4;
                    for (int c = 0; c < 3; c++) slot[n].rel[c] = buf[k + c] - cur[c];
                    n++; k += 2;
                }
        free(buf);
    }
    /* matrix translations are not contiguous: world matrix [3],[7],[11]; camera matrix at CAMERA_OFF the same */
    uintptr_t mats[1] = {w}; unsigned nmat = 0; struct { uintptr_t at; float rel[3]; } mat[1];
    for (unsigned q = 0; q < 1; q++) {
        float m[12];
        if (!mats[q] || !read_mem(mats[q], m, sizeof m)) continue;
        mat[nmat].at = mats[q]; mat[nmat].rel[0] = m[3] - cur[0]; mat[nmat].rel[1] = m[7] - cur[1]; mat[nmat].rel[2] = m[11] - cur[2];
        fprintf(stderr, "[survey] %s matrix at %#llx: %.3f %.3f %.3f %.3f | %.3f %.3f %.3f %.3f | %.3f %.3f %.3f %.3f\n", q ? "camera" : "world", (unsigned long long)mats[q],
                m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], m[10], m[11]);
        if (q == 1 && (fabsf(mat[nmat].rel[0]) > 300 || fabsf(mat[nmat].rel[1]) > 300 || fabsf(mat[nmat].rel[2]) > 300)) continue;   /* camera not near the player: leave it */
        nmat++;
    }
    fprintf(stderr, "[survey] tag=%s moving %u triples and %u matrices by %.2f,%.2f,%.2f\n", tag, n, nmat, xyz[0] - cur[0], xyz[1] - cur[1], xyz[2] - cur[2]);
    /* A far place is not loaded: the player is frozen until the world streams in around him, which never happens when he
       appears there at once. So the move is a flight: a straight line from here to there over <hold> frames (30 Hz), the
       world streaming in on the way as it does for a fast glide. 300 frames carry 2.3 km at about 8 m per frame. */
    for (unsigned i = 0; i < hold; i++) {
        float f = (float)(i + 1) / (float)hold, at[3];
        for (int c = 0; c < 3; c++) at[c] = cur[c] + (xyz[c] - cur[c]) * f;
        for (unsigned k = 0; k < n; k++) { float v[3] = {at[0] + slot[k].rel[0], at[1] + slot[k].rel[1], at[2] + slot[k].rel[2]}; memcpy((void *)slot[k].at, v, sizeof v); }
        for (unsigned k = 0; k < nmat; k++) { float *m = (float *)mat[k].at; m[3] = at[0] + mat[k].rel[0]; m[7] = at[1] + mat[k].rel[1]; m[11] = at[2] + mat[k].rel[2]; }
        usleep(33333);
    }
    report(tag, "move_done");
    return 1;
}
#endif   /* GAME_BOTW160 */
#if !defined(GAME_BOTW160)
void runtime_survey_init(Module *m) {
    (void)m;
    if (getenv("TOTK_SURVEY")) runtime_fail("survey: only Breath of the Wild 1.6.0 has the player position chains");
}
int runtime_survey_command(const char *line) { (void)line; return 0; }
#endif
#else
enum { SCENE_SLOT = GAME_ADDR(0x4663f08), FORCE_MATRIX = GAME_ADDR(0x69a18c), ACTOR_POS = GAME_ACTOR_POS, ACTOR_ROT = GAME_ACTOR_ROT };
static uintptr_t survey_main, survey_main_size;
static void (*survey_force)(void *, const float *, uint32_t);
static _Atomic int survey_enabled;
_Atomic int runtime_survey_pending;
/* The frame-end sync, read by hle_nvn.c (built once for all versions): *(sys+[0]), then +[1] through one more pointer if
   [1] >= 0. 1.4.3's frame controller (main+0x2db94c) first waits on *(*(sys+0x150)+0x78), found with TOTK_SURVEY_DEBUG. */
#if defined(TOTK_GAME_V143)
const int32_t runtime_survey_sync[2] = {0x150, 0x78};
#else
const int32_t runtime_survey_sync[2] = {0x1d8, -1};
#endif
static pthread_mutex_t survey_lock = PTHREAD_MUTEX_INITIALIZER;
static struct { int kind; char tag[64]; float xyz[3]; unsigned hold; } request;
static unsigned hold_left;
static float hold_xyz[3];
static char hold_tag[64];
static _Thread_local int in_tick;

static int read_mem(uintptr_t address, void *out, size_t size) {
    if (!address || address > UINTPTR_MAX - size) return 0;
    mach_vm_size_t got = 0;
    return mach_vm_read_overwrite(mach_task_self(), address, size, (uintptr_t)out, &got) == KERN_SUCCESS && got == size;
}
static uintptr_t read_ptr(uintptr_t address) { uintptr_t p = 0; return read_mem(address, &p, sizeof p) ? p : 0; }
static int valid_xyz(const float xyz[3]) {
    return isfinite(xyz[0]) && isfinite(xyz[1]) && isfinite(xyz[2]) &&
           fabsf(xyz[0]) <= 5500 && xyz[1] >= -1500 && xyz[1] <= 3500 && fabsf(xyz[2]) <= 5000;
}
static void survey_debug_layout(uintptr_t module, uintptr_t scene) {
    static unsigned reports;
    if (!getenv("TOTK_SURVEY_DEBUG") || reports++ >= 3) return;
    fprintf(stderr, "[survey-layout] module=%#llx scene=%#llx\n", (unsigned long long)module, (unsigned long long)scene);
    int count = 0; read_mem(scene + 0x50, &count, 4);
    uintptr_t components = read_ptr(scene + 0x58);
    fprintf(stderr, "[survey-layout] components=%#llx count=%d\n", (unsigned long long)components, count);
    if (count < 1 || count > 256) return;
    for (int i = 0; i < count; ++i) {
        uintptr_t c = read_ptr(components + i * 8), ref = read_ptr(c + 8);
        char name[200] = {0}; read_mem(ref, name, sizeof name - 1);
        int n = 0; read_mem(c + 0x20, &n, 4); uintptr_t links = read_ptr(c + 0x28);
        fprintf(stderr, "[survey-layout] component=%d ptr=%#llx ref=%.199s count=%d links=%#llx\n", i, (unsigned long long)c, name, n, (unsigned long long)links);
        if (i != 13 || n < 1 || n > 64) continue;
        for (int j = 0; j < n; ++j) {
            uintptr_t data = read_ptr(links + j * 0x70 + 8), actor = read_ptr(data + 0x40), actor_name = read_ptr(actor + GAME_ACTOR_NAME);
            char text[64] = {0}; read_mem(actor_name, text, sizeof text - 1);
            fprintf(stderr, "[survey-layout] link=%d data=%#llx actor=%#llx name=%.63s\n", j, (unsigned long long)data, (unsigned long long)actor, text);
        }
    }
}
/* The resident list named in the comment above: the player and the cameras. Both are returned when found, so the
   guide arrow can read the camera's rotation without walking the actor table. */
static int resident_actors(uintptr_t *player_out, uintptr_t *camera_out) {
    *player_out = 0; if (camera_out) *camera_out = 0;
    uintptr_t module = read_ptr(survey_main + SCENE_SLOT);
    uintptr_t scene = module ? read_ptr(module + 0x1e8) : 0;
    survey_debug_layout(module, scene);
    int count = 0;
    if (!scene || !read_mem(scene + 0x50, &count, 4) || count < 14 || count > 256) return 0;
    uintptr_t components = read_ptr(scene + 0x58);
    uintptr_t resident = components ? read_ptr(components + 13 * 8) : 0;
    if (!resident || !read_mem(resident + 0x20, &count, 4) || count < 1 || count > 64) return 0;
    uintptr_t links = read_ptr(resident + 0x28);
    if (!links) return 0;
    for (int i = 0; i < count; ++i) {
        uintptr_t data = read_ptr(links + (uintptr_t)i * 0x70 + 8);
        uintptr_t actor = data ? read_ptr(data + 0x40) : 0;
        uintptr_t name = actor ? read_ptr(actor + GAME_ACTOR_NAME) : 0;
        char text[16] = {0};
        if (!name || !read_mem(name, text, sizeof text - 1)) continue;
        if (!strcmp(text, "Player")) {
            float xyz[3];
            if (read_mem(actor + ACTOR_POS, xyz, sizeof xyz) && valid_xyz(xyz)) *player_out = actor;
        } else if (camera_out && !strcmp(text, "PlayerCamera")) {
            *camera_out = actor;
        }
    }
    return *player_out ? 1 : 0;
}
static uintptr_t player_actor(void) {
    uintptr_t player = 0;
    resident_actors(&player, NULL);
    return player;
}
int runtime_live_activity(RuntimePlayerActivity *out) {
    memset(out,0,sizeof *out);
#if defined(TOTK_GAME_V143)
    if(!survey_main)return 0;
    uintptr_t actor=player_actor(),vt=actor?read_ptr(actor):0;
    if(!actor||vt<survey_main||vt>=survey_main+survey_main_size)return 0;
    int ok=activity_decode143(read_mem,actor,out);
    if(runtime_settings_paused())out->active=0;
    return ok;
#else
    return 0;
#endif
}
/* A rotation is usable when every value is finite and sane; a camera may look down, so the axis lengths are what is
   checked rather than a fixed facing. */
static int usable_rotation(const float r[9]) {
    for (int i = 0; i < 9; ++i) if (!isfinite(r[i]) || fabsf(r[i]) > 4) return 0;
    for (int row = 0; row < 3; ++row) {
        float n = sqrtf(r[row * 3] * r[row * 3] + r[row * 3 + 1] * r[row * 3 + 1] + r[row * 3 + 2] * r[row * 3 + 2]);
        if (n < 0.5f || n > 2) return 0;
    }
    return 1;
}
/* A string in game memory, cut at its first non-printable byte (empty when unreadable). */
static void survey_text(uintptr_t at, char *out, size_t size) {
    out[0] = 0;
    if (!at || !read_mem(at, out, size - 1)) { out[0] = 0; return; }
    out[size - 1] = 0;
    for (char *p = out; *p; ++p) if ((unsigned char)*p < 0x20 || (unsigned char)*p > 0x7e) { *p = 0; break; }
}
/* The game's actor table (found 2026-10-24 in 1.4.3 with the survey commands below): main+0x3ad6d78 holds an object
   whose vtable is main+0x3944c98, with its slot count at +0x30 and slots of 0x60 bytes from +0x40, each starting with
   an actor pointer (then the actor's creation number). It holds the placed objects (shrine devices, chests), the
   system actors and the pooled ones; the player's resident list above holds only the player and the cameras. */
#if defined(TOTK_GAME_V143)
enum { ACTOR_TABLE_ROOT = 0x3ad6d78, ACTOR_TABLE_VTABLE = 0x3944c98, ACTOR_TABLE_COUNT = 0x30,   /* 1.4.3 offsets */
       ACTOR_TABLE_SLOTS = 0x40, ACTOR_TABLE_STRIDE = 0x60, ACTOR_TABLE_MAX = 20000 };
#endif
#if defined(TOTK_GAME_V143)
static int actor_name(uintptr_t actor, char *out, size_t size) {   /* a game object with a name: 1 */
    uintptr_t vt = read_ptr(actor);
    if (!vt || vt < survey_main || vt >= survey_main + survey_main_size) return 0;
    survey_text(read_ptr(actor + GAME_ACTOR_NAME), out, size);
    return isalnum((unsigned char)out[0]);
}
#endif
int runtime_live_scene(RuntimeScene *out, float radius) {
    memset(out, 0, sizeof *out);
#if !defined(TOTK_GAME_V143)
    (void)radius;
#endif
    if (!survey_main) return -1;
    uintptr_t player = player_actor();
    if (!player) return 0;
    if (!read_mem(player + ACTOR_POS, out->player, sizeof out->player) || !read_mem(player + ACTOR_ROT, out->rot, sizeof out->rot)) return 0;
#if defined(TOTK_GAME_V143)
    uintptr_t table = read_ptr(survey_main + ACTOR_TABLE_ROOT);
    uint32_t count = 0;
    if (!table || read_ptr(table) != survey_main + ACTOR_TABLE_VTABLE || !read_mem(table + ACTOR_TABLE_COUNT, &count, 4) ||
        !count || count > ACTOR_TABLE_MAX) return 1;
    uintptr_t *slots = malloc(count * sizeof *slots);
    if (!slots) return 1;
    int ok = 1;
    for (uint32_t k = 0; k < count && ok; ++k) ok = read_mem(table + ACTOR_TABLE_SLOTS + (uintptr_t)k * ACTOR_TABLE_STRIDE, &slots[k], 8);
    if (!ok) { free(slots); return 1; }
    out->table = (int)count;
    for (uint32_t k = 0; k < count; ++k) {
        uintptr_t a = slots[k];
        char name[48]; float xyz[3];
        if (!a || a == player || !read_mem(a + ACTOR_POS, xyz, sizeof xyz) || !valid_xyz(xyz)) continue;
        if (fabsf(xyz[0]) < 0.01f && fabsf(xyz[1]) < 0.01f && fabsf(xyz[2]) < 0.01f) continue;   /* parked */
        float dx = xyz[0] - out->player[0], dy = xyz[1] - out->player[1], dz = xyz[2] - out->player[2];
        float d = sqrtf(dx * dx + dy * dy + dz * dz);
        if (d > radius || !actor_name(a, name, sizeof name)) continue;
        if (!strcmp(name, "PlayerCamera")) {
            memcpy(out->camera, xyz, sizeof xyz); out->has_camera = 1;
            float rot[9];
            if (read_mem(a + ACTOR_ROT, rot, sizeof rot) && usable_rotation(rot)) { memcpy(out->cam_rot, rot, sizeof rot); out->has_cam_rot = 1; }
        }
        /* what Link wears and holds, and the game's machinery, sit on him: they would fill the list */
        if (d < 1.5f || strstr(name, "SystemActor") || strstr(name, "Camera")) continue;
        int full = out->actors == 40;   /* insert nearest first; a full list drops the farthest */
        if (full && d >= out->near[39].distance) continue;
        int at = full ? 39 : out->actors++;
        while (at > 0 && out->near[at - 1].distance > d) { out->near[at] = out->near[at - 1]; --at; }
        RuntimeActor *r = &out->near[at];
        memcpy(r->name, name, sizeof r->name); memcpy(r->xyz, xyz, sizeof xyz); r->distance = d;
    }
    free(slots);
#endif
    return 1;
}
int runtime_live_player(float xyz[3]) {
    if(!survey_main)return -1;
    uintptr_t actor=player_actor();
    if(!actor)return 0;
    return read_mem(actor+ACTOR_POS,xyz,3*sizeof(float))&&valid_xyz(xyz)?1:0;
}
int runtime_live_facing(float player_rot[9], float camera_rot[9], float camera_pos[3]) {
    if (!survey_main) return -1;
    uintptr_t player = 0, camera = 0;
    float rot[9];
    if (!resident_actors(&player, &camera) || !player) return 0;
    if (!read_mem(player + ACTOR_ROT, rot, sizeof rot) || !usable_rotation(rot)) return 0;
    memcpy(player_rot, rot, sizeof rot);
    if (!camera || !read_mem(camera + ACTOR_ROT, rot, sizeof rot) || !usable_rotation(rot)) return 1;
    memcpy(camera_rot, rot, sizeof rot);
    float xyz[3];
    if (camera_pos && read_mem(camera + ACTOR_POS, xyz, sizeof xyz) && valid_xyz(xyz)) memcpy(camera_pos, xyz, sizeof xyz);
    else if (camera_pos) { camera_pos[0] = camera_pos[1] = camera_pos[2] = 0; return 1; }
    return 3;
}
void runtime_survey_init(Module *m) {
    if(!strcmp(m->name,"main")&&SCENE_SLOT+8u<=m->size){survey_main=(uintptr_t)m->base;survey_main_size=m->size;}
    const char *enabled = getenv("TOTK_SURVEY");
    if (!enabled || strcmp(enabled, "1")) return;
    const char *owner = getenv("TOTK_SLOT_OWNER"), *profile = getenv("TOTK_PROFILE_DIR");
    char target[PATH_MAX], user[PATH_MAX];
    if (!owner || !strcmp(owner, "user") || !profile || !realpath(profile, target) ||
        (realpath("analysis/phase6-profile", user) && !strcmp(target, user)))
        runtime_fail("TOTK_SURVEY requires an agent-owned session and a separate test profile");
#if defined(TOTK_GAME_V143)
    const uint32_t expected[] = {0xa9bc7bfd, 0xa9015ff8, 0xa90257f6, 0xa9034ff4};   // 1.4.3 inlines the physics call: larger frame
#else
    const uint32_t expected[] = {0xa9bd7bfd, 0xf9000bf5, 0x910003fd, 0xa9024ff4};
#endif
    if (strcmp(m->name, "main") || SCENE_SLOT + 8u > m->size || FORCE_MATRIX + sizeof expected > m->text_end ||
        memcmp(m->base + FORCE_MATRIX, expected, sizeof expected))
        runtime_fail("survey requires verified game-version forceSetMatrix entry");
    survey_main = (uintptr_t)m->base;
    survey_force = (void (*)(void *, const float *, uint32_t))(m->base + FORCE_MATRIX);
    survey_enabled = 1;
    fprintf(stderr, "[survey] enabled: test profile, game frame-end commands, original forceSetMatrix\n");
}
/* "survey actors <tag>" (read-only): every component of the scene and the actors its links hold, as the player-finding
   walk above reads them (links of 0x70 bytes, actor at +0x40, name at GAME_ACTOR_NAME), with each actor's position
   and distance from the player, and the player's rotation. One line each, "[survey-actors]", for working out which
   live state (nearby objects, the stage) the hint assistant can read instead of looking at frames. */
static void dump_actors(const char *tag, uint64_t frame, uintptr_t player) {
    float me[3] = {0}, rot[9] = {0};
    read_mem(player + ACTOR_POS, me, sizeof me); read_mem(player + ACTOR_ROT, rot, sizeof rot);
    fprintf(stderr, "[survey-actors] tag=%s frame=%llu player=%.2f,%.2f,%.2f rot=%.3f,%.3f,%.3f|%.3f,%.3f,%.3f|%.3f,%.3f,%.3f\n",
            tag, (unsigned long long)frame, me[0], me[1], me[2], rot[0], rot[1], rot[2], rot[3], rot[4], rot[5], rot[6], rot[7], rot[8]);
    uintptr_t module = read_ptr(survey_main + SCENE_SLOT), scene = module ? read_ptr(module + 0x1e8) : 0;
    int count = 0;
    if (!scene || !read_mem(scene + 0x50, &count, 4) || count < 1 || count > 256) return;
    uintptr_t components = read_ptr(scene + 0x58);
    for (int i = 0; i < count; ++i) {
        uintptr_t c = read_ptr(components + (uintptr_t)i * 8);
        char name[96]; survey_text(c ? read_ptr(c + 8) : 0, name, sizeof name);
        int n = 0; if (c) read_mem(c + 0x20, &n, 4);
        uintptr_t links = c ? read_ptr(c + 0x28) : 0;
        fprintf(stderr, "[survey-actors] tag=%s comp=%d name=%s count=%d\n", tag, i, name, n);
        if (n < 1 || n > 4096 || !links) continue;
        for (int j = 0, shown = 0; j < n && shown < 400; ++j) {
            uintptr_t data = read_ptr(links + (uintptr_t)j * 0x70 + 8), actor = data ? read_ptr(data + 0x40) : 0;
            char an[96]; survey_text(actor ? read_ptr(actor + GAME_ACTOR_NAME) : 0, an, sizeof an);
            if (!isalnum((unsigned char)an[0])) continue;
            float xyz[3];
            if (read_mem(actor + ACTOR_POS, xyz, sizeof xyz) && valid_xyz(xyz)) {
                float dx = xyz[0] - me[0], dy = xyz[1] - me[1], dz = xyz[2] - me[2];
                fprintf(stderr, "[survey-actors] tag=%s comp=%d link=%d actor=%s xyz=%.2f,%.2f,%.2f d=%.1f\n",
                        tag, i, j, an, xyz[0], xyz[1], xyz[2], sqrtf(dx * dx + dy * dy + dz * dz));
            } else fprintf(stderr, "[survey-actors] tag=%s comp=%d link=%d actor=%s xyz=?\n", tag, i, j, an);
            ++shown;
        }
    }
}
/* "survey nearby <tag>" (read-only, freezes the game a second or two): every object in resident memory that looks like
   an actor laid out as the player is (a name pointer at GAME_ACTOR_NAME, a position at ACTOR_POS within 300 m of the
   player, an orthonormal rotation at ACTOR_ROT), nearest first. The scene's actor lists hold only the resident actors
   (the player, cameras); this finds the rest without knowing where the game keeps them. Pages that are not resident
   are skipped (mincore), so reserved guest memory is not touched. */
typedef struct { char name[64]; float xyz[3]; float d; uintptr_t at, vtable; } SurveyFound;
static int survey_by_distance(const void *a, const void *b) {
    float x = ((const SurveyFound *)a)->d, y = ((const SurveyFound *)b)->d; return (x > y) - (x < y);
}
static int survey_rotation(const float *r) {   /* orthogonal rows, each of a sane length: rotated, maybe scaled */
    float n[3];
    for (int i = 0; i < 9; ++i) if (!isfinite(r[i]) || fabsf(r[i]) > 100) return 0;
    for (int row = 0; row < 3; ++row) {
        n[row] = sqrtf(r[row * 3] * r[row * 3] + r[row * 3 + 1] * r[row * 3 + 1] + r[row * 3 + 2] * r[row * 3 + 2]);
        if (n[row] < 0.05f || n[row] > 60) return 0;
    }
    for (int a = 0; a < 3; ++a) for (int b = a + 1; b < 3; ++b) {
        float dot = r[a * 3] * r[b * 3] + r[a * 3 + 1] * r[b * 3 + 1] + r[a * 3 + 2] * r[b * 3 + 2];
        if (fabsf(dot) > 0.02f * n[a] * n[b]) return 0;
    }
    return 1;
}
/* Walks every resident read-write chunk of this process (mincore: reserved guest memory is not touched), calling
   visit(chunk copy, its address, its length) for each; the scratch buffer itself is skipped. */
typedef void (*SurveyVisit)(const uint8_t *buf, uintptr_t base, size_t len, void *ctx);
static uint64_t survey_walk(SurveyVisit visit, void *ctx) {
    enum { CHUNK = 16 << 20 };
    uint8_t *buf = malloc(CHUNK); char *resident = malloc(CHUNK / 4096 + 2);   /* one byte a page, any page size */
    if (!buf || !resident) { free(buf); free(resident); return 0; }
    size_t page = (size_t)getpagesize(); uint64_t scanned = 0;
    mach_vm_address_t addr = 0; mach_vm_size_t size = 0;
    for (;;) {
        vm_region_basic_info_data_64_t info; mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64; mach_port_t object;
        if (mach_vm_region(mach_task_self(), &addr, &size, VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &count, &object) != KERN_SUCCESS) break;
        if ((info.protection & (VM_PROT_READ | VM_PROT_WRITE)) == (VM_PROT_READ | VM_PROT_WRITE) &&
            !((uintptr_t)buf >= addr && (uintptr_t)buf < addr + size)) {
            for (mach_vm_size_t off = 0; off < size; off += CHUNK - 0x400) {
                size_t len = (size_t)(size - off < CHUNK ? size - off : CHUNK);
                if (len < 0x300) break;
                uintptr_t base = (uintptr_t)(addr + off);
                if (mincore((void *)(base & ~(page - 1)), len + (base & (page - 1)), resident) != 0) continue;
                int any = 0; for (size_t p = 0; p < (len + page - 1) / page; ++p) if (resident[p] & 1) { any = 1; break; }
                if (!any || !read_mem(base, buf, len)) continue;
                scanned += len; visit(buf, base, len, ctx);
            }
        }
        addr += size;
    }
    free(buf); free(resident);
    return scanned;
}
enum { SURVEY_MAX_FOUND = 6000 };
typedef struct { SurveyFound *found; int n; float me[3]; } SurveyCollect;
static void survey_collect(const uint8_t *buf, uintptr_t base, size_t len, void *ctx) {
    SurveyCollect *c = ctx;
    for (size_t i = 0; i + ACTOR_ROT + 36 <= len && c->n < SURVEY_MAX_FOUND; i += 8) {
        const float *xyz = (const float *)(buf + i + ACTOR_POS);
        float dx = xyz[0] - c->me[0], dy = xyz[1] - c->me[1], dz = xyz[2] - c->me[2];
        if (!isfinite(dx) || !isfinite(dy) || !isfinite(dz) || fabsf(dx) > 300 || fabsf(dy) > 300 || fabsf(dz) > 300) continue;
        if (!survey_rotation((const float *)(buf + i + ACTOR_ROT))) continue;
        /* a C++ object of the game: its first word is a vtable in main's own image */
        uintptr_t vtable = *(const uintptr_t *)(buf + i);
        if (vtable < survey_main || vtable >= survey_main + survey_main_size) continue;
        uintptr_t name = *(const uintptr_t *)(buf + i + GAME_ACTOR_NAME);
        if (name < 0x100000000ull || name > 0x7fffffffffffull) continue;
        char text[64]; survey_text(name, text, sizeof text);
        size_t tl = strlen(text);
        if (tl < 3 || !isupper((unsigned char)text[0])) continue;
        SurveyFound *f = &c->found[c->n++]; memcpy(f->name, text, tl + 1); memcpy(f->xyz, xyz, sizeof f->xyz);
        f->d = sqrtf(dx * dx + dy * dy + dz * dz); f->at = base + i; f->vtable = vtable - survey_main;
    }
}
static int survey_collect_actors(uintptr_t player, SurveyCollect *c, uint64_t *scanned) {
    memset(c, 0, sizeof *c);
    c->found = calloc(SURVEY_MAX_FOUND, sizeof *c->found);
    if (!c->found) return 0;
    read_mem(player + ACTOR_POS, c->me, sizeof c->me);
    *scanned = survey_walk(survey_collect, c);
    return 1;
}
static void scan_nearby(const char *tag, uint64_t frame, uintptr_t player) {
    SurveyCollect c; uint64_t scanned = 0;
    if (!survey_collect_actors(player, &c, &scanned)) return;
    qsort(c.found, (size_t)c.n, sizeof *c.found, survey_by_distance);
    fprintf(stderr, "[survey-nearby] tag=%s frame=%llu player=%.2f,%.2f,%.2f scanned=%llu MB candidates=%d\n", tag,
            (unsigned long long)frame, c.me[0], c.me[1], c.me[2], (unsigned long long)(scanned >> 20), c.n);
    for (int k = 0; k < c.n && k < 600; ++k)
        fprintf(stderr, "[survey-nearby] tag=%s actor=%s xyz=%.2f,%.2f,%.2f d=%.1f at=%#llx vtable=main+%#llx\n", tag, c.found[k].name,
                c.found[k].xyz[0], c.found[k].xyz[1], c.found[k].xyz[2], c.found[k].d, (unsigned long long)c.found[k].at,
                (unsigned long long)c.found[k].vtable);
    memset(c.found, 0, SURVEY_MAX_FOUND * sizeof *c.found); free(c.found);   /* nothing for the next scan to find */
}

/* "survey refs <tag>" (read-only, several seconds): which memory points at the actors survey nearby finds. Every
   resident word that points into an actor (its first 0x800 bytes) is a hit; the report shows
     delta   how far into the actor the pointers aim, and at how many distinct actors
     run     consecutive words pointing at different actors with one delta: an array of actors (where it lives; "main+"
             marks one in the game's own data, a static root)
     intra   a pointer that lives inside one actor (at +from) and aims into another (at +to): an intrusive list
   so the game's actor lists can be read directly instead of scanning. */
typedef struct { uintptr_t loc; int actor; int delta; } SurveyRef;
typedef struct { const SurveyFound *by_at; int n; uintptr_t lo, hi; SurveyRef *refs; int nrefs, max; } SurveyRefs;
static int survey_by_at(const void *a, const void *b) {
    uintptr_t x = ((const SurveyFound *)a)->at, y = ((const SurveyFound *)b)->at; return (x > y) - (x < y);
}
static int survey_actor_of(const SurveyFound *by_at, int n, uintptr_t v) {   /* the actor v points into, or -1 */
    int lo = 0, hi = n - 1, best = -1;
    while (lo <= hi) { int mid = (lo + hi) / 2; if (by_at[mid].at <= v) { best = mid; lo = mid + 1; } else hi = mid - 1; }
    return best >= 0 && v - by_at[best].at < 0x800 ? best : -1;
}
static void survey_refs_visit(const uint8_t *buf, uintptr_t base, size_t len, void *ctx) {
    SurveyRefs *r = ctx;
    for (size_t i = 0; i + 8 <= len && r->nrefs < r->max; i += 8) {
        uintptr_t v = *(const uintptr_t *)(buf + i);
        if (v < r->lo || v >= r->hi) continue;
        int a = survey_actor_of(r->by_at, r->n, v);
        if (a < 0) continue;
        r->refs[r->nrefs++] = (SurveyRef){base + i, a, (int)(v - r->by_at[a].at)};
    }
}
static int survey_by_loc(const void *a, const void *b) {
    uintptr_t x = ((const SurveyRef *)a)->loc, y = ((const SurveyRef *)b)->loc; return (x > y) - (x < y);
}
static void survey_where(uintptr_t loc, char *out, size_t size) {
    if (survey_main && loc >= survey_main && loc < survey_main + survey_main_size) snprintf(out, size, "main+%#llx", (unsigned long long)(loc - survey_main));
    else snprintf(out, size, "%#llx", (unsigned long long)loc);
}
static void scan_refs(const char *tag, uint64_t frame, uintptr_t player) {
    SurveyCollect c; uint64_t scanned = 0;
    if (!survey_collect_actors(player, &c, &scanned)) return;
    SurveyFound *by_at = c.found; int n = c.n;
    qsort(by_at, (size_t)n, sizeof *by_at, survey_by_at);
    int m = 0; for (int k = 0; k < n; ++k) if (!m || by_at[k].at != by_at[m - 1].at) by_at[m++] = by_at[k];   /* unique */
    n = m;
    SurveyRefs r = {by_at, n, n ? by_at[0].at : 0, n ? by_at[n - 1].at + 0x800 : 0, calloc(400000, sizeof(SurveyRef)), 0, 400000};
    if (!n || !r.refs) { free(by_at); free(r.refs); return; }
    uint64_t scanned2 = survey_walk(survey_refs_visit, &r);
    fprintf(stderr, "[survey-refs] tag=%s frame=%llu actors=%d scanned=%llu MB hits=%d%s\n", tag, (unsigned long long)frame, n,
            (unsigned long long)(scanned2 >> 20), r.nrefs, r.nrefs >= r.max ? " (capped)" : "");
    /* deltas: hits and distinct actors per offset into the actor */
    enum { DELTAS = 0x800 / 8 };
    static int hits[DELTAS], distinct[DELTAS]; static unsigned char *seen; free(seen); seen = calloc((size_t)n * DELTAS, 1);
    memset(hits, 0, sizeof hits); memset(distinct, 0, sizeof distinct);
    for (int k = 0; k < r.nrefs; ++k) {
        int d = r.refs[k].delta / 8; if (r.refs[k].delta % 8) continue;
        hits[d]++; if (seen && !seen[(size_t)r.refs[k].actor * DELTAS + d]) { seen[(size_t)r.refs[k].actor * DELTAS + d] = 1; distinct[d]++; }
    }
    for (int shown = 0; shown < 16; ++shown) {
        int best = -1; for (int d = 0; d < DELTAS; ++d) if (distinct[d] && (best < 0 || distinct[d] > distinct[best])) best = d;
        if (best < 0) break;
        fprintf(stderr, "[survey-refs] tag=%s delta=+%#x actors=%d hits=%d\n", tag, best * 8, distinct[best], hits[best]);
        distinct[best] = 0;
    }
    /* runs: arrays of pointers to different actors at one delta */
    qsort(r.refs, (size_t)r.nrefs, sizeof *r.refs, survey_by_loc);
    int runs = 0;
    for (int k = 0; k < r.nrefs && runs < 40;) {
        /* one delta, one stride (an array of pointers, or of structs that each hold one), different actors */
        uintptr_t stride = k + 1 < r.nrefs ? r.refs[k + 1].loc - r.refs[k].loc : 0;
        int e = k + 1;
        if (stride && stride <= 0x400)
            while (e < r.nrefs && r.refs[e].delta == r.refs[k].delta && r.refs[e].loc - r.refs[e - 1].loc == stride &&
                   r.refs[e].actor != r.refs[e - 1].actor) ++e;
        if (e - k >= 4) {
            char where[48]; survey_where(r.refs[k].loc, where, sizeof where);
            fprintf(stderr, "[survey-refs] tag=%s run at=%s len=%d stride=%llu delta=+%#x first=%s,%s,%s\n", tag, where, e - k,
                    (unsigned long long)(r.refs[k + 1].loc - r.refs[k].loc), r.refs[k].delta,
                    by_at[r.refs[k].actor].name, by_at[r.refs[k + 1].actor].name, by_at[r.refs[k + 2].actor].name);
            ++runs;
        }
        k = e;
    }
    /* intra: a pointer inside one actor aiming into another, by (from, to) */
    enum { PAIRS = 64 }; typedef struct { int from, to, count; } SurveyPair; SurveyPair pairs[PAIRS]; int np = 0;
    for (int k = 0; k < r.nrefs; ++k) {
        int b = survey_actor_of(by_at, n, r.refs[k].loc);
        if (b < 0 || b == r.refs[k].actor) continue;
        int from = (int)(r.refs[k].loc - by_at[b].at), to = r.refs[k].delta, j = 0;
        while (j < np && (pairs[j].from != from || pairs[j].to != to)) ++j;
        if (j == np) { if (np == PAIRS) continue; pairs[np++] = (SurveyPair){from, to, 0}; }
        pairs[j].count++;
    }
    for (int shown = 0; shown < 16; ++shown) {
        int best = -1; for (int j = 0; j < np; ++j) if (pairs[j].count && (best < 0 || pairs[j].count > pairs[best].count)) best = j;
        if (best < 0) break;
        fprintf(stderr, "[survey-refs] tag=%s intra from=+%#x to=+%#x count=%d\n", tag, pairs[best].from, pairs[best].to, pairs[best].count);
        pairs[best].count = 0;
    }
    free(seen); seen = NULL;
    memset(by_at, 0, SURVEY_MAX_FOUND * sizeof *by_at); memset(r.refs, 0, (size_t)r.max * sizeof *r.refs);
    free(by_at); free(r.refs);
}
/* "survey whois <address>" (read-only): the words that point at or just below an address (an array found by refs),
   to climb from a list to the object that owns it and on to a fixed place in main's data. */
typedef struct { uintptr_t target; int shown; } SurveyWhois;
static void survey_whois_visit(const uint8_t *buf, uintptr_t base, size_t len, void *ctx) {
    SurveyWhois *w = ctx;
    for (size_t i = 0; i + 8 <= len && w->shown < 60; i += 8) {
        uintptr_t v = *(const uintptr_t *)(buf + i);
        if (v + 0x40 < w->target || v > w->target + 8) continue;   /* at the address, or the object just before it */
        char where[48]; survey_where(base + i, where, sizeof where);
        fprintf(stderr, "[survey-whois] target=%#llx from=%s points=%+lld\n", (unsigned long long)w->target, where,
                (long long)(v - w->target));
        w->shown++;
    }
}
static void scan_whois(const char *address) {
    SurveyWhois w = {(uintptr_t)strtoull(address, NULL, 16), 0};
    if (!w.target) return;
    survey_walk(survey_whois_visit, &w);   /* main's writable data is among the regions walked */
    fprintf(stderr, "[survey-whois] target=%#llx done (%d)\n", (unsigned long long)w.target, w.shown);
}
/* "survey dump <address>" (read-only): 48 words from an address, each with what it looks like: an actor (its name),
   a string, a place in main, or two 32-bit numbers (a count and a capacity sit like that). */
static void scan_dump(const char *address) {   /* "main_0x123" is an offset into main's image */
    uintptr_t at = !strncmp(address, "main_", 5) ? survey_main + (uintptr_t)strtoull(address + 5, NULL, 16)
                                                 : (uintptr_t)strtoull(address, NULL, 16);
    for (int k = 0; k < 48; ++k) {
        uintptr_t v; if (!read_mem(at + (uintptr_t)k * 8, &v, 8)) { fprintf(stderr, "[survey-dump] %#llx unreadable\n", (unsigned long long)(at + k * 8)); break; }
        char what[96] = "";
        uintptr_t vt = 0, name = 0; char text[64];
        if (v >= survey_main && v < survey_main + survey_main_size) {
            survey_text(v, text, sizeof text);
            if (strlen(text) >= 4) snprintf(what, sizeof what, "main+%#llx \"%s\"", (unsigned long long)(v - survey_main), text);
            else snprintf(what, sizeof what, "main+%#llx", (unsigned long long)(v - survey_main));
        }
        else if (v > 0x100000000ull && v < 0x7fffffffffffull && read_mem(v, &vt, 8) && vt >= survey_main && vt < survey_main + survey_main_size &&
                 read_mem(v + GAME_ACTOR_NAME, &name, 8) && (survey_text(name, text, sizeof text), isupper((unsigned char)text[0])))
            snprintf(what, sizeof what, "-> actor %s", text);
        else if (v > 0x100000000ull && v < 0x7fffffffffffull && (survey_text(v, text, sizeof text), strlen(text) >= 4))
            snprintf(what, sizeof what, "-> \"%s\"", text);
        else snprintf(what, sizeof what, "%d %d", (int)(uint32_t)v, (int)(uint32_t)(v >> 32));
        fprintf(stderr, "[survey-dump] %#llx +%#05x %#018llx %s\n", (unsigned long long)(at + k * 8), k * 8, (unsigned long long)v, what);
    }
}
/* "survey list <header>" (read-only): the actor table whose header is at an address ({u32, u32 capacity} then the
   data pointer, as found at 0x7034065130 in 1.4.3): every slot that holds an actor, with its position and distance. */
static void scan_list(const char *address, uintptr_t player) {
    uintptr_t header = (uintptr_t)strtoull(address, NULL, 16), data = 0; uint32_t words[2] = {0};
    float me[3] = {0}; read_mem(player + ACTOR_POS, me, sizeof me);
    if (!read_mem(header, words, sizeof words) || !read_mem(header + 8, &data, 8) || !data || words[1] > 100000) {
        fprintf(stderr, "[survey-list] %s: no table\n", address); return; }
    int actors = 0, empty = 0, other = 0;
    for (uint32_t k = 0; k < words[1]; ++k) {
        uintptr_t a = 0, vt = 0, name = 0; char text[64];
        if (!read_mem(data + (uintptr_t)k * 8, &a, 8) || !a) { ++empty; continue; }
        if (!read_mem(a, &vt, 8) || vt < survey_main || vt >= survey_main + survey_main_size ||
            !read_mem(a + GAME_ACTOR_NAME, &name, 8)) { ++other; continue; }
        survey_text(name, text, sizeof text);
        float xyz[3] = {0}; int has = read_mem(a + ACTOR_POS, xyz, sizeof xyz) && valid_xyz(xyz);
        float dx = xyz[0] - me[0], dy = xyz[1] - me[1], dz = xyz[2] - me[2];
        fprintf(stderr, "[survey-list] slot=%u actor=%s xyz=%.2f,%.2f,%.2f d=%.1f%s vtable=main+%#llx\n", k, text, xyz[0], xyz[1],
                xyz[2], sqrtf(dx * dx + dy * dy + dz * dz), has ? "" : " (no position)", (unsigned long long)(vt - survey_main));
        ++actors;
    }
    fprintf(stderr, "[survey-list] %s: first word %u, capacity %u, actors %d, empty %d, other %d\n", address, words[0], words[1], actors, empty, other);
}
/* "survey slots <slot address>" (read-only): from one entry of the 0x60-byte actor table found in 1.4.3 (actor pointer,
   then its index), walk back and forth while the indices run on, and print the table's span and every actor in it. */
static int survey_slot(uintptr_t at, uintptr_t *actor, uint32_t *index) {
    return read_mem(at, actor, 8) && read_mem(at + 8, index, 4);
}
static void scan_slots(const char *address, uintptr_t player) {
    uintptr_t at = (uintptr_t)strtoull(address, NULL, 16), a; uint32_t index, i2;
    float me[3] = {0}; read_mem(player + ACTOR_POS, me, sizeof me);
    if (!survey_slot(at, &a, &index)) { fprintf(stderr, "[survey-slots] %s unreadable\n", address); return; }
    uintptr_t first = at; uint32_t first_index = index;
    while (first_index > 0 && survey_slot(first - 0x60, &a, &i2) && i2 == first_index - 1) { first -= 0x60; first_index = i2; }
    uintptr_t last = at; uint32_t last_index = index;
    while (survey_slot(last + 0x60, &a, &i2) && i2 == last_index + 1 && last_index < 200000) { last += 0x60; last_index = i2; }
    char where[48]; survey_where(first, where, sizeof where);
    int actors = 0;
    for (uintptr_t s = first; s <= last; s += 0x60) {
        uintptr_t vt = 0, name = 0; char text[64];
        if (!survey_slot(s, &a, &i2) || !a || !read_mem(a, &vt, 8) || vt < survey_main || vt >= survey_main + survey_main_size ||
            !read_mem(a + GAME_ACTOR_NAME, &name, 8)) continue;
        survey_text(name, text, sizeof text);
        float xyz[3] = {0}; int has = read_mem(a + ACTOR_POS, xyz, sizeof xyz) && valid_xyz(xyz);
        float dx = xyz[0] - me[0], dy = xyz[1] - me[1], dz = xyz[2] - me[2];
        fprintf(stderr, "[survey-slots] index=%u actor=%s xyz=%.2f,%.2f,%.2f d=%.1f%s\n", i2, text, xyz[0], xyz[1], xyz[2],
                sqrtf(dx * dx + dy * dy + dz * dz), has ? "" : " (no position)");
        ++actors;
    }
    fprintf(stderr, "[survey-slots] table from %s (index %u) to %#llx (index %u): %d actors\n", where, first_index,
            (unsigned long long)last, last_index, actors);
}
static void scan_table(const char *tag) {   /* "survey table <tag>": what runtime_live_scene gives the assistant */
    RuntimeScene scene; int r = runtime_live_scene(&scene, 300);
    fprintf(stderr, "[survey-table] tag=%s result=%d table=%d actors=%d camera=%d %.2f,%.2f,%.2f facing=%.2f,%.2f,%.2f\n", tag, r,
            scene.table, scene.actors, scene.has_camera, scene.camera[0], scene.camera[1], scene.camera[2], scene.rot[2], scene.rot[5], scene.rot[8]);
    for (int k = 0; k < scene.actors; ++k)
        fprintf(stderr, "[survey-table] tag=%s actor=%s xyz=%.2f,%.2f,%.2f d=%.1f\n", tag, scene.near[k].name, scene.near[k].xyz[0],
                scene.near[k].xyz[1], scene.near[k].xyz[2], scene.near[k].distance);
}
static void report(const char *tag, const char *status, uint64_t frame, uintptr_t actor) {
    float xyz[3];
    if (actor && read_mem(actor + ACTOR_POS, xyz, sizeof xyz) && valid_xyz(xyz))
        fprintf(stderr, "[survey] tag=%s status=%s frame=%llu actor=%#llx xyz=%.6f,%.6f,%.6f\n",
                tag, status, (unsigned long long)frame, (unsigned long long)actor, xyz[0], xyz[1], xyz[2]);
    else fprintf(stderr, "[survey] tag=%s status=%s frame=%llu actor=0\n", tag, status, (unsigned long long)frame);
}
int runtime_survey_command(const char *line) {
    if (strncmp(line, "survey ", 7)) return 0;
    char op[16], tag[64]; float xyz[3] = {0}; unsigned hold = 0; int used = 0, kind = 0;
    if (sscanf(line, "survey %15s %63s %n", op, tag, &used) == 2 && used && !line[used] && !strcmp(op, "pos")) kind = 1;
    if (sscanf(line, "survey %15s %63s %n", op, tag, &used) == 2 && used && !line[used] && !strcmp(op, "actors")) kind = 3;
    if (sscanf(line, "survey %15s %63s %n", op, tag, &used) == 2 && used && !line[used] && !strcmp(op, "nearby")) kind = 4;
    if (sscanf(line, "survey %15s %63s %n", op, tag, &used) == 2 && used && !line[used] && !strcmp(op, "refs")) kind = 5;
    if (sscanf(line, "survey %15s %63s %n", op, tag, &used) == 2 && used && !line[used] && !strcmp(op, "whois")) kind = 6;
    if (sscanf(line, "survey %15s %63s %n", op, tag, &used) == 2 && used && !line[used] && !strcmp(op, "dump")) kind = 7;
    if (sscanf(line, "survey %15s %63s %n", op, tag, &used) == 2 && used && !line[used] && !strcmp(op, "list")) kind = 8;
    if (sscanf(line, "survey %15s %63s %n", op, tag, &used) == 2 && used && !line[used] && !strcmp(op, "slots")) kind = 9;
    if (sscanf(line, "survey %15s %63s %n", op, tag, &used) == 2 && used && !line[used] && !strcmp(op, "table")) kind = 10;
    used = 0;
    if (sscanf(line, "survey move %63s %f %f %f %u %n", tag, &xyz[0], &xyz[1], &xyz[2], &hold, &used) == 5 &&
        used && !line[used] && valid_xyz(xyz) && hold >= 1 && hold <= 600) kind = 2;
    if (!kind) { fprintf(stderr, "[survey] rejected: expected pos <tag>, actors <tag>, nearby <tag>, refs <tag>, whois <hex>, dump <hex>, list <hex>, slots <hex>, table <tag> or move <tag> X Y Z <1..600 frames>\n"); return 1; }
    for (const char *p = tag; *p; ++p) if (!isalnum((unsigned char)*p) && *p != '_' && *p != '-') {
        fprintf(stderr, "[survey] rejected: invalid tag\n"); return 1;
    }
    pthread_mutex_lock(&survey_lock);
    if (!survey_enabled) report(tag, "disabled", 0, 0);
    else if (request.kind || hold_left) report(tag, "busy", 0, 0);
    else {
        request.kind = kind; strcpy(request.tag, tag); memcpy(request.xyz, xyz, sizeof xyz); request.hold = hold;
        atomic_store_explicit(&runtime_survey_pending, 1, memory_order_release);
    }
    pthread_mutex_unlock(&survey_lock);
    return 1;
}
void runtime_survey_cancel_user(void) {
    if (!atomic_load_explicit(&runtime_survey_pending, memory_order_relaxed)) return;
    pthread_mutex_lock(&survey_lock);
    request.kind = 0; hold_left = 0; atomic_store(&runtime_survey_pending, 0);
    fprintf(stderr, "[survey] cancelled: user input\n");
    pthread_mutex_unlock(&survey_lock);
}
void runtime_survey_tick(uint64_t frame) {
    if (in_tick || !atomic_load_explicit(&runtime_survey_pending, memory_order_acquire)) return;
    in_tick = 1;
    pthread_mutex_lock(&survey_lock);
    uintptr_t actor = player_actor();
    if (!actor) {
        report(request.kind ? request.tag : hold_tag, "no_player", frame, 0);
        request.kind = 0; hold_left = 0;
    } else if (request.kind == 1) {
        report(request.tag, "position", frame, actor); request.kind = 0;
    } else if (request.kind == 3) {
        dump_actors(request.tag, frame, actor); request.kind = 0;
    } else if (request.kind == 4) {
        scan_nearby(request.tag, frame, actor); request.kind = 0;
    } else if (request.kind == 5) {
        scan_refs(request.tag, frame, actor); request.kind = 0;
    } else if (request.kind == 6) {
        scan_whois(request.tag); request.kind = 0;
    } else if (request.kind == 7) {
        scan_dump(request.tag); request.kind = 0;
    } else if (request.kind == 8) {
        scan_list(request.tag, actor); request.kind = 0;
    } else if (request.kind == 9) {
        scan_slots(request.tag, actor); request.kind = 0;
    } else if (request.kind == 10) {
        scan_table(request.tag); request.kind = 0;
    } else {
        if (request.kind == 2) {
            memcpy(hold_xyz, request.xyz, sizeof hold_xyz); strcpy(hold_tag, request.tag);
            hold_left = request.hold; request.kind = 0;
            report(hold_tag, "move_begin", frame, actor);
        }
        if (hold_left) {
            float rot[9] = {0}, matrix[12];
            int ok = read_mem(actor + ACTOR_ROT, rot, sizeof rot);
            for (unsigned i = 0; i < 9; i++) if (!isfinite(rot[i]) || fabsf(rot[i]) > 2) ok = 0;
            if (ok) {
                for (unsigned row = 0; row < 3; row++) {
                    for (unsigned col = 0; col < 3; col++) matrix[row * 4 + col] = rot[row * 3 + col];
                    matrix[row * 4 + 3] = hold_xyz[row];
                }
                survey_force((void *)actor, matrix, 0);
                if (!--hold_left) report(hold_tag, "move_done", frame, actor);
            } else { report(hold_tag, "invalid_rotation", frame, actor); hold_left = 0; }
        }
    }
    atomic_store_explicit(&runtime_survey_pending, request.kind || hold_left, memory_order_release);
    pthread_mutex_unlock(&survey_lock);
    in_tick = 0;
}
#endif   /* GAME_BOTW */
