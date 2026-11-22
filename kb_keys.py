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
       "Num Lock", "Num /", "Num *", "Num -", "Num +", "Num Enter",
       "Num 1", "Num 2", "Num 3", "Num 4", "Num 5", "Num 6", "Num 7", "Num 8", "Num 9",
       "Num 0", "Num .", "Non-US \\"]
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


LABEL_FILE = "/home/jimmy/.config/c0d3d/rgb-key-labels.json"


def load_labels():
    import json, os
    try:
        with open(LABEL_FILE) as handle:
            data = json.load(handle)
        return {int(slot): str(name) for slot, name in data.items()}
    except (OSError, ValueError):
        return {}


def save_label(slot, name):
    import json, os
    labels = load_labels()
    labels[int(slot)] = name
    try:
        os.makedirs(os.path.dirname(LABEL_FILE), exist_ok=True)
        temp = LABEL_FILE + ".tmp"
        with open(temp, "w") as handle:
            json.dump({str(k): v for k, v in labels.items()}, handle)
        os.replace(temp, LABEL_FILE)
    except OSError:
        pass
    LABELS[int(slot)] = name
