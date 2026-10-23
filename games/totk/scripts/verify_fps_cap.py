#!/usr/bin/env python3
"""Run the production pacing policy and its probe without ROM files or a Metal device.

Only external display/interpolation/game-clock inputs are stubbed. The cap API,
present configuration, policy and production probe are compiled directly
from hle_nvn.c, so this never maintains a second implementation of the policy.
"""
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'third_party/d2r_gfx/gfx/nvn/hle_nvn.c').read_text()

def section(start, end):
    return source[source.index(start):source.index(end, source.index(start))]

prefix = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#define LOG(...) do { fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); } while (0)
#define die(...) do { LOG(__VA_ARGS__); exit(2); } while (0)
#define UNCAPPED_INTERVAL_FROM_ENV(e) ((e) && atoi(e))
#define TARGET_OS_IPHONE 0
#define MFX_OFF 0
#define MFX_HALF 1
#define MFX_30 2
#define MFX_MAX 3
static int mode, pending, held, detclock, display_hz = 120;
static int mfx_enabled(void) { return mode; }
void mfx_set(int m) { pending = m; }
int mfx_latch(void) { mode = pending; return mode; }
static int game_holds_30(void) { return held; }
static int dm_detclock_enabled(void) { return detclock; }
static int mtl_display_hz(void) { return display_hz; }
static int mtl_link_hz(void) { return display_hz; }
typedef struct { int interval; } win_t;
static int g_hz = -1, g_paced_hz, g_display_mode, g_uncapped;
'''
main = r'''
#define CHECK(c) do { if (!(c)) die("fps-cap extra check failed at %d: %s", __LINE__, #c); } while (0)
int main(int argc, char **argv) {
    if (argc == 2) { CHECK(nvn_fps_cap() == atoi(argv[1])); return 0; }
    win_t w = {.interval = 2};
    /* Exercise the actual environment eligibility, not just direct global setup. */
    const char *names[] = {"TOTK_REALTIME", "TOTK_FPS60", "DM_PRESENT_HZ"};
    nvn_set_fps_cap(60);
    for (int i = 0; i < 3; ++i) {
        setenv(names[i], i == 2 ? "60" : "0", 1); g_hz = -1;
        (void)present_period(&w); CHECK(!cap_now()); unsetenv(names[i]);
    }
    g_hz = -1; CHECK(present_period(&w) == 1000000000ull / 60);
    held = 1; CHECK(present_period(&w) == 1000000000ull / 30);
    CHECK(nvn_fps_cap_pacing() == 0 && nvn_fps_cap() == 60);
    held = 0; CHECK(present_period(&w) == 1000000000ull / 60);
    detclock = 1; (void)present_period(&w); CHECK(!cap_now() && !nvn_fps_cap_pacing());
    detclock = 0;
    dm_nvn_probe_present_interval();
    /* Calling the setter before the first getter overrides even an invalid env. */
    atomic_store(&g_fps_cap, -1); setenv("TOTK_FPS_CAP", "garbage", 1);
    nvn_set_fps_cap(40); CHECK(nvn_fps_cap() == 40);
    return 0;
}
'''
policy = section('#define FPS_CAP_MIN', 'static double g_rt_comp_ms;')
pacing = section('#define UNCAPPED_HZ', 'int (*g_nvn_loadscreen_up)')
env = {k: v for k, v in os.environ.items() if not k.startswith(('TOTK_', 'DM_PRESENT', 'DM_DETCLOCK'))}
with tempfile.TemporaryDirectory(prefix='totk-fps-cap-') as tmp:
    cfile, exe = Path(tmp) / 'probe.c', Path(tmp) / 'probe'
    cfile.write_text(prefix + policy + pacing + main)
    subprocess.run(['cc', '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(exe)], check=True)
    run = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError(run.stderr)
    pacing_cases = int(re.search(r'\[present-interval\] (\d+) pacing cases passed', run.stderr)[1])
    cases = {'': 0, '0': 0, '-5': 0, '10': 30, '60': 60, '240': 240, '500': 240,
             '2147483648': 240, '999999999999999999999999999': 240,
             '-999999999999999999999999999': 0, 'garbage': 0, '60junk': 0}
    for value, expected in cases.items():
        subprocess.run([str(exe), str(expected)], env={**env, 'TOTK_FPS_CAP': value}, check=True)
    for negative in ('11', '20', '32'):
        run = subprocess.run([str(exe)], env={**env, 'TOTK_PROBE_NEGATIVE': negative}, capture_output=True, text=True)
        assert run.returncode == 2 and 'present interval probe:' in run.stderr, run.stderr
print(json.dumps({'ok': True, 'production_pacing_cases': pacing_cases, 'environment_cases': len(cases),
                  'negative_controls': [11, 20, 32], 'gpu_tested': False}))
