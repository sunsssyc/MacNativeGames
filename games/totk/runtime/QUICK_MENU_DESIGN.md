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

The expanded overlay pauses the game frame producer cooperatively at the next presentation boundary after the loading overlay is dismissed. Collapsing or hiding releases only its own pause request; existing game menus and focus state remain untouched. Audio and I/O workers keep running. The compact HUD shows only the measured FPS and a settings entry; full performance details are available on hover. Controller-layout selection is a setting, not a claim of gamepad navigation support. Every setting lives in this menu (Command-, opens it too; there is no separate desktop-style settings window): settings_panel.m keeps the shared model, persistence and runtime calls, and startup-only options say "after restart" beside their name while the choice differs from the running one. Assistance also chooses the hint assistant's AI channel (assistant.json "channel"), with each channel's availability from the hint service.
