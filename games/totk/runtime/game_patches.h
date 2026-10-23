#pragma once
#include "runtime.h"

/* TOTK version-specific game-code patches, applied to the loaded main module after relocation and before its text is sealed.
   Every site is checked against the original instruction word first; a mismatch stops the boot. */
void runtime_game_patches(Module *main_module);

/* 1.4.3 automatic resolution; setters are thread-safe, applied next present.
   Default minimum 0.67 (range 0.5..1), default target 16.7 ms. Disabled restores
   native game DRS, or boot-time TOTK_FIXED_RES. Unsupported builds report off. */
void runtime_drs_set(int enabled);
int runtime_drs_enabled(void);
float runtime_drs_scale(void);
float runtime_drs_min(void);
void runtime_drs_set_min(float scale);
void runtime_drs_set_target_ms(float ms);
