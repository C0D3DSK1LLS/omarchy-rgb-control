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
import os

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
BUSES = (7, 8)
ADDRESSES = (0x39, 0x3A, 0x3B, 0x3C)


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


def find_sticks():
    """Every ENE DRAM controller on the memory buses, in bus/address order."""
    sticks = []
    for bus in BUSES:
        path = f"/dev/i2c-{bus}"
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:
            continue
        try:
            for address in ADDRESSES:
                try:
                    raw = bytes(_read(fd, address, REG_DEVICE_NAME + offset)
                                for offset in range(16))
                    name = raw.split(b"\x00")[0].decode("ascii", "replace").strip()
                    if not name or not all(32 <= ord(ch) < 127 for ch in name):
                        continue
                    if not (name.startswith("AUDA") or name.startswith("DIMM_LED")):
                        continue
                    leds = _read(fd, address, REG_LED_COUNT) or 8
                except OSError:
                    continue
                sticks.append(Stick(len(sticks) + 1, bus, address, name, min(leds, 16)))
        finally:
            os.close(fd)
    return sticks


def _scaled(hex_colour, brightness):
    value = (hex_colour or "00ff41").lstrip("#")
    if len(value) != 6:
        value = "00ff41"
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    level = max(0, min(100, int(brightness))) / 100.0
    return (int(red * level + 0.5), int(green * level + 0.5), int(blue * level + 0.5))


def set_colour(sticks, hex_colour, brightness=100):
    """Paint these sticks (and only these) one solid colour."""
    if not sticks:
        return 0
    red, green, blue = _scaled(hex_colour, brightness)
    painted = 0
    for stick in sticks:
        fd = os.open(f"/dev/i2c-{stick.bus}", os.O_RDWR)
        try:
            _write(fd, stick.address, REG_DIRECT, 0)      # effect mode
            _write(fd, stick.address, REG_MODE, MODE_STATIC)
            for led in range(stick.leds):
                base = REG_COLORS_EFFECT + 3 * led
                # The chip takes R, B, G — verified against a crimson write.
                _write(fd, stick.address, base, red)
                _write(fd, stick.address, base + 1, blue)
                _write(fd, stick.address, base + 2, green)
            _write(fd, stick.address, REG_APPLY, APPLY)
        finally:
            os.close(fd)
        painted += 1
    return painted


if __name__ == "__main__":
    found = find_sticks()
    for item in found:
        print(item, item.name, f"{item.leds} LEDs")
    if not found:
        print("no ENE DRAM controllers found (is i2c-imc-skylake loaded?)")
