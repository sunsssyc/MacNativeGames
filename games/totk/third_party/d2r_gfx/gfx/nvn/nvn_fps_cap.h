// TOTK 帧率上限（hle_nvn.c）：启动时 TOTK_FPS_CAP=<n>，运行中由设置面板调 nvn_set_fps_cap。纯 C 原型，前端（runtime/frontend.m）可直接包含。
// TOTK frame-rate cap (hle_nvn.c): TOTK_FPS_CAP=<n> at start, nvn_set_fps_cap from the settings panel while the game runs. Plain C
// prototypes, so the frontend (runtime/frontend.m) can include this header.
#pragma once
/* 0 = off (the uncapped default: our own clock with a ceiling, the game's present interval honoured); otherwise clamped to
   30..240. Environment values must be whole decimal integers; malformed values disable the cap,
   positive overflow clamps to 240. Any thread, at any time: it is one atomic value, the present path takes it over at the next frame and logs one line
   when its pacing changes. Overrides TOTK_FPS_CAP. */
void nvn_set_fps_cap(int cap);
/* The cap set (TOTK_FPS_CAP until nvn_set_fps_cap is called), 0 = off. */
int nvn_fps_cap(void);
/* The cap the present path paces by at the moment, 0 when it does not: off, suspended while MetalFX frame interpolation (key 2)
   keeps its own pacing or while the game holds 30 fps, or not applied (TOTK_REALTIME=0, TOTK_FPS60=0, DM_PRESENT_HZ). */
int nvn_fps_cap_pacing(void);
