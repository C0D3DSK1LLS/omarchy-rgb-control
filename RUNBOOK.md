# RGB troubleshooting runbook

Read this before touching anything. Every symptom below has been seen on this
box, and the fix is the one that worked.

## 1. RAM missing from the panel, sticks stuck on rainbow
Order:
```
lsmod | grep i2c_imc                 # module loaded?
ls -l /dev/i2c-6 /dev/i2c-7          # buses present?
systemctl --user status rgb-lighting
tail -20 ~/.local/state/ralph/diagnostics/rgb-lighting.log
sudo i2cdetect -y 6
sudo i2cdetect -y 7
```
- No module: `sudo modprobe i2c-imc-skylake` (conf in `/etc/modules-load.d`,
  option `allow_unsafe_access=1` in `/etc/modprobe.d`, DKMS package
  `/usr/src/i2c-imc-skylake-1.0`).
- Only **0x77** answering: the firmware parked the modules and no slots are
  published. `ram.py` remaps automatically (0x80F8 slot, 0x80F9 address<<1 on
  0x77). Run `python3 -c "import ram; print(len(ram.find_sticks()))"` in
  `~/.local/share/c0d3d/rgb-control` and expect 8.
- Found at 0x70-0x73 or 0x39-0x3C: normal (cold vs warm address families).

## 2. RAM scan hangs / panel "scanning devices" forever
`find_sticks` must never probe both address families on every bus with long
timeouts. One quick probe picks the family, then only known sticks get the
patient retry. Three passes are merged; a NAK falls back to the cache.
A healthy scan is ~0.5 s for 8 sticks.

## 3. A stick or two dark
Read them individually:
```
python3 - <<'PY'
import sys, os; sys.path.insert(0, os.path.expanduser("~/.local/share/c0d3d/rgb-control"))
import ram
print([str(s) for s in ram.find_sticks()])
PY
```
Writes to a missing stick are skipped, never fatal. Cache entries live in
`~/.local/state/ralph/rgb-sticks.json` and are dropped after 60 consecutive misses.

## 4. Effect stops when the panel closes
The panel must not own the sticks. `rgb-lighting.service` does; the panel only
writes `~/.local/state/ralph/rgb-ram-state.json`.
```
systemctl --user is-enabled rgb-lighting.service   # must be enabled
systemctl --user restart rgb-lighting.service
```
Effects are custom/hardware/off; the service logs and backs off instead of
crash-looping. If it restarts every 2 s, read the log — a traceback there names
the line.

## 5. Keyboard dark, red, or resetting to its profile
- Closing the panel intentionally leaves software mode on, so the colour stays;
  the service re-applies `rgb-keyboard-state.json` at login.
- **Bootloader**: `cat /sys/bus/usb/devices/1-1/product` contains "Bootloader"
  and the usage-1 HID interface disappears. No software can clear it — unplug
  the keyboard's USB, wait five seconds, replug. Do not keep sending frames.
- Never spawn one process per frame. `kb-anim.py` holds ONE `kb-colour.py
  --stream` session; that churn is what triggered both bootloader falls.
- Every write needs `RGB_KB_WRITES=1` in the environment; the panel and the
  daemon set it. Do not remove that guard.

## 6. Per-key paints the wrong key
Slots are HID usage order: **A=4, B=5, C=6 …**, so a key's slot is its usage
code. Names are stored in `~/.config/c0d3d/rgb-key-labels.json`. The OpenRGB
listing order is different and must not be used.

## 7. Fan/board colour does nothing on the first try
The MSI 185-byte controller drops the first colour packet after the HID device
is opened. Every board write is sent twice with a ~350 ms gap (the app does
this). If a manual test fails, send the exact command twice before concluding
anything.

## 8. A board effect does nothing
Its own firmware ignores some modes. "Fire" is accepted and does nothing, so it
is filtered out. **Direct mode does not work on this firmware** — verified with
a full colour list — therefore per-LED/software animation of the fans is
impossible; the MSI hardware effect list is the ceiling.

## 9. Device scan is slow
`openrgb-config/OpenRGB.json` must keep all detectors disabled except
`MSI Mystic Light MS_7B94`, `MSI GeForce RTX 4070 Ti SUPER Gaming Slim` and
`Corsair Nightsword`. The K70 detector stays OFF so OpenRGB never writes to the
keyboard. Healthy scan: ~2 s for five devices.

## 10. Files that matter
- App: `~/.local/share/c0d3d/rgb-control` (git repo; RUNBOOK.md here)
- RAM state: `~/.local/state/ralph/rgb-ram-state.json`
- Keyboard state: `~/.local/state/ralph/rgb-keyboard-state.json`
- Stick cache: `~/.local/state/ralph/rgb-sticks.json`
- Panel layout: `~/.local/state/ralph/rgb-panel-layout.json`
- Presets: `~/.config/c0d3d/rgb-colour-presets.json`
- Key names: `~/.config/c0d3d/rgb-key-labels.json`
- Logs: `~/.local/state/ralph/diagnostics/rgb-lighting.log`
- Unit: `~/.config/systemd/user/rgb-lighting.service`
- Module: `/etc/modules-load.d/i2c-imc-skylake.conf`,
  `/etc/modprobe.d/i2c-imc-skylake.conf`, DKMS `i2c-imc-skylake/1.0`
- Backup: `/mnt/archives/backups/rgb-*.tar.gz`

## 11. Golden rules learned the hard way
- Measure addresses and names; never assume a bus or an index.
- One process owns the hardware; everything else writes state.
- A NAK is transient until proven otherwise; retry, cache, never crash.
- Board writes go twice; keyboard writes go through one stream.
- If a "fix" needs the user to check forty buttons, it is not finished.
