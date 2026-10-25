---
name: native-game-companion
description: Implement and validate a native game overlay companion with skinned character animations driven by live runtime state. Use for this project's Riju companion, action-state readers, BFRES-to-Blender animation baking and sprite playback; not ChatGPT Work pets.
---

# Native game companion

Work from the actual checkout and deployed application, not an earlier chat's presumed branch. Keep the runtime reader, animation classifier and presentation separate. See [implementation notes](implementation.md) for the current TOTK adapter and asset pipeline.

## Runtime behavior

Use the game's animation blackboard or another verified live state source. A held key is intent, not proof of movement; a save file is historical; a Player object may remain on the title screen. Do not label position-only information as grounded, jumping or fighting.

Version-gate memory layouts. Read through guarded memory copies, validate chain ownership, array counts, finite values and actor identity before publishing a sample. Reset on unload, identity change or stale data. Unknown means quiet idle; do not substitute stale movement. Do not invoke guest virtual functions from the AppKit thread.

Keep sampling bounded and local. The resident player list is appropriate; a full nearby-actor scan, model call or screenshot per animation frame is not. Use one shared sample for portrait and dock. Give recording, speaking and dragging priority over gameplay reactions. Hysteresis prevents walk/run flicker; landing is an edge-triggered one-shot. A combat stance flag does not prove an enemy is nearby or an attack occurred.

## Skeletal animation and rendering

Use the latest approved mesh and materials as the bake input. For native local bone transforms, apply inverse rest-local × animated-local before keying the pose. Bake location, quaternion rotation and scale for each bone. Preserve existing actions with fake users.

Remove travel from the root for an anchored screen companion, without removing limb motion or knee compression. Render all clips with one camera, size and foot anchor. Check every frame's alpha bounds, not just a contact sheet: crouching skirts can extend below the toes. Interpolate rotations as quaternions. Clear the active action before assigning interpolated pose matrices, or Blender can overwrite them at render time.

Pack RGBA sheets only after validating nonempty frames and clear edge margins. Check looping seams, transition frames and consistent apparent scale. Use a bounded shared image cache; stop animation timers when hidden or Reduce Motion is enabled. Animation must not move the drag hit target or persisted dock position.

## Validation and deployment

Test the pure decoder with fake memory, including wrong versions/counts, broken pointers and invalid values. Test the state machine with time sequences (movement hysteresis, airborne→landed, pause, stale samples, reload). Then test actual AppKit priorities and timer lifecycle.

A fake-memory test verifies logic, not reverse-engineered offsets. Confirm live standing, moving and jumping readings in a muted, independent-save game instance. Use the project's GameSlot ownership mechanism. If autoload appears stuck, inspect the stack and pause owner: a settings pause can stop frame-end commands and screenshots while the UI remains responsive. Do not interpret that as a loading failure.

Before updating an application, identify the running binary and profile. Wait for a user-owned game to close; do not terminate it or overwrite it. Verify the bundled assets and executable belong to the tested commit. Record unsupported states and unverified interpretations explicitly.
