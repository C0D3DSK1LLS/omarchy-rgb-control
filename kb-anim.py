#!/usr/bin/env python3
"""Animate the K70 through one long-lived HID session.

Started by the panel (or by the lighting service at login) and left running:
it owns kb-colour.py --stream for its whole life, so the keyboard never sees
the open/close churn that kept knocking it into its bootloader.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import kbfx  # noqa: E402

CAPTURE = HERE / "k70-capture.json"
FPS = 20.0


def template_slots():
    frames = json.loads(CAPTURE.read_text())["frames"]
    packet = next(bytes.fromhex(row["hex"]) for row in frames if row["number"] == 10948)
    return [index for index in range(142)
            if packet[9 + index * 3:12 + index * 3].hex() == "1b33ff"]


def main():
    if len(sys.argv) < 3:
        print("usage: kb-anim.py EFFECT COLOURS [BRIGHTNESS]", file=sys.stderr)
        return 64
    name = sys.argv[1]
    spec = kbfx.BY_NAME.get(name)
    if not spec:
        print(f"unknown keyboard effect {name!r}", file=sys.stderr)
        return 2
    effect, defaults, _labels = spec
    palette = [tuple(int(token[i:i + 2], 16) for i in (0, 2, 4))
               for token in sys.argv[2].split(",") if token] or defaults
    brightness = int(sys.argv[3]) if len(sys.argv) > 3 else 80
    level = max(0, min(100, brightness)) / 100.0

    paint = template_slots()
    env = dict(os.environ, RGB_KB_WRITES="1")
    child = subprocess.Popen([sys.executable, str(HERE / "kb-colour.py"), "--stream"],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, text=True, env=env)

    running = True

    def stop(*_args):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    started = time.monotonic()
    due = started
    while running and child.poll() is None:
        moment = time.monotonic() - started
        values = effect(moment, len(paint), palette)
        line = ["1b33ff"] * 142
        for slot, colour in zip(paint, values):
            scaled = tuple(int(channel * level) for channel in colour)
            line[slot] = "%02x%02x%02x" % scaled
        try:
            child.stdin.write(",".join(line) + "\n")
            child.stdin.flush()
        except (BrokenPipeError, OSError):
            break
        due += 1 / FPS
        delay = due - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            due = time.monotonic()

    try:
        child.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
