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
