# Riju companion motion

The dock and conversation header use transparent frames rendered from the rounded-mouth Blender model with twelve native skeletal clips. These are real skinned poses, not transforms applied to a still illustration. The game does not load the GLB or run a second 3D renderer.

## States

- Idle: original breathing and subtle limb motion.
- Idle variety: fidget (look-around/weight shift), relaxed (hands at hips), and ponder (hand at chin). A gesture follows 22, 28, 24 or 32 seconds of quiet visible idle time. Conversation or dragging interrupts the gesture and resets the quiet interval.
- Greeting / welcome: two greetings alternate on pointer entry, with an 8-second cooldown. Welcome also acknowledges a finished request or drag release.
- Surprised: a restrained hand-to-chest pose while held/dragged; it does not change the click bounds.
- Listening: original relaxed listening stance while recording.
- Ponder → thinking: hand moves to chin, then the native thinking pose loops during a pending request.
- Reply / explain / cheerful: normal speech, hand-raised explanation and open-palm response alternate every 5 seconds only while audio is actually playing. These vary gestures, not interpreted emotions or phoneme lip sync.

Same fixed camera and foot anchor in all clips. 192×288 frames at 15 fps support the dock's 96×144 point size at Retina resolution. One-shot gestures blend back to idle in bone space; loops ease their final samples into the first pose. Playback changes cross-fade over 160 ms. The panel uses a face crop of these same frames. Timers stop for hidden views and Reduce Motion uses a static frame. Missing assets fall back to the existing still portrait. Shared decoded-image cache budget: 48 MiB.

## Rebuild

Use Blender with the approved, locally held rig/material scene:

```
Blender --background --python render_actions.py -- --scene /absolute/path/to/riju-mini-palette-toon.blend --output /absolute/path/to/frames
xcrun swiftc pack_actions.swift -o /tmp/pack-actions
/tmp/pack-actions /absolute/path/to/frames
```

The scene must include all named native actions used by render_actions.py; missing actions fail before rendering. Copy only manifest.json and the twelve top-level PNG atlases into runtime/assets/riju-actions/. build_app.py includes these assets in the Mac app. Do not copy individual frame folders into the bundle.

Validate with tests/test_hint_avatar.py and tests/test_hint_overlay.py on macOS with WindowServer access. The avatar test exercises all twelve clips, speech variants, idle scheduling and interruption, greeting cooldown, frame progression, fixed click bounds, header animation and hidden-view timer teardown. No microphone or model request is started by it.

## Live Link activity (1.4.3)

`runtime/player_activity.h` is the guarded read adapter; `world_survey.c` locates the
resident player without scanning the whole actor table. `companion_activity.h`
classifies the sample locally. `hint_avatar.inc` samples at 10 Hz and gives dialogue,
voice and dragging priority. No model requests are made by this feature.

The new sprite clips are `walk`, `run`, `jump`, `fall`, `land`, `combat` and
`combat_run`. Gliding currently uses the same held airborne pose as falling; it
does not pretend to include a parasail. Combat means the game's battle/aim stance,
not a confirmed enemy encounter. Water and standing rides return to idle.

To bake locomotion onto an approved rig (requires local game assets and bfrespy):

```sh
blender -b --python games/totk/tools/companion/bake_locomotion.py -- \
  --parser /absolute/path/to/io_scene_bfres \
  --assets /absolute/path/containing/game-decoded-and-game-original \
  --scene /absolute/path/to/approved-rig.blend --output /absolute/path/to/baked
blender -b --python games/totk/tools/companion/render_actions.py -- \
  --scene /absolute/path/to/baked/riju-companion-actions.blend \
  --output /absolute/path/to/frames --only walk,run,jump,fall,land,combat,combat_run
swift games/totk/tools/companion/pack_actions.swift /absolute/path/to/frames
```

`--only` merges an existing manifest. Keep all original gesture sheets when adding
these sheets to the application's manifest. Root travel is removed for walk/run;
lowest deformed geometry is kept above the standing floor to avoid skirt clipping.
The character's saved dock position and hit rectangle never follow Link's position.

Regression tests:

```sh
python3 -m unittest discover -s tests -p test_companion_activity.py -v
python3 -m unittest discover -s tests -p test_hint_avatar.py -v
python3 -m unittest discover -s tests -p test_hint_overlay.py -v
```

In an owned test session with `TOTK_HINT_TEST=1`, `hint state <absolute-json-path>`
includes the decoded activity and a diagnostic stage when it is unavailable.

Freshness is checked in two ways: sample age and an observation fingerprint of the
AS values plus world position. If the observation does not change for 0.6 seconds,
movement reactions return to idle. This is a conservative stale-state fallback,
not a full game-menu detector; perfectly static battle stance can also relax to idle.

Validated on 2026-10-25 with a muted copied 1.4.3 save: stand/run/stop,
jump → fall → land, bow/combat, inventory freezing an old 5.555 speed while
the pet returns to idle, and movement resuming after inventory closes. All 19
clip assets (515 frames) matched the built bundle. Seven added clips (87 frames)
passed per-frame alpha-margin validation. Water, rides and glide were not exercised
in that live session; their classifier branches have deterministic coverage/fallbacks.
