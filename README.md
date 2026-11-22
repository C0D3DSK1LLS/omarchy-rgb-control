# PeaceMachine RGB Control

Control of the board, GPU and mouse through the OpenRGB CLI, plus the K70
Optical keyboard's capture-backed native HID sender.

Addressable zones are resized to 30 LEDs before a frame. Keyboard brightness
uses OpenRGB; its colour picker and presets use `kb-colour.py`. Presets update
the keyboard last so later OpenRGB initialization cannot reset its mode.

Run with `c0d3d-rgb-control` or from the menu as **PeaceMachine RGB Control**.

Known gaps: saved profiles/apply-at-login and the Trident Z Royal RAM which
the board keeps off the Linux-visible SMBus.

## K70 optical protocol correction — 22 November 2026

`kb-colour.py` now replays the successful lighting setup in `kb2.pcapng`, using
fixtures in `k70-capture.json`. The sender is wired into the panel. C0D3D confirmed a green-ish colour after
the standalone command; the panel integration still needs his live check.

The handover misidentified three things:

- Usage 1's actual descriptor has unnumbered 1024-byte IN/OUT reports. `08` is
  the Corsair protocol identifier, not a HID report number. Linux hidraw needs
  `00` plus the 1024 captured bytes, exactly 1025 bytes passed to write().
  OpenRGB's leading zero was correct. See Linux kernel HIDRAW API, write():
  https://www.kernel.org/doc/html/latest/hid/hidraw.html
- Usage 2 is a 64-byte input-only interface. Do not send lighting there.
- Reply byte 2 is status: `00 06 03` is failure, while `00 06 00` is success.
  Captured START resources 24/36 failed; channel 0 resource 22 succeeded.

Frame 10914 is a 7-byte protocol header plus a 428-byte payload: LE16 type 12,
then 142 RGB slots at absolute byte 9. The first four slots are off, hence the
first coloured triplet appears at byte 21. There are also white indicator slots;
the helper preserves those and the unused black slots. Resources 22 and 2e stay
open between updates, as iCUE does; stopping every frame is incorrect.

Offline check (no hardware writes):

```bash
python3 ~/.local/share/c0d3d/rgb-control/kb-colour.py --self-test
```

Live test, sets green without launching a window:

```bash
python3 ~/.local/share/c0d3d/rgb-control/kb-colour.py 00FF41
```

Return to the keyboard's stored hardware profile:

```bash
python3 ~/.local/share/c0d3d/rgb-control/kb-colour.py --restore
```

No boot profile is saved. Do not run concurrent writers against the keyboard.
The development sandbox exposes sysfs but no /dev/hidraw devices, so the
standalone hardware test was run by C0D3D. Offline panel checks cover routing,
colour arguments, brightness ordering and failed-command reporting.
