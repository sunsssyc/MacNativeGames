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

## Jump flicker correction

Do not crossfade two sprites with two ordinary source-over draws: at 50/50,
opaque overlap has only 75% alpha and the game background flashes through.
Blend premultiplied colors additively inside an isolated transparent layer, then
composite that layer once. Test opaque overlap at 0/25/50/75/100% against both
transparent and colored backgrounds; the avatar probe covers this.

Latch rising→falling for one airborne interval instead of switching on every
near-zero vertical-speed sample. Confirm ground contact across two samples before
landing. A single failed guarded read can hold the previous visual state for at
most 180 ms; explicit paused state, stale samples and identity changes still reset.
Tests inject apex jitter, a one-sample false landing and brief/long read failures.

## Primary animation commands and airborne playback (supersedes velocity fallback)

Do not identify climbing or free fall from InAir/vertical velocity alone. The
previous 350 ms stationary-air fallback failed while climbing moved. In a muted
private 1.4.3 session the primary AS graph command reads Wait, Move, Jump, Land,
ClimbMove, ClimbWait, WallOff and Fall as the corresponding actions happen.

Verified chain after the existing AS controller/blackboard checks:
- Controller +0x18: slot count 7; +0x20: inline slot buffer pointer.
- First slot +0: primary graph instance.
- Instance +0x10: current command string; +0x28: owning blackboard;
  +0x90: owning controller. Validate both backlinks and bounded ASCII name.
- Re-read the slot instance and command pointer, actor generation/state and
  controller/blackboard ownership before publishing. Failure stays invalid.

Climb*/Ladder*/WallOff map to explicit climbing classification and quiet idle
visuals until a matching companion climb animation exists. Only Jump/JumpMove,
Fall or explicit gliding justify airborne visuals. Unknown airborne commands
stay neutral. Land starts recovery immediately; Wait/Move end it immediately.
The old extra ground-confirmation delay and fixed landing hold are not applied
when a verified command exists. Never label this as an authored climb animation.

The shared classifier now polls at up to 30 Hz, and airborne crossfades take
50 ms with the same constant-alpha compositor. Original Jump was nearly a held
pose, so replaying it for both ascent/descent looked frozen. Render Jump_St into
Jump for takeoff; use Jump_Ed frames 1–2 for descent and 2–16 for contact/recovery.
Do not use later contact frames in descent: crouching before landing also clipped
the skirt. New jump/fall/land assets have 6/6/8 frames at 30 fps; landing playback
fits 200 ms. Validate each alpha boundary (20 frames passed, minimum 8 px margin).

Live verification recorded 78 valid observations: three stationary jumps, one
running jump, moving and stationary climbing, wall release and landing. Each
jump sampled jump→fall→land→idle/run at roughly 0/0.21/0.43/0.64 seconds relative
to its first sample. These are animation phase times, not end-to-end latency
measurements (the diagnostic command stream samples at about 10 Hz). Moving and
stationary climb samples stayed classified as climb with idle visuals. WallOff
remained neutral, then Fall/Land/Wait followed correctly. Wait for autoload to
finish and a valid Wait command before driving the test; Actor presence alone
is insufficient, and DemoWait can occur during loading.

## Hand-held weapons and attack clips

Riju's actor pack references Weapon_Sword_152_Main/Sub; their ModelInfo points to
Weapon_Sword_052. Use the local model and its albedo, not a guessed sword ID.
`attach_weapons.py` imports that model and weights all its vertices rigidly to
Weapon_L / Weapon_R. The importer has already converted Y-up to Blender Z-up:
undo that conversion once, then apply the character's rest socket matrix. Do not
parent at Blender's bone tail. Keep the *_Blade_Hide shape: it is the detachable
blade visibility group; omitting it leaves only the handle/guard. Weapons use
half-scale for the mini companion and do not participate in body floor anchoring.

Render armed combat idle, armed Common_Move_Run and a new Combat_Attack clip.
The broad Combat_Move_Run stance exceeds the fixed dock canvas with swords.
Combat_Attack removes travelling root/pelvis height and preserves the fixed camera
and original character size. Armed clips use a wider 256×288 transparent canvas;
other clips stay 192×288. The fixed 128×144 dock target and shared 256-pixel width
budget keep apparent scale identical across states. Source rectangles/packing
use per-clip width; face crops use the original 192-pixel body region. Check every frame with `check_frames.swift`; a
single ready-pose render misses clipping during overhead swings and wide slashes.
Do not ship full native arena motion if sword tips are cut off. Weapons are shown
in these combat clips; social, neutral and airborne clips remain unarmed.

A combat flag is not an attack. Grounded primary sword commands CutS1–CutS4/CutSF,
CutDash, CutReverse and CutJustRush/Finish select attack immediately. A distinct
command restarts the strike even if the visual state is still attack. Repeated
polls of the same command must not reset playback. End the strike immediately
when the primary command changes to locomotion/stance; equip/charge/face commands
must not create slashes. Combat_Attack is a compact 24-frame, 30 fps two-sword
reaction, not an exact retarget of each Link weapon's combo. Other weapon types
and airborne attacks need separately verified commands and authored visuals.

Validation for the weapon addition: 54 armed frames passed alpha-bound checks
with a minimum 12 px margin. The pure decoder/classifier test and four AppKit
regression suites passed, including continuous-command versus new-combo restart.
Ground attack command routing is checked against Player.root.asb and fixtures;
new live combat verification remains pending while the user's formal game runs.
