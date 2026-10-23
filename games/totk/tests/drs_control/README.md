# Automatic resolution (1.4.3, macOS)

`TOTK_DRS=1` replaces the game's final dynamic-resolution scale with a host
controller. Defaults: 16.7 ms target, 0.67 minimum, full scale maximum. Set
`TOTK_DRS_MIN` (0.5–1) or `TOTK_DRS_TARGET_MS` (4–100 ms) to override. Without
a valid explicit target, a positive `TOTK_FPS_CAP` supplies `1000 / cap`
milliseconds, with the cap clamped to 30–240 FPS to match the scheduler.
Malformed, non-finite or out-of-range targets fall back to the cap, then 16.7 ms.
Malformed/non-finite minimum values use 0.67; valid numeric minima clamp to 0.5–1. The controller uses
completed GPU timings, median filtering, discrete scale levels and hysteresis;
a missing GPU timer falls back to present intervals after 60 frames. Interval
fallback cannot distinguish CPU cost from GPU cost or find headroom under a cap.

The thread-safe runtime panel API is declared in `runtime/game_patches.h`:
`runtime_drs_set`, `runtime_drs_enabled`, `runtime_drs_scale`,
`runtime_drs_set_min`, and `runtime_drs_set_target_ms`. Changes apply on the next
present. Minimum/target changes retain the current level where allowed and
restart the measurement window. Disabling restores native DRS, or full scale
when `TOTK_FIXED_RES=1` was requested at startup. An enabled DRS overrides fixed
resolution. iOS and exported iOS binaries do not install this patch.

The veneer replaces the checked `mov w9,w23` at main+0x5848a8, preserving the
surrounding return packing and all other registers. Its data is at loader page
+48..55; code uses text padding +928..955 after Vert+ and before rewriter code.
No runtime text writes occur: live changes update one atomic data word.

Run `python3 -m unittest discover -s tests -p test_drs_control.py` from the repo
root. The controller probe covers sustained loads, recovery, noisy timings, CPU
bottlenecks, delayed samples, GPU clock changes, probe backoff and minimum
changes. The macOS runtime probe checks actual patch encoding and live APIs
using a synthetic module and GPU sample source. This does not replace a real
1.4.3 gameplay check of image quality, resource allocation and frame pacing.
