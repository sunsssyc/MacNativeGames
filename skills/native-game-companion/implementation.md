# Project implementation notes

## Current source anchors

- `games/totk/runtime/world_survey.c`: guarded `mach_vm_read_overwrite`, resident player lookup, version gate.
- `games/totk/runtime/player_activity.h`: 1.4.3 AS blackboard decoding.
- `games/totk/runtime/companion_activity.h`: pure state machine, speed hysteresis, freshness and landing.
- `games/totk/runtime/hint_avatar.inc`: 10 Hz shared sampling, 30 Hz UI redraw, 15 fps sprite frames, conversation priority, 160 ms transitions, 48 MiB cache.
- `games/totk/tools/companion/bake_locomotion.py`, `render_actions.py`, `pack_actions.swift`: native local animation → approved skinned rig → RGBA sheets.
- `tests/companion_activity_probe.c`, `test_hint_avatar.py`, `test_hint_overlay.py`: memory, time-sequence and AppKit regression coverage.

## Versioned schema

TOTK 1.4.3 `AS/Player.root.asb` declares 15 int, 77 float, 65 bool and 1 Vec3 values. The ASB file-order indices are not the enum ordinals in older reverse-engineering repositories. Decode the actual local game's ASB; never silently reuse an older version's numbers.

Relevant file indices: float `LinearVelXZ=4`; bool `InAir=14`, `InWater=15`, `BattleMode=16`, `IsAiming=19`, `IsOnWater=41`, `SlowGlideMode=45`, `FastGlideBow=46`, `IsGlide=47`, `IsStandingRide=63`; Vec3 `LinearVel=0`.

Primary format/layout references used during this work:
- https://github.com/aquacluck/totk-lotuskit (`engineActor.hpp`, `engineComponent.hpp`, `as.hpp`, `bbBlackboard.hpp`)
- https://github.com/dt-12345/asb (ASB blackboard header and name-table layout)

These are research leads, not proof that the same memory layout is valid in another build. The decoder validates the exact schema and component ownership and fails closed. Preserve the unsupported-version fallback.

## Action-specific lessons

Keep the rounded-mouth approved blend as input; reopening the original BFRES would discard material and lip work. Native clips can be mirrored onto the same 173-bone rig even when only 142 bones have tracks, by resetting untracked bones to rest. Root travel in local coordinates is not necessarily Blender Z world movement. Remove only root travel; preserve hip compression and limb transforms.

Grounding by ankle/toe height alone misses skirt vertices below the feet. Check deformed mesh bounds and alpha margins. The 87 added movement frames were checked for nonempty alpha and >1 px margin; the corrected minimum was 8 px. Do not cite those results for subsequently changed renders without rerunning the check.

The sprite runtime does not render a live 3D model. Gliding currently reuses a held airborne pose. Record this limitation rather than describing it as a dedicated glide animation.

## Verified runtime behavior (2026-10-25)

A private muted 1.4.3 session produced speed 5.55 while running, positive/negative
vertical velocity and InAir during a jump, then landing, and BattleMode/IsAiming
while drawing the bow. The actual pet selected run → jump → fall → land and combat.
The game's inventory can leave Actor state active and AS values frozen; actor state
alone is not a menu detector. Fingerprint AS values plus world position and relax
to idle after 0.6 seconds without a new observation. Position prevents false expiry
during constant-speed movement. A perfectly static battle stance may conservatively
relax to idle too; do not describe this fallback as exact menu detection.

The final inventory test held forward, opened inventory, and observed the old speed
5.555 remaining in AS while the pet returned to idle. Closing inventory and moving
again restored run. Stand/run/jump/fall/land/bow and this stale-state sequence were
verified in a muted copied save. Swimming/riding/gliding were not live exercised.

When launching the native binary directly, preserve the launcher's
`TOTK_ROMFS_PROOF_DIR` outside the app. Otherwise the runtime may write
`.romfs-verified-v1` into sealed Resources and break `codesign --verify --strict`.
Remove only the test-created cache after stopping that test; do not re-sign unrelated
changes or remove unknown resources to hide signature errors.
