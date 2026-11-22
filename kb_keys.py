#!/usr/bin/env python3
"""Keyboard key map for the K70 RGB PRO.

Slots follow HID usage order: usage - 4 is the slot, so A is 0, B is 1, C is 2
... Z is 25, then the digits, Enter, Escape and the rest of the main block.
The last block holds modifiers and media keys; only the four confirmed by the
lighting tests are labelled here, the rest stay "Special n" until named in the
panel.
"""

MAIN = (
    [chr(ord("A") + i) for i in range(26)]
    + [str(d) for d in range(1, 10)] + ["0"]
    + ["Enter", "Esc", "Backspace", "Tab", "Space",
       "-", "=", "[", "]", "\\", "#", ";", "'", "`", ",", ".", "/",
       "Caps Lock"]
    + [f"F{i}" for i in range(1, 13)]
    + ["Print Screen", "Scroll Lock", "Pause", "Insert", "Home", "Page Up",
       "Delete", "End", "Page Down", "Right", "Left", "Down", "Up",
       "Num Lock", "KP /", "KP *", "KP -", "KP +", "KP Enter",
       "KP 1", "KP 2", "KP 3", "KP 4", "KP 5", "KP 6", "KP 7", "KP 8", "KP 9",
       "KP 0", "KP .", "Non-US \\"]
)

CONFIRMED = {
    97: "Left Ctrl",
    98: "Left Shift",
    101: "Right Ctrl",
    102: "Right Shift",
}

SPECIAL_SLOTS = [97, 98, 99, 101, 102, 105, 106, 107, 108, 109, 110, 111,
                 122, 123, 124, 125, 126, 128, 137, 138, 140, 141]

KEYS = [(slot, MAIN[slot]) for slot in range(len(MAIN))]
KEYS += [(slot, CONFIRMED.get(slot, f"Special {index + 1}"))
         for index, slot in enumerate(SPECIAL_SLOTS) if slot not in CONFIRMED]
KEYS += [(slot, name) for slot, name in CONFIRMED.items()]
KEYS.sort(key=lambda item: item[0])

LABELS = dict(KEYS)
