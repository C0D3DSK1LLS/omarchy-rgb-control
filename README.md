# PeaceMachine RGB Control

Board/GPU/mouse use OpenRGB. The K70 RGB PRO Optical-Mechanical (1b1c:1bc6)
uses a native lighting-only sender, `kb-colour.py`. Its colour picker and the
Matrix/Crimson/Ice/Amber/White/Off buttons use the same path.

## K70 correction and incident

The first capture replay was wrong: it included key assignments (resource02,
129-byte payload) and performance settings (register4a). C0D3D reported repeated
letters; reconnecting restored normal input. Those writes are now forbidden by
`validate_packet()` at the actual USB transport boundary, as are indicator,
macro and flash writes. No input mappings or keyboard performance flags are set.

Only these operations are allowed: read mode; set hardware/software mode;
open/close handle0 for lighting resource22; RGB type12; keepalive12.
The successful capture supplies only the RGB frame, never a startup script.
Repeated-open status3 is handled with close/reopen, matching ckb-next.

Wire report is 1024 bytes; Linux hidraw write receives an extra leading zero.
Payload is 428 bytes: type12 (two bytes) + 142 RGB triplets. Unused black slots
and white indicator slots are preserved. OpenRGB's 111 named LEDs are unrelated
to the protocol's 142 slots. Brightness scales key RGB values.

Sources checked against the capture:
- https://github.com/jurkovic-nikola/OpenLinkHub/blob/main/src/devices/k70pro/k70pro.go
- https://github.com/ckb-next/ckb-next/blob/master/src/daemon/device_bragi.c
- https://github.com/ckb-next/ckb-next/blob/master/src/daemon/bragi_common.c
- https://www.kernel.org/doc/html/latest/hid/hidraw.html

## Panel behaviour

Hardware jobs run on one background worker; GTK receives progress and results
through GLib. Repeated clicks cannot start competing writes. All normal-device
zones are batched into one OpenRGB command; the device's supported Static or
Direct mode is chosen. Errors do not get overwritten by a success message.

The isolated `openrgb-config` preserves existing settings and disables only the
K70 detector. `--noautoconnect` prevents using another server's detector settings.
OpenRGB therefore cannot reset the keyboard during panel scans/updates.

While the panel is open and controls the keyboard, it pings every 20 seconds.
Closing waits for the current write and restores hardware mode. A failed colour
write also attempts hardware restoration. No separate daemon is installed.
Keep the panel open to retain software lighting; no permanent boot profile is
saved. Other independently-running RGB software must not control the same device.

## Checks and current verification limit

```bash
python3 test_rgb_control.py
```

```bash
python3 test_k70_protocol.py
```

```bash
python3 kb-colour.py --self-test
```

Checks use simulated hardware, never real USB writes. They cover main-loop
responsiveness during slow operations, batching, mode selection, failures,
colour changes, repeated handle opens, input-write blocking and restoration.
The sandbox exposes sysfs but no USB device nodes and prohibits X11/D-Bus socket
binding. Physical operation of this corrected lighting-only version still needs
C0D3D's check; earlier full-replay colour success did not prove input safety.

Recovery if ever needed:

```bash
python3 ~/.local/share/c0d3d/rgb-control/kb-colour.py --restore
```

Reconnecting the keyboard also returns it to its hardware profile.
