#!/usr/bin/env python3
"""Native ENE DRAM lighting for the G.Skill Trident Z Royal modules.

Why this exists: the OpenRGB CLI re-scans every controller on each run and
re-applies the colours it has saved, so changing one stick repainted the whole
kit. These chips are plain SMBus devices caped at two registers, so the panel
talks to them directly and touches only the stick that was asked for.

Protocol (from OpenRGB's ENE SMBus driver, verified on this box):
  * select a 16-bit register: SMBus word write, command 0x00, byte-swapped
  * read it back:             SMBus byte read,   command 0x81
  * write it:                 SMBus byte write,  command 0x01
  * colours for effect mode:  0x8160 + 3 * LED, bytes R, B, G
  * mode register 0x8021:     1 = static
  * apply register 0x80A0:    write 1 to latch
"""
import ctypes
import fcntl
import json
import os
import time

I2C_SLAVE = 0x0703
I2C_SMBUS = 0x0720
SMBUS_READ = 1
SMBUS_WRITE = 0
BYTE_DATA = 2
WORD_DATA = 3

REG_DEVICE_NAME = 0x1000
REG_LED_COUNT = 0x1C03
REG_COLORS_EFFECT = 0x8160
REG_DIRECT = 0x8020
REG_MODE = 0x8021
REG_APPLY = 0x80A0

MODE_STATIC = 1
APPLY = 1
REG_SPEED = 0x8022
BUSES = (6, 7, 8)
ADDRESSES = tuple(range(0x30, 0x78))

# G.Skill's own effect names, in their own order, mapped one-to-one onto the
# ENE mode register (the order matches exactly: mode 1 .. 14).
MODES = [
    ("Off", 0),
    ("Static", 1),
    ("Breathing", 2),
    ("Strobing", 3),
    ("Cycle", 4),
    ("Rainbow", 5),
    ("Breathing Rainbow", 6),
    ("Comet", 7),
    ("Comet Rainbow", 8),
    ("Flash", 9),
    ("Flash Rainbow", 10),
    ("Wave", 11),
    ("Glowing Yoyo", 12),
    ("Starry Night", 13),
    ("Default", 14),
]
MODE_NAMES = [name for name, _ in MODES]

# ENE speed register: 0 is fastest, 4 slowest.
SPEEDS = [("Fastest", 0), ("Fast", 1), ("Normal", 2), ("Slow", 3), ("Slowest", 4)]
SPEED_NAMES = [name for name, _ in SPEEDS]


class _Data(ctypes.Union):
    _fields_ = [("byte", ctypes.c_uint8),
                ("word", ctypes.c_uint16),
                ("block", ctypes.c_uint8 * 34)]


class _Io(ctypes.Structure):
    _fields_ = [("rw", ctypes.c_uint8),
                ("cmd", ctypes.c_uint8),
                ("size", ctypes.c_uint32),
                ("data", ctypes.POINTER(_Data))]


def _xfer(fd, address, read_write, command, size, data=None):
    if data is None:
        data = _Data()
    fcntl.ioctl(fd, I2C_SLAVE, address)
    fcntl.ioctl(fd, I2C_SMBUS, _Io(read_write, command, size, ctypes.pointer(data)))
    return data


def _select(fd, address, register):
    # ENE expects the register byte-swapped in a word write to command 0.
    value = ((register << 8) & 0xFF00) | ((register >> 8) & 0xFF)
    _xfer(fd, address, SMBUS_WRITE, 0x00, WORD_DATA, _Data(word=value))


def _read(fd, address, register):
    _select(fd, address, register)
    return _xfer(fd, address, SMBUS_READ, 0x81, BYTE_DATA).byte


def _write(fd, address, register, value):
    _select(fd, address, register)
    _xfer(fd, address, SMBUS_WRITE, 0x01, BYTE_DATA, _Data(byte=value))


class Stick:
    """One DIMM's lighting controller."""

    def __init__(self, number, bus, address, name, leds):
        self.number = number
        self.bus = bus
        self.address = address
        self.name = name
        self.leds = leds

    @property
    def label(self):
        return f"Stick {self.number}"

    @property
    def where(self):
        return f"i2c-{self.bus} 0x{self.address:02X}"

    def __str__(self):
        return f"{self.label} ({self.where})"


_KNOWN = {}
_CACHE_FILE = os.path.expanduser("~/.local/state/ralph/rgb-sticks.json")


def _load_cache():
    try:
        data = json.load(open(_CACHE_FILE))
    except (OSError, ValueError):
        return {}
    known = {}
    for entry in data:
        try:
            bus, address, name, leds = entry
            known[(int(bus), int(address))] = (str(name), int(leds))
        except (TypeError, ValueError):
            continue
    return known


def _save_cache(known):
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        payload = [[bus, address, name, leds] for (bus, address), (name, leds) in sorted(known.items())]
        temp = _CACHE_FILE + ".tmp"
        with open(temp, "w") as handle:
            json.dump(payload, handle)
        os.replace(temp, _CACHE_FILE)
    except OSError:
        pass


