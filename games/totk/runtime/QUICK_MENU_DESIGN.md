# Quick menu — approved A v2

The approved A v2 concept follows the original in-game options screen: a full-screen settings surface, centered title and three category tabs, a settings column, and contextual help to its right. Narrow windows place help below the scrolling controls. FPS and diagnostic details belong to the collapsed strip rather than the main settings hierarchy.

## Visual rules

- Warm ivory text and fine dividers: `quickInk`, RGB 0.99 / 0.975 / 0.85.
- Orange marks selected values: `quickAccent`, RGB 0.88 / 0.40 / 0.015.
- Pale yellow marks hover and keyboard focus: `quickGold`, RGB 1.00 / 0.90 / 0.50.
- Dark translucent surfaces and a blurred game backdrop separate text from the scene. Keep decoration quiet and preserve readable contrast.
- Top and bottom horizontal dividers share normalized endpoints **x = 0.155 and x = 0.845** of the menu width. Both center motifs use **x = 0.5**. Derive all three anchors from the same bounds; do not independently offset either divider.
- Use generous spacing, clear value columns and one coherent focus treatment. Preserve the game-like visual hierarchy rather than adding desktop-style card chrome.

## Interaction

Graphics, Controls and Assistance are separate tabs. Contextual descriptions follow the selected or hovered setting. Value controls support previous / next mouse clicks; binary controls select the clicked on / off state. Tab and Shift-Tab switch categories, arrow keys navigate and adjust settings, and Escape collapses to the FPS strip. Opening releases captured mouse input; collapsing restores mouse-camera control when enabled.

The overlay does not pause gameplay. Controller-layout selection is a setting, not a claim of gamepad navigation support. Settings use the existing shared persistence and runtime APIs; startup-only options remain identified in All settings.
