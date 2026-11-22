# PeaceMachine RGB Control

Live control of every LED OpenRGB can reach, over the SDK rather than the CLI.
The CLI re-opens each device on every run and wipes the other channels; talking
to `openrgb --server` keeps everything open so one update lands atomically.

* `openrgb --server` runs as the user unit `rgb-server.service` (127.0.0.1:6742).
* Board, GPU, mouse are written through the SDK (`orbg.py`).
* Addressable zones are resized to 30 LEDs before a frame (that is what the fan
  hub answers to — more than that and the header refuses the frame).
* The keyboard is written with the CLI's hardware `Static` mode; its software
  mode leaves it dark once the app closes.

Run with `c0d3d-rgb-control` or from the menu as **PeaceMachine RGB Control**.

Known gaps: keyboard writes are not landing yet (it shows its own hardware
profile), saved profiles and apply-at-login, and the Trident Z Royal RAM which
the board keeps off the Linux-visible SMBus.

## K70 optical protocol correction — 22 November 2026

`kb-colour.py` now replays the successful lighting setup in `kb2.pcapng`, using
fixtures in `k70-capture.json`. It is a standalone hardware-test sender, not yet
wired into the panel: physical LED behaviour must be confirmed first.

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
The development sandbox exposes sysfs but no /dev/hidraw devices, so command
acceptance and actual LEDs remain unverified on Linux until the host test runs.
