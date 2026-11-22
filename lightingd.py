#!/usr/bin/env python3
"""Owns the RAM lighting, with or without the panel open.

The panel writes a small state file; this service is the only process that
touches the sticks. That way closing the window cannot stop an effect, and the
last look is restored on the next login.

State file: ~/.local/state/ralph/rgb-ram-state.json

    {"kind": "hardware", "mode": 1, "speed": 2, "colour": "#00ff41",
     "brightness": 80, "sticks": null}

    {"kind": "custom", "effect": "Cylon", "colours": [[220,20,60],[255,255,255]],
     "brightness": 80, "sticks": [[7, 57], [7, 58]]}

`sticks` null means every module; otherwise a list of [bus, address] pairs.
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

import effects  # noqa: E402
import ram  # noqa: E402

STATE = Path(os.path.expanduser("~/.local/state/ralph/rgb-ram-state.json"))
KB_STATE = Path(os.path.expanduser("~/.local/state/ralph/rgb-keyboard-state.json"))
LOG = Path(os.path.expanduser("~/.local/state/ralph/diagnostics/rgb-lighting.log"))
FPS = 20.0
POLL = 0.25

stopping = False


def log(message):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H:%M:%S")
    with LOG.open("a") as handle:
        handle.write(f"{stamp} {message}\n")
    if LOG.stat().st_size > 256 * 1024:
        lines = LOG.read_text().splitlines()[-500:]
        LOG.write_text("\n".join(lines) + "\n")


def chosen_sticks(state):
    sticks = ram.find_sticks()
    if not sticks:
        return []
    wanted = state.get("sticks")
    if not wanted:
        return sticks
    keys = {(int(bus), int(address)) for bus, address in wanted}
    picked = [stick for stick in sticks if (stick.bus, stick.address) in keys]
    return picked or sticks


def paint_hardware(state):
    sticks = chosen_sticks(state)
    if not sticks:
        log("no RAM controllers found yet")
        return False
    mode = int(state.get("mode", ram.MODE_STATIC))
    speed = int(state.get("speed", 2))
    colour = state.get("colour") or "#00ff41"
    brightness = int(state.get("brightness", 80))
    ram.set_effect(sticks, mode, colour, brightness, speed)
    log(f"hardware mode={mode} speed={speed} colour={colour} at {brightness}% on {len(sticks)} stick(s)")
    return True


def paint_custom(state, stamp):
    """Animate until the state file changes again."""
    sticks = chosen_sticks(state)
    if not sticks:
        log("no RAM controllers found yet")
        return False
    name = state.get("effect") or ""
    spec = effects.BY_NAME.get(name)
    if not spec:
        log(f"unknown effect {name!r}")
        return False
    effect, defaults, _labels = spec
    palette = [tuple(colour) for colour in (state.get("colours") or defaults)]
    brightness = int(state.get("brightness", 80))
    ram.prepare_direct(sticks)
    log(f"effect {name} on {len(sticks)} stick(s), palette {palette}")
    started = time.monotonic()
    due = started
    last = None
    last_check = 0.0
    while not stopping:
        now = time.monotonic()
        if now - last_check > 0.2:
            last_check = now
            try:
                if STATE.stat().st_mtime != stamp:
                    return True          # new command waiting in the state file
            except OSError:
                return True
        moment = time.monotonic() - started
        try:
            frame = effect(moment, len(sticks), sticks[0].leds, palette)
            last = ram.write_frame(sticks, frame, brightness, last)
        except OSError as exc:
            log(f"write failed: {exc}")
            time.sleep(0.2)
        due += 1 / FPS
        delay = due - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            due = time.monotonic()
    return True


def read_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None


def paint_keyboard():
    """Re-apply the keyboard look at login; the board forgets it on power loss."""
    try:
        state = json.loads(KB_STATE.read_text())
    except (OSError, ValueError):
        return
    env = dict(os.environ, RGB_KB_WRITES="1")
    try:
        if state.get("kind") == "custom" and state.get("effect"):
            colours = ",".join(state.get("colours") or [])
            subprocess.Popen([sys.executable, str(HERE / "kb-anim.py"), state["effect"],
                              colours, str(int(state.get("brightness", 80)))],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, start_new_session=True, env=env)
            log(f"keyboard effect {state['effect']} started")
        elif state.get("kind") == "solid":
            subprocess.run([sys.executable, str(HERE / "kb-colour.py"),
                            str(state.get("colour", "#00ff41")).lstrip("#"),
                            "--brightness", str(int(state.get("brightness", 80)))],
                           capture_output=True, timeout=30, env=env)
            log(f"keyboard colour {state.get('colour')} restored")
    except (OSError, ValueError) as exc:
        log(f"keyboard restore failed: {exc}")


def main():
    signal.signal(signal.SIGTERM, lambda *_: globals().__setitem__("stopping", True))
    signal.signal(signal.SIGINT, lambda *_: globals().__setitem__("stopping", True))
    log(f"lighting service started (pid {os.getpid()})")
    try:
        paint_keyboard()
    except Exception as exc:  # noqa: BLE001
        log(f"keyboard restore failed: {exc}")
    stamp = None
    while not stopping:
        try:
            mtime = STATE.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != stamp:
            stamp = mtime
            try:
                state = read_state()
                if not state:
                    log("no state file yet")
                elif state.get("kind") == "custom":
                    if not paint_custom(state, stamp):
                        stamp = None
                        time.sleep(2)
                    continue
                elif state.get("kind") == "hardware":
                    if not paint_hardware(state):
                        stamp = None
                        time.sleep(2)
                elif state.get("kind") == "off":
                    sticks = chosen_sticks(state)
                    if sticks:
                        ram.set_effect(sticks, 0, "#000000", 0, 2)
                    log("off")
            except Exception as exc:  # noqa: BLE001
                # Never die in a restart loop: log it, wait, try again.
                log(f"apply failed: {exc}")
                stamp = None
                time.sleep(2)
        time.sleep(POLL)
    log("lighting service stopping")


if __name__ == "__main__":
    main()
