#!/usr/bin/env python3
"""PeaceMachine RGB Control — every LED in the box from one window.

OpenRGB handles the board, GPU and mouse. The K70 Optical has its own native
HID sender; OpenRGB detection for that model is disabled in this app's config.
All hardware work runs on one worker, never GTK's main thread.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import orbg  # noqa: E402
import ram  # noqa: E402
import effects  # noqa: E402

APP_ID = "org.jimmy.RgbControl"
OPENRGB = "/usr/local/bin/openrgb"
OPENRGB_CONFIG = os.path.join(HERE, "openrgb-config")
K70_NAME = "Corsair K70 RGB PRO Optical-Mechanical"
STATE = os.path.join(HERE, "state.json")
RAM_STATE = os.path.expanduser("~/.local/state/ralph/rgb-ram-state.json")

# per-zone LED counts for the MSI board. The CLI's total is unreliable because
# it re-reads its own saved zone sizes, so each zone is written by its own count.
ZONE_LEDS = {
    "jrgb1": 1, "jrgb2": 1, "jrainbow1": 30, "jrainbow2": 30,
    "jcorsair": 1, "pipe1": 1, "pipe2": 1, "onboard": 6,
}
ADDRESSABLE = {"jrainbow1", "jrainbow2", "jcorsair"}
ADDRESSABLE_LEN = 30          # what the fan hub actually answers to


def rgb_to_hex(rgba):
    return "#%02x%02x%02x" % (int(rgba.red * 255 + 0.5), int(rgba.green * 255 + 0.5),
                              int(rgba.blue * 255 + 0.5))


def hex_to_rgba(value):
    value = (value or "#00ff41").lstrip("#")
    if len(value) != 6:
        value = "00ff41"
    rgba = Gdk.RGBA()
    rgba.parse("#" + value)
    return rgba


def hex_to_tuple(value):
    value = (value or "#00ff41").lstrip("#")
    if len(value) != 6:
        value = "00ff41"
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgba_to_tuple(rgba):
    return (int(rgba.red * 255 + 0.5), int(rgba.green * 255 + 0.5),
            int(rgba.blue * 255 + 0.5))


class Device:
    def __init__(self, index, name):
        self.index = index
        self.name = name
        self.type = ""
        self.zones = []
        self.led_count = 0
        self.modes = []
        self.keyboard = False
        # Native ENE DRAM sticks when this entry is the RAM group.
        self.ram_sticks = []
        self.ram_mode = None
        self.ram_speed = None


def parse_devices():
    try:
        result = subprocess.run([OPENRGB, "--config", OPENRGB_CONFIG, "--noautoconnect", "--list-detailed"],
                                capture_output=True, text=True, timeout=25)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip() or "Device scan failed")
        out = result.stdout
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Device scan timed out") from exc
    devices, cur = [], None
    for raw in out.splitlines():
        m = re.match(r"^(\d+): (.*)$", raw)
        if m:
            cur = Device(int(m.group(1)), m.group(2).strip())
            devices.append(cur)
            continue
        if cur is None:
            continue
        line = raw.strip()
        if line.startswith("Type:"):
            cur.type = line[5:].strip()
            cur.keyboard = cur.type.lower() == "keyboard"
        elif line.startswith("Zones:"):
            cur.zones = [z.strip("'") for z in re.findall(r"'[^']*'|\S+", line[6:])]
        elif line.startswith("Modes:"):
            cur.modes = [m.strip("'[]") for m in re.findall(r"'[^']*'|\[[^\]]*\]|\S+", line[6:])]
        elif line.startswith("LEDs:"):
            cur.led_count = len(re.findall(r"'[^']*'|\S+", line[5:]))
    # Native keyboard discovery does not open/reset the keyboard.
    for node in Path("/sys/class/hidraw").glob("hidraw*"):
        try:
            identity = (node / "device/uevent").read_text()
            descriptor = (node / "device/report_descriptor").read_bytes()
        except OSError:
            continue
        if ("HID_ID=0003:00001B1C:00001BC6" in identity
                and descriptor.startswith(bytes.fromhex("06 42 ff 09 01 a1 01"))):
            keyboard = Device(-1, K70_NAME)
            keyboard.type, keyboard.keyboard = "Keyboard", True
            keyboard.zones, keyboard.led_count = ["Keyboard"], 111
            devices.append(keyboard)
            break
    # The RAM is driven natively (see ram.py). OpenRGB's CLI re-applies every
    # DRAM controller on each run, which is what repainted the whole kit, so
    # its DRAM entries are dropped and one native "RAM" entry takes their place.
    devices = [dev for dev in devices if dev.type.upper() != "DRAM" or dev.keyboard]
    sticks = ram.find_sticks()
    # The iMC bus occasionally NAKs a controller mid-scan; one more pass
    # usually brings the full kit back rather than losing a stick until Rescan.
    for _ in range(2):
        if len(sticks) >= 8:
            break
        time.sleep(0.2)
        more = ram.find_sticks()
        if len(more) > len(sticks):
            sticks = more
    if sticks:
        group = Device(None, "RAM")
        group.type = "DRAM"
        group.zones = ["DRAM"]
        group.led_count = sum(stick.leds for stick in sticks)
        group.ram_sticks = sticks
        devices.insert(0, group)
    return devices


def cli(args):
    try:
        r = subprocess.run([OPENRGB, "--config", OPENRGB_CONFIG, "--noautoconnect"] + args, capture_output=True, text=True, timeout=25)
        message = (r.stdout + r.stderr).strip()
        return r.returncode == 0 and not re.search(r"(?im)^\s*Error:", message), message
    except Exception as exc:
        return False, str(exc)


def is_k70_optical(dev):
    return dev.keyboard and "k70 rgb pro optical" in dev.name.lower()


def keyboard_request(args):
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "kb-colour.py")] + args,
            capture_output=True, text=True, timeout=8)
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except Exception as exc:
        return False, str(exc)


def keyboard_colour(colour, brightness=100):
    return keyboard_request([colour.lstrip("#"), "--brightness", str(brightness)])


def solid_mode(dev):
    mode = next((value for value in dev.modes if value.lower() == "static"), None)
    if mode is None:
        mode = next((value for value in dev.modes if value.lower() == "direct"), None)
    if mode is None:
        if dev.modes:
            raise ValueError(f"{dev.name}: no supported solid-colour mode")
        mode = "Static"
    return mode


def device_args(dev, colour, brightness):
    known = [z.lower().replace(" ", "") for z in dev.zones]
    mode = solid_mode(dev)
    args = []
    if not dev.keyboard and known and all(key in ZONE_LEDS for key in known):
        for index, key in enumerate(known):
            args += ["-d", dev.name, "-z", str(index)]
            if key in ADDRESSABLE:
                args += ["-sz", str(ADDRESSABLE_LEN)]
            args += ["-m", mode, "-c", colour.lstrip("#"), "-b", str(brightness)]
    else:
        args = ["-d", dev.name, "-m", mode, "-c", colour.lstrip("#"), "-b", str(brightness)]
    return args


def write_devices(devices, colour, brightness, progress, cancelled, keyboard_writer=None):
    keyboard_writer = keyboard_writer or keyboard_colour
    errors = []
    rams = [dev for dev in devices if dev.ram_sticks]
    normal = [dev for dev in devices
              if not is_k70_optical(dev) and not dev.ram_sticks]
    if normal and not cancelled.is_set():
        progress("Applying " + ", ".join(dev.name for dev in normal) + "…")
        args = []
        for dev in normal:
            args.extend(device_args(dev, colour, brightness))
        ok, message = cli(args)
        if not ok:
            errors.append(message or "OpenRGB update failed")
    for dev in rams:
        if cancelled.is_set():
            break
        progress(f"Applying {dev.name}…")
        try:
            mode = dev.ram_mode if dev.ram_mode is not None else ram.MODE_STATIC
            speed = dev.ram_speed if dev.ram_speed is not None else 2
            ram.set_effect(dev.ram_sticks, mode, colour, brightness, speed)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{dev.name}: {exc}")
    for dev in devices:
        if is_k70_optical(dev) and not cancelled.is_set():
            progress("Applying keyboard colour…")
            ok, message = keyboard_writer(colour, brightness)
            if not ok:
                errors.append(message or "Keyboard update failed")
    if cancelled.is_set():
        return False, "Cancelled"
    if errors:
        return False, " · ".join(error.splitlines()[-1] for error in errors)
    return True, f"Applied {colour} at {brightness}%"


class Panel(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="PeaceMachine RGB Control")
        self.set_default_size(940, 620)
        self.devices = []
        self.selected = None
        self.client = None
        self.busy = False
        self.closed = False
        self.cancelled = threading.Event()
        self.hardware_lock = threading.Lock()
        self.keyboard_touched = False
        self.keyboard_alive = False
        self.keepalive_source = None
        self.actions = []
        self.connect("close-request", self.on_close)
        self.colour_hex = "#00ff41"
        self.brightness = 80
        self.anim_thread = None
        self.anim_stop = threading.Event()
        self.animating = False
        self.saved_state = {}
        self.state_restored = False

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        title = Gtk.Label(label="PEACEMACHINE RGB")
        title.add_css_class("app-title")
        header.set_title_widget(title)
        rescan = Gtk.Button(label="Rescan")
        rescan.connect("clicked", lambda *_: self.scan())
        header.pack_start(rescan)
        self.actions.append(rescan)
        about = Gtk.Button(label="About")
        about.connect("clicked", lambda *_: self.show_about())
        header.pack_end(about)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(14)
        root.set_margin_end(14)
        self.set_child(root)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        root.append(paned)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left.set_size_request(300, -1)
        cap = Gtk.Label(label="DEVICES")
        cap.set_xalign(0)
        cap.add_css_class("eyebrow")
        left.append(cap)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self.on_select)
        scroller.set_child(self.listbox)
        left.append(scroller)
        paned.set_start_child(left)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right.set_margin_start(14)

        self.title_label = Gtk.Label(label="Select a device")
        self.title_label.set_xalign(0)
        self.title_label.add_css_class("device-title")
        right.append(self.title_label)

        self.meta_label = Gtk.Label(label="")
        self.meta_label.set_xalign(0)
        self.meta_label.add_css_class("device-meta")
        right.append(self.meta_label)

        colour_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl = Gtk.Label(label="COLOUR")
        lbl.add_css_class("eyebrow")
        colour_row.append(lbl)
        self.colour_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
        self.colour_button.set_rgba(hex_to_rgba(self.colour_hex))
        colour_row.append(self.colour_button)
        right.append(colour_row)

        bright_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        blbl = Gtk.Label(label="BRIGHTNESS")
        blbl.add_css_class("eyebrow")
        bright_row.append(blbl)
        self.bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.bright.set_value(self.brightness)
        self.bright.set_hexpand(True)
        self.bright.set_draw_value(True)
        bright_row.append(self.bright)
        right.append(bright_row)

        # RAM kit picker: appears only for the grouped RAM entry. ALL writes
        # every stick in one go; a number writes just that module.
        self.ram_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        ram_lbl = Gtk.Label(label="STICK")
        ram_lbl.add_css_class("eyebrow")
        ram_lbl.set_xalign(0)
        self.ram_row.append(ram_lbl)
        self.ram_buttons = Gtk.FlowBox()
        self.ram_buttons.set_selection_mode(Gtk.SelectionMode.NONE)
        self.ram_buttons.set_max_children_per_line(9)
        self.ram_buttons.set_min_children_per_line(1)
        self.ram_buttons.set_column_spacing(4)
        self.ram_buttons.set_row_spacing(4)
        self.ram_buttons.set_halign(Gtk.Align.START)
        self.ram_row.append(self.ram_buttons)
        self.ram_row.set_visible(False)
        right.append(self.ram_row)

        # Effect and speed, same hardware list the G.Skill tool offers.
        self.effect_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        effect_lbl = Gtk.Label(label="EFFECT")
        effect_lbl.add_css_class("eyebrow")
        self.effect_row.append(effect_lbl)
        self.effect_dropdown = Gtk.DropDown.new_from_strings(ram.MODE_NAMES)
        self.effect_dropdown.set_selected(1)          # Static
        self.effect_row.append(self.effect_dropdown)
        self.effect_row.set_visible(False)
        right.append(self.effect_row)

        self.speed_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        speed_lbl = Gtk.Label(label="SPEED")
        speed_lbl.add_css_class("eyebrow")
        self.speed_row.append(speed_lbl)
        self.speed_dropdown = Gtk.DropDown.new_from_strings(ram.SPEED_NAMES)
        self.speed_dropdown.set_selected(2)           # Normal
        self.speed_row.append(self.speed_dropdown)
        self.speed_row.set_visible(False)
        right.append(self.speed_row)

        # My own effects: software-driven frames rather than chip modes.
        self.mine_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        mine_lbl = Gtk.Label(label="MY EFFECTS")
        mine_lbl.add_css_class("eyebrow")
        self.mine_row.append(mine_lbl)
        self.mine_dropdown = Gtk.DropDown.new_from_strings(["None"] + effects.EFFECT_NAMES)
        self.mine_dropdown.set_selected(0)
        self.mine_row.append(self.mine_dropdown)
        self.mine_row.set_visible(False)
        right.append(self.mine_row)
        self.mine_dropdown.connect("notify::selected", lambda *_: self.refresh_palette())

        # One colour picker per slot the chosen effect declares.
        self.palette_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.palette_row.set_visible(False)
        right.append(self.palette_row)
        self.palette_buttons = []

        self.ram_choice = 0
        self.ram_syncing = False
        self.ram_toggles = []

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        apply = Gtk.Button(label="Apply to this device")
        apply.add_css_class("apply")
        apply.connect("clicked", lambda *_: self.apply_selected())
        buttons.append(apply)
        self.stop_button = Gtk.Button(label="Stop effect")
        self.stop_button.connect("clicked", lambda *_: self.stop_animation())
        self.stop_button.set_visible(False)
        buttons.append(self.stop_button)
        right.append(buttons)
        self.apply_button = apply
        self.actions.append(apply)

        self.zones_label = Gtk.Label(label="")
        self.zones_label.set_xalign(0)
        self.zones_label.add_css_class("device-meta")
        self.zones_label.set_wrap(True)
        right.append(self.zones_label)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        right.append(spacer)
        paned.set_end_child(right)

        self.status = Gtk.Label(label="Starting…")
        self.status.set_xalign(0)
        self.status.add_css_class("status")
        activity = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.spinner = Gtk.Spinner()
        activity.append(self.spinner)
        activity.append(self.status)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_hexpand(True)
        activity.set_hexpand(True)
        root.append(activity)

        self.keepalive_source = GLib.timeout_add_seconds(20, self.keep_keyboard_alive)
        GLib.idle_add(self.scan)

    # ------------------------------------------------------------------ state
    def release_keyboard(self):
        self.keyboard_alive = False
        if self.keyboard_touched:
            ok, message = keyboard_request(["--restore"])
            if ok:
                self.keyboard_touched = False
            return ok, message
        return True, ""

    def on_close(self, *_args):
        self.closed = True
        self.cancelled.set()
        if self.keepalive_source is not None:
            GLib.source_remove(self.keepalive_source)
            self.keepalive_source = None
        def cleanup():
            # Wait for any colour write before restoring hardware control.
            with self.hardware_lock:
                self.release_keyboard()
        threading.Thread(target=cleanup, name="rgb-release").start()
        return False

    def keep_keyboard_alive(self):
        if self.closed:
            return False
        if self.busy or not self.keyboard_touched or not self.keyboard_alive:
            return True
        def work():
            result = keyboard_request(["--ping"])
            if not result[0]:
                self.release_keyboard()
            return result
        def finish(result):
            ok, message = result
            self.set_status("Keyboard lighting active" if ok else message, ok)
        self.run_job("Checking keyboard lighting…", work, finish)
        return True

    def set_busy(self, busy):
        self.busy = busy
        for action in self.actions:
            action.set_sensitive(not busy)
        self.colour_button.set_sensitive(not busy)
        self.bright.set_sensitive(not busy)
        self.spinner.set_spinning(busy)
        self.spinner.set_visible(busy)

    def post_status(self, message):
        def deliver():
            if not self.closed:
                self.set_status(message)
            return False
        GLib.idle_add(deliver)

    def run_job(self, message, work, finish):
        if self.busy or self.closed:
            return False
        self.set_busy(True)
        self.set_status(message)
        def worker():
            with self.hardware_lock:
                try:
                    result, error = work(), None
                except Exception as exc:
                    result, error = None, str(exc)
            def done():
                if not self.closed:
                    self.set_busy(False)
                    if error:
                        self.set_status(error, False)
                    else:
                        finish(result)
                return False
            GLib.idle_add(done)
        # Non-daemon: any in-flight subprocess is reaped before process exit.
        threading.Thread(target=worker, name="rgb-hardware").start()
        return False

    def scan(self):
        return self.run_job("Scanning devices…", parse_devices, self.show_devices)

    def show_devices(self, devices):
        self.selected = None
        while (child := self.listbox.get_first_child()):
            self.listbox.remove(child)
        self.devices = devices
        self.title_label.set_text("Select a device")
        self.meta_label.set_text("")
        self.zones_label.set_text("")
        for dev in self.devices:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            name = Gtk.Label(label=dev.name)
            name.set_xalign(0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.add_css_class("device-name")
            if dev.ram_sticks:
                sub_text = (f"{dev.type} · {len(dev.ram_sticks)} sticks · "
                            f"{dev.led_count} LEDs")
            else:
                sub_text = f"{dev.type or 'device'} · {dev.led_count} LED(s)"
            sub = Gtk.Label(label=sub_text)
            sub.set_xalign(0)
            sub.add_css_class("device-sub")
            box.append(name)
            box.append(sub)
            row.set_child(box)
            row.device = dev
            self.listbox.append(row)
        self.set_status(f"{len(self.devices)} device(s) found")
        first = self.listbox.get_first_child()
        if first:
            self.listbox.select_row(first)

    def on_select(self, _lb, row):
        if row is None:
            return
        dev = row.device
        self.selected = dev
        self.title_label.set_text(dev.name)
        self.build_ram_choices(dev)
        if dev.ram_sticks:
            self.meta_label.set_text(
                f"{dev.type} · {len(dev.ram_sticks)} sticks · {dev.led_count} LEDs")
            self.zones_label.set_text(
                "Apply writes only the selected stick; ALL writes the whole kit.")
            if not self.state_restored:
                self.apply_saved_state()
                self.state_restored = True
        else:
            self.meta_label.set_text(f"{dev.type} · {len(dev.zones)} channel(s) · {dev.led_count} LED(s)")
            self.zones_label.set_text("Channels: " + (", ".join(dev.zones) if dev.zones else "none"))
        self.update_apply_label()

    def build_ram_choices(self, dev):
        while (child := self.ram_buttons.get_first_child()):
            self.ram_buttons.remove(child)
        self.ram_toggles = []
        self.ram_choice = 0
        self.effect_row.set_visible(bool(dev.ram_sticks))
        self.speed_row.set_visible(bool(dev.ram_sticks))
        self.mine_row.set_visible(bool(dev.ram_sticks))
        self.refresh_palette()
        if not dev.ram_sticks:
            self.ram_row.set_visible(False)
            return
        labels = ["ALL"] + [str(index + 1) for index in range(len(dev.ram_sticks))]
        for index, label in enumerate(labels):
            button = Gtk.ToggleButton(label=label)
            button.add_css_class("ram-choice")
            button.set_halign(Gtk.Align.START)
            button.set_tooltip_text("Every stick" if index == 0
                                    else str(dev.ram_sticks[index - 1]))
            button.set_active(index == 0)
            button.connect("toggled", self.on_ram_choice, index)
            self.ram_buttons.append(button)
            self.ram_toggles.append(button)
        self.ram_row.set_visible(True)

    def on_ram_choice(self, button, index):
        if self.ram_syncing:
            return
        self.ram_syncing = True
        try:
            if button.get_active():
                for other_index, other in enumerate(self.ram_toggles):
                    if other_index != index and other.get_active():
                        other.set_active(False)
                self.ram_choice = index
            elif not any(toggle.get_active() for toggle in self.ram_toggles):
                # Keep exactly one target selected.
                button.set_active(True)
        finally:
            self.ram_syncing = False
        self.update_apply_label()

    def update_apply_label(self):
        dev = self.selected
        if dev and dev.ram_sticks:
            count = len(dev.ram_sticks)
            self.apply_button.set_label(
                f"Apply to all {count} sticks" if self.ram_choice == 0
                else f"Apply to stick {self.ram_choice}")
        else:
            self.apply_button.set_label("Apply to this device")

    # ------------------------------------------------------------------ apply
    def apply_selected(self):
        if self.selected and not self.busy:
            self.apply_device(self.selected)

    def apply_device(self, dev):
        if dev.ram_sticks:
            sticks = dev.ram_sticks
            if self.ram_choice > 0:
                sticks = [sticks[self.ram_choice - 1]]
            brightness = int(self.bright.get_value())
            custom = self.mine_dropdown.get_selected()
            if custom > 0:
                name = effects.EFFECT_NAMES[custom - 1]
                payload = {
                    "kind": "custom",
                    "effect": name,
                    "colours": [list(colour) for colour in self.palette_colours()],
                    "brightness": brightness,
                    "sticks": [[stick.bus, stick.address] for stick in sticks],
                }
                self.write_lighting(payload, f"{name} running on {len(sticks)} stick(s) "
                                             f"at {brightness}%")
                self.animating = True
                self.stop_button.set_visible(True)
                return
            payload = {
                "kind": "hardware",
                "mode": ram.MODES[self.effect_dropdown.get_selected()][1],
                "speed": ram.SPEEDS[self.speed_dropdown.get_selected()][1],
                "colour": rgb_to_hex(self.colour_button.get_rgba()),
                "brightness": brightness,
                "sticks": [[stick.bus, stick.address] for stick in sticks],
            }
            self.write_lighting(payload, f"Applied to {len(sticks)} stick(s)")
            self.animating = False
            self.stop_button.set_visible(False)
            return
        self.start_apply([dev], rgb_to_hex(self.colour_button.get_rgba()))

    def write_lighting(self, payload, message):
        """Hand the RAM job to the lighting service; the panel never writes sticks."""
        try:
            os.makedirs(os.path.dirname(RAM_STATE), exist_ok=True)
            temp = RAM_STATE + ".tmp"
            with open(temp, "w") as handle:
                json.dump(payload, handle)
            os.replace(temp, RAM_STATE)
            self.saved_state = payload
            self.set_status(message)
        except OSError as exc:
            self.set_status(f"Could not reach the lighting service: {exc}", False)

    # ------------------------------------------------------------- my effects
    def load_saved_state(self):
        try:
            with open(RAM_STATE) as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return {}

    def apply_saved_state(self):
        """Show what the lighting service is actually running."""
        state = self.saved_state or self.load_saved_state()
        if not state:
            return
        self.saved_state = state
        brightness = int(state.get("brightness", self.brightness))
        self.bright.set_value(brightness)
        mode_ids = [value for _name, value in ram.MODES]
        speed_ids = [value for _name, value in ram.SPEEDS]
        if state.get("kind") == "custom":
            name = state.get("effect")
            if name in effects.EFFECT_NAMES:
                self.mine_dropdown.set_selected(effects.EFFECT_NAMES.index(name) + 1)
                for button, colour in zip(self.palette_buttons, state.get("colours") or []):
                    button.set_rgba(hex_to_rgba("#%02x%02x%02x" % tuple(colour)))
                self.animating = True
                self.stop_button.set_visible(True)
        elif state.get("kind") == "hardware":
            self.mine_dropdown.set_selected(0)
            try:
                self.effect_dropdown.set_selected(mode_ids.index(int(state.get("mode", 1))))
            except ValueError:
                pass
            try:
                self.speed_dropdown.set_selected(speed_ids.index(int(state.get("speed", 2))))
            except ValueError:
                pass
            self.colour_button.set_rgba(hex_to_rgba(state.get("colour") or "#00ff41"))
            self.animating = False
            self.stop_button.set_visible(False)
        sticks = state.get("sticks")
        if sticks and len(sticks) == 1 and self.ram_toggles:
            key = (int(sticks[0][0]), int(sticks[0][1]))
            for index, stick in enumerate(self.selected.ram_sticks):
                if (stick.bus, stick.address) == key:
                    self.ram_toggles[index + 1].set_active(True)
                    break

    def refresh_palette(self):
        """Rebuild the colour pickers for the chosen effect's palette."""
        while (child := self.palette_row.get_first_child()):
            self.palette_row.remove(child)
        self.palette_buttons = []
        choice = self.mine_dropdown.get_selected()
        dev = self.selected
        if not (dev and dev.ram_sticks) or choice <= 0:
            self.palette_row.set_visible(False)
            return
        name = effects.EFFECT_NAMES[choice - 1]
        _effect, defaults, labels = effects.BY_NAME[name]
        for label, default in zip(labels, defaults):
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            caption = Gtk.Label(label=label.upper())
            caption.add_css_class("eyebrow")
            caption.set_xalign(0)
            cell.append(caption)
            button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
            button.set_rgba(hex_to_rgba("#%02x%02x%02x" % tuple(default)))
            cell.append(button)
            self.palette_row.append(cell)
            self.palette_buttons.append(button)
        self.palette_row.set_visible(True)

    def palette_colours(self):
        return [rgba_to_tuple(button.get_rgba()) for button in self.palette_buttons]

    def stop_animation(self):
        """Freeze the kit on the chosen colour; the service keeps owning it."""
        dev = self.selected
        sticks = dev.ram_sticks if dev and dev.ram_sticks else []
        if self.ram_choice > 0 and sticks:
            sticks = [sticks[self.ram_choice - 1]]
        self.animating = False
        self.stop_button.set_visible(False)
        if not sticks:
            return False
        payload = {
            "kind": "hardware",
            "mode": ram.MODE_STATIC,
            "speed": 2,
            "colour": rgb_to_hex(self.colour_button.get_rgba()),
            "brightness": int(self.bright.get_value()),
            "sticks": [[stick.bus, stick.address] for stick in sticks],
        }
        self.write_lighting(payload, "Effect stopped")
        return True

    def start_apply(self, devices, colour):
        if self.busy or not devices:
            return
        # GTK values are copied here; worker code never touches a widget.
        self.colour_hex = colour
        self.brightness = int(self.bright.get_value())
        brightness = self.brightness
        devices = list(devices)
        def native_write(value, level):
            # Set before USB begins so closing during first apply still restores.
            self.keyboard_touched = True
            result = keyboard_colour(value, level)
            self.keyboard_alive = result[0]
            if not result[0]:
                self.release_keyboard()
            return result
        def work():
            return write_devices(devices, colour, brightness, self.post_status,
                                 self.cancelled, keyboard_writer=native_write)
        def finish(result):
            ok, message = result
            self.set_status(message, ok)
        self.run_job("Applying colours…", work, finish)

    # ----------------------------------------------------------------- chrome
    def set_status(self, text, ok=True):
        self.status.set_text(text)
        self.status.set_tooltip_text(text)
        self.status.remove_css_class("bad")
        if not ok:
            self.status.add_css_class("bad")

    def show_about(self):
        dlg = Gtk.AboutDialog(transient_for=self, modal=True)
        dlg.set_program_name("PeaceMachine RGB Control")
        dlg.set_version("1.0.0")
        dlg.set_comments("Board, fans, GPU and mouse from one window, over a live "
                         "OpenRGB controller. K70 Optical colour uses its native HID protocol.")
        dlg.set_website("https://peacemachinestudios.com")
        dlg.set_copyright("© 2026 William James Sova (C0D3D) — PeaceMachineStudios")
        dlg.set_logo_icon_name("preferences-color")
        dlg.set_license_type(Gtk.License.MIT_X11)
        dlg.present()


class RgbApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=0)

    def do_activate(self):
        win = self.props.active_window or Panel(self)
        win.present()


def main():
    provider = Gtk.CssProvider()
    css = os.path.join(HERE, "rgb.css")
    if os.path.exists(css):
        provider.load_from_path(css)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER)
    RgbApp().run(sys.argv)


if __name__ == "__main__":
    main()
