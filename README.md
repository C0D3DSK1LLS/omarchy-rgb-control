# PeaceMachine RGB Control

Every LED in the box from one window. Front-end over the locally built OpenRGB
binary at `/usr/local/bin/openrgb`, which carries two machine-specific patches:

* **MSI X299 PRO (MS-7B94)** added to the MSI 185-byte motherboard table, so the
  addressable headers (JRAINBOW1/2) expose LEDs and take colours.
* **Corsair K70 RGB PRO Optical-Mechanical (1B1C:1BC6)** mapped onto the V2
  hardware controller, so the keyboard and its per-key LEDs appear.

Run with `c0d3d-rgb-control`. Devices are listed on the left; each device's
channels have colour, mode, brightness and their own Apply. The row of presets
at the bottom sets every device at once.

Not yet: per-key painting on the keyboard (needs the OpenRGB SDK rather than the
CLI), profiles, and the Trident Z Royal RAM — that one is blocked by the board
switching the DIMM SMBus away from Linux, see the notes in AGENTS.md.
