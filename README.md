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
