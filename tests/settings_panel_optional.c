/* Stand-ins for the frame-rate cap and the dynamic resolution controller (other features), with the exact prototypes the
   settings window declares weak (games/totk/runtime/settings_panel.m), for tests/settings_panel_probe.m, which counts. */
extern int probe_cap_calls, probe_drs_calls;
extern float probe_drs_min, probe_drs_target;
static int cap, drs;
void nvn_set_fps_cap(int c) { cap = c; probe_cap_calls++; }
int nvn_fps_cap(void) { return cap; }
int probe_cap_paused;
int nvn_fps_cap_pacing(void) { return probe_cap_paused ? 0 : cap; }
void runtime_drs_set(int on) { drs = on; probe_drs_calls++; }
int runtime_drs_enabled(void) { return drs; }
float runtime_drs_min(void) { return probe_drs_min; }
float runtime_drs_scale(void) { return drs ? 0.87f : 1.0f; }
void runtime_drs_set_min(float m) { probe_drs_min = m; probe_drs_calls++; }
void runtime_drs_set_target_ms(float ms) { probe_drs_target = ms; probe_drs_calls++; }