def _probe(fd, address, deadline=1.0):
    """Read a stick's identity, retrying while the iMC engine is sulking."""
    limit = time.monotonic() + deadline
    while True:
        try:
            raw = bytes(_read(fd, address, REG_DEVICE_NAME + offset) for offset in range(16))
            name = raw.split(b"\x00")[0].decode("ascii", "replace").strip()
            if name and all(32 <= ord(ch) < 127 for ch in name):
                leds = 8
                for _ in range(3):
                    try:
                        leds = _read(fd, address, REG_LED_COUNT) or 8
                        break
                    except OSError:
                        time.sleep(0.005)
                return name, min(leds, 16)
        except OSError:
            pass
        if time.monotonic() >= limit:
            return None
        time.sleep(0.01)


def find_sticks():
    """Every ENE DRAM controller on the memory buses, in bus/address order.

    The iMC engine occasionally NAKs a probe, so a module that has answered
    before is remembered on disk and kept - a scan must never silently drop a
    stick and leave it dark.
    """
    cache = _load_cache()
    sticks = []
    found = {}
    for bus in BUSES:
        path = f"/dev/i2c-{bus}"
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:
            continue
        try:
            for address in ADDRESSES:
                hit = _probe(fd, address)
                key = (bus, address)
                if hit:
                    found[key] = hit
                elif key in cache:
                    found[key] = cache[key]
                elif key in _KNOWN:
                    found[key] = _KNOWN[key]
                else:
                    continue
                time.sleep(0.003)
        finally:
            os.close(fd)
    for (bus, address), (name, leds) in sorted(found.items()):
        if not (name.startswith("AUDA") or name.startswith("DIMM_LED")):
            continue
        sticks.append(Stick(len(sticks) + 1, bus, address, name, leds))
    fresh = {key: value for key, value in found.items() if key not in cache}
    if fresh:
        cache.update(found)
        _save_cache(cache)
    _KNOWN.update(found)
    return sticks


def _scaled(hex_colour, brightness):
    value = (hex_colour or "00ff41").lstrip("#")
    if len(value) != 6:
        value = "00ff41"
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    level = max(0, min(100, int(brightness))) / 100.0
    return (int(red * level + 0.5), int(green * level + 0.5), int(blue * level + 0.5))


def prepare_direct(sticks):
    """Put the sticks into direct per-LED mode once, ready for frames."""
    for stick in sticks:
        try:
            fd = os.open(f"/dev/i2c-{stick.bus}", os.O_RDWR)
        except OSError:
            continue
        try:
            _write(fd, stick.address, REG_DIRECT, 0)
            _write(fd, stick.address, REG_MODE, MODE_STATIC)
        except OSError:
            continue
        finally:
            os.close(fd)


def write_frame(sticks, frames, brightness=100, previous=None):
    """Push one animation frame.

    frames[i] is a list of (r, g, b) for sticks[i]. When `previous` holds the
    last frame, only LEDs whose colour actually changed are written - that is
    what keeps slow effects at a smooth rate on a shared SMBus.
    """
    level = max(0, min(100, int(brightness))) / 100.0
    scaled = [[(int(red * level), int(green * level), int(blue * level))
               for red, green, blue in column] for column in frames]
    for index, (stick, colours) in enumerate(zip(sticks, scaled)):
        old = previous[index] if previous and index < len(previous) else None
        changes = [(led, colour) for led, colour in enumerate(colours[:stick.leds])
                   if old is None or led >= len(old) or old[led] != colour]
        if not changes:
            continue
        try:
            fd = os.open(f"/dev/i2c-{stick.bus}", os.O_RDWR)
        except OSError:
            continue
        try:
            for led, (red, green, blue) in changes:
                base = REG_COLORS_EFFECT + 3 * led
                _write(fd, stick.address, base, red)
                _write(fd, stick.address, base + 1, blue)
                _write(fd, stick.address, base + 2, green)
            _write(fd, stick.address, REG_APPLY, APPLY)
        except OSError:
            continue
        finally:
            os.close(fd)
    return scaled


def set_effect(sticks, mode, hex_colour, brightness=100, speed=2):
    """Apply one effect (and only to these sticks)."""
    if not sticks:
        return 0
    red, green, blue = _scaled(hex_colour, brightness)
    painted = 0
    for stick in sticks:
        try:
            fd = os.open(f"/dev/i2c-{stick.bus}", os.O_RDWR)
        except OSError:
            continue
        try:
            try:
                _write(fd, stick.address, REG_DIRECT, 0)      # effect mode
            except OSError:
                continue
            if mode == 1:
                # Static keeps a colour per LED.
                slots = stick.leds
            elif mode == 0:
                slots = 0
            else:
                # Animated effects read up to ten colour slots.
                slots = 10
            for slot in range(slots):
                base = REG_COLORS_EFFECT + 3 * slot
                # The chip takes R, B, G — verified against a crimson write.
                _write(fd, stick.address, base, red)
                _write(fd, stick.address, base + 1, blue)
                _write(fd, stick.address, base + 2, green)
            _write(fd, stick.address, REG_MODE, mode)
            _write(fd, stick.address, REG_SPEED, max(0, min(4, speed)))
            _write(fd, stick.address, REG_APPLY, APPLY)
        except OSError:
            continue
        finally:
            os.close(fd)
        painted += 1
    return painted


def set_colour(sticks, hex_colour, brightness=100):
    """Solid colour on these sticks."""
    return set_effect(sticks, MODE_STATIC, hex_colour, brightness, 2)


if __name__ == "__main__":
    found = find_sticks()
    for item in found:
        print(item, item.name, f"{item.leds} LEDs")
    if not found:
        print("no ENE DRAM controllers found (is i2c-imc-skylake loaded?)")
