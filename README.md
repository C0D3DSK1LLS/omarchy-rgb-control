# Omarchy RGB Control

One GTK4 panel for every light in the box on **Omarchy / Arch Linux**:
motherboard and ARGB fans, GPU and mouse through OpenRGB, G.Skill Trident Z
Royal RAM and a Corsair K70 RGB PRO Optical keyboard driven natively.

Built on C0D3D's machine and published as-is for other Omarchy users who want
the same thing. It is not a universal RGB app; hardware support is exactly what
OpenRGB (or the native paths below) can reach.

## What it does

- **RAM** — G.Skill Trident Z Royal (ENE controllers) over SMBus: solid colours,
  the 15 effects from G.Skill's own software with five speeds, and 32 extra
  effects with their own colour palettes.
- **Keyboard** — Corsair K70 RGB PRO Optical (1b1c:1bc6): per-key painting,
  key naming, eight keyboard effects, native HID (no iCUE, no Wine).
- **Board / fans** — the full MSI Mystic Light effect list plus colour.
- **GPU / mouse** — whatever OpenRGB exposes.
- **Persistence** — a small user service owns the lighting, so effects keep
  running with the panel closed and return at login.

## Requirements

- Omarchy or Arch with GTK4 / PyGObject: `sudo pacman -S python-gobject gtk4 i2c-tools`
- OpenRGB: `sudo pacman -S openrgb` (or a local build, see below)
- Optional, RAM only: the `i2c-imc-skylake` driver over DKMS, with
  `allow_unsafe_access=1`. The RAM paths need it; everything else works without.
- Optional, keyboard only: nothing — it speaks HID directly.

## Hardware notes

- **MSI X299 PRO (MS-7B94)** needs an OpenRGB build that knows the board's
  185-byte protocol. Upstream OpenRGB may already include it; if your board is
  missing, add its ID to the MSI 185 controller table and build with
  `ENABLE_UNTESTED_MYSTIC_LIGHT`.
- **Corsair K70 RGB PRO Optical (1b1c:1bc6)** is driven by this project, not by
  OpenRGB. The sender is capture-backed and lighting-only.
- **G.Skill RAM** talks ENE SMBus; after a cold boot the modules may all park on
  address 0x77, so the code remaps their slots before scanning.
- Other Corsair keyboards/RAM are not supported by the native paths — use
  OpenRGB for those.

## Run

```bash
git clone https://github.com/C0D3DSK1LLS/omarchy-rgb-control
cd omarchy-rgb-control
./c0d3d-rgb-control     # or: python3 app.py
```

Desktop entry and launcher used on the original machine:

- `~/.local/bin/c0d3d-rgb-control`
- `~/.local/share/applications/org.jimmy.RgbControl.desktop`

## Safety

- Keyboard writes are restricted to lighting commands by a transport-level
  whitelist; key assignments, macros and firmware writes are refused.
- All writes require `RGB_KB_WRITES=1`, set by the panel/service.
- The RAM driver touches the memory controller's SMBus. Read `RUNBOOK.md`
  before enabling it, and unload it when not in use if you prefer.

## Files and state

- RAM state: `~/.local/state/ralph/rgb-ram-state.json`
- Keyboard state: `~/.local/state/ralph/rgb-keyboard-state.json`
- Presets: `~/.config/c0d3d/rgb-colour-presets.json`
- Key names: `~/.config/c0d3d/rgb-key-labels.json`
- Logs: `~/.local/state/ralph/diagnostics/`
- Runbook: [RUNBOOK.md](RUNBOOK.md)

## Licence

MIT — © 2026 William James Sova (C0D3D), PeaceMachineStudios.
