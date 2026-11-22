#!/usr/bin/env python3
"""Animated effects for the board's ARGB headers.

The board only takes whole-frame colours over OpenRGB's server protocol, so
this daemon starts that server, holds the motherboard open in Direct mode and
pushes frames to JRAINBOW1/2. It idles (and leaves no server running) unless
the panel asks for an effect.

State: ~/.local/state/ralph/rgb-fan-state.json
    {"kind": "custom", "effect": "Fan Wave", "colours": [[...]], "brightness": 80}
    {"kind": "off"}
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

import fanfx  # noqa: E402
import orbg  # noqa: E402

STATE = Path(os.path.expanduser("~/.local/state/ralph/rgb-fan-state.json"))
LOG = Path(os.path.expanduser("~/.local/state/ralph/diagnostics/rgb-fans.log"))
OPENRGB = "/usr/local/bin/openrgb"
CONFIG = str(HERE / "openrgb-config")
FPS = 15.0
ZONES = (2, 3)                 # JRAINBOW1, JRAINBOW2
LEDS = 30

running = True


def log(message):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H:%M:%S")
    with LOG.open("a") as handle:
        handle.write(f"{stamp} {message}\n")
    if LOG.stat().st_size > 128 * 1024:
        LOG.write_text("\n".join(LOG.read_text().splitlines()[-300:]) + "\n")


def stop(*_args):
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


def board_layout():
    """Index, total LED count and the JRAINBOW1/2 slices, from OpenRGB's names."""
    result = subprocess.run([OPENRGB, "--config", CONFIG, "--noautoconnect", "--list-detailed"],
                            capture_output=True, text=True, timeout=25)
    index = None
    for line in result.stdout.splitlines():
        head, _, name = line.partition(": ")
        if head.strip().isdigit() and "MSI X299 PRO" in name:
            index = int(head)
            break
    if index is None:
        return None
    total = 0
    current = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        head, _, _rest = stripped.partition(": ")
        if head.isdigit():
            current = int(head)
        if current != index:
            continue
        if stripped.startswith("LEDs:"):
            names = [part.strip().strip("'") for part in stripped[5:].split("' '")]
            total = len(names)
            spans = {}
            start = 0
            for name in [n.strip("'") for n in names]:
                zone = name.split(",")[0].strip()
                spans.setdefault(zone, [start, 0])
                spans[zone][1] += 1
                start += 1
            return index, total, spans
    return index, total, {}


def ensure_server():
    if orbg.server_running():
        return False
    subprocess.Popen([OPENRGB, "--config", CONFIG, "--server"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        if orbg.server_running():
            return True
        time.sleep(0.1)
    return False


def stop_server():
    subprocess.run(["pkill", "-x", "openrgb"], capture_output=True)
    time.sleep(0.3)


def read_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None


def paint(state, stamp):
    name = state.get("effect")
    spec = fanfx.BY_NAME.get(name)
    if not spec:
        log(f"unknown effect {name!r}")
        return
    effect, defaults, _labels = spec
    palette = [tuple(colour) for colour in (state.get("colours") or defaults)]
    level = max(0, min(100, int(state.get("brightness", 80)))) / 100.0

    started_server = ensure_server()
    if not orbg.server_running():
        log("OpenRGB server did not start")
        return

    layout = board_layout()
    if not layout:
        log("motherboard not found")
        return
    index, total, spans = layout
    rainbow = []
    for zone_name in ("JRAINBOW1", "JRAINBOW2"):
        if zone_name in spans:
            rainbow.append(spans[zone_name])
    if not rainbow:
        log("JRAINBOW zones not found in the device layout")
        return

    client = orbg.Client()
    try:
        client.set_client_name("PeaceMachine Fan Effects")
        client.custom_mode(index)
        client.drain(0.15)
        # The controller only drives as many LEDs as its zone objects hold, so
        # each ARGB zone is widened to the strip length before frames flow.
        zone_names = [name for name in ("JRAINBOW1", "JRAINBOW2") if name in spans]
        for zone_index, _name in enumerate(zone_names):
            client.resize_zone(index, 2 + zone_index, LEDS)
        client.drain(0.2)
        log(f"effect {name} on {len(rainbow)} ARGB zone(s), {total} LEDs at {int(level * 100)}%")

        start = time.monotonic()
        due = start
        while running:
            try:
                if STATE.stat().st_mtime != stamp:
                    break
            except OSError:
                break
            moment = time.monotonic() - start
            pixels = [(int(r * level), int(g * level), int(b * level))
                      for r, g, b in effect(moment, LEDS, palette)]
            frame = [(0, 0, 0)] * total
            for begin, size in rainbow:
                for offset in range(min(size, len(pixels))):
                    frame[begin + offset] = pixels[offset]
            client.update_leds(index, frame)
            due += 1 / FPS
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                due = time.monotonic()
    except (OSError, ConnectionError) as exc:
        log(f"stream failed: {exc}")
    finally:
        client.close()
        if started_server:
            stop_server()


def main():
    log(f"fan effects service started (pid {os.getpid()})")
    stamp = None
    while running:
        try:
            mtime = STATE.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != stamp:
            stamp = mtime
            state = read_state()
            if state and state.get("kind") == "custom":
                paint(state, stamp)
                continue
            elif state and state.get("kind") == "off":
                stop_server()
                log("fan effects off")
        time.sleep(0.4)
    stop_server()
    log("fan effects service stopping")


if __name__ == "__main__":
    main()
