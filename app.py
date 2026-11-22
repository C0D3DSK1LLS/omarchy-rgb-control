#!/usr/bin/env python3
"""PeaceMachine RGB Control — every LED in the box from one window.

Backend is the locally-built OpenRGB binary (it carries the two patches this
machine needs: the MSI X299 PRO board entry, and the K70 RGB PRO
Optical-Mechanical keyboard entry). This app only ever shells out to it, so
anything OpenRGB can do, this can do — and nothing here fights the hardware.
"""
import json
import os
import re
import shlex
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

APP_ID = "org.jimmy.RgbControl"
OPENRGB = "/usr/local/bin/openrgb"
STATE = os.path.expanduser("~/.local/share/c0d3d/rgb-control/state.json")

PRESETS = [
    ("Matrix", "#00ff41"),
    ("Crimson", "#dc143c"),
    ("Ice", "#8fd6ff"),
    ("Amber", "#ffa500"),
    ("White", "#ffffff"),
    ("Off", "#000000"),
]


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


class Device:
    def __init__(self, index, name):
        self.index = index
        self.name = name
        self.type = ""
        self.zones = []
        self.led_count = 0
        self.modes = []


def parse_devices():
    try:
        out = subprocess.run([OPENRGB, "--list-detailed"], capture_output=True, text=True, timeout=25).stdout
    except Exception:
        return []
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
        elif line.startswith("Zones:"):
            cur.zones = [z.strip("'") for z in re.findall(r"'[^']*'|\S+", line[6:])]
        elif line.startswith("Modes:"):
            cur.modes = [m.strip("'[]") for m in re.findall(r"'[^']*'|\[[^\]]*\]|\S+", line[6:])]
        elif line.startswith("LEDs:"):
            cur.led_count = len(re.findall(r"'[^']*'|\S+", line[5:]))
    return devices


def run_openrgb(args):
    try:
        r = subprocess.run([OPENRGB] + args, capture_output=True, text=True, timeout=25)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as exc:            # pragma: no cover - hardware dependent
        return False, str(exc)


class ZoneRow(Gtk.Box):
    """One zone of one device: colour, brightness, mode, and its own apply."""

    def __init__(self, window, device, zone_index, zone_name, modes):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.window = window
        self.device = device
        self.index = zone_index
        self.set_margin_top(2)
        self.set_margin_bottom(2)

        label = Gtk.Label(label=zone_name)
        label.set_xalign(0)
        label.set_hexpand(True)
        label.add_css_class("zone-name")
        self.append(label)

        self.colour = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
        self.colour.set_rgba(hex_to_rgba(window.last_colour))
        self.colour.set_valign(Gtk.Align.CENTER)
        self.append(self.colour)

        self.mode = Gtk.DropDown.new_from_strings(modes or ["static"])
        for i, m in enumerate(modes or ["static"]):
            if m.lower() == "static":
                self.mode.set_selected(i)
                break
        self.mode.set_valign(Gtk.Align.CENTER)
        self.append(self.mode)

        self.bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.bright.set_value(window.last_brightness)
        self.bright.set_size_request(120, -1)
        self.bright.set_valign(Gtk.Align.CENTER)
        self.bright.add_mark(100, Gtk.PositionType.RIGHT, None)
        self.append(self.bright)

        apply = Gtk.Button(label="Apply")
        apply.add_css_class("apply")
        apply.connect("clicked", lambda *_: self.apply())
        self.append(apply)

    def apply(self):
        colour = rgb_to_hex(self.colour.get_rgba()).lstrip("#")
        mode = self.mode.get_selected_item().get_string()
        brightness = int(self.bright.get_value())
        self.window.last_colour = "#" + colour
        self.window.last_brightness = brightness
        ok, msg = run_openrgb(["-d", str(self.device.index), "-z", str(self.index),
                               "-m", mode, "-c", colour, "-b", str(brightness)])
        self.window.set_status(
            f"{self.device.name} · zone {self.index} → {mode} #{colour} at {brightness}%"
            if ok else f"failed: {msg.splitlines()[-1] if msg else 'unknown error'}", ok)
        return ok


class Panel(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="PeaceMachine RGB Control")
        self.set_default_size(980, 640)
        self.devices = []
        self.selected = None
        self.last_colour = "#00ff41"
        self.last_brightness = 70

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        title = Gtk.Label(label="PEACEMACHINE RGB")
        title.add_css_class("app-title")
        header.set_title_widget(title)

        self.rescan_btn = Gtk.Button(label="Rescan")
        self.rescan_btn.connect("clicked", lambda *_: self.scan())
        header.pack_start(self.rescan_btn)

        about = Gtk.Button(label="About")
        about.connect("clicked", lambda *_: self.show_about())
        header.pack_end(about)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(10)
        root.set_margin_bottom(10)
        root.set_margin_start(12)
        root.set_margin_end(12)
        self.set_child(root)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        root.append(paned)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left.set_size_request(280, -1)
        caption = Gtk.Label(label="DEVICES")
        caption.set_xalign(0)
        caption.add_css_class("eyebrow")
        left.append(caption)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self.on_row_selected)
        scroll.set_child(self.listbox)
        left.append(scroll)
        paned.set_start_child(left)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right.set_margin_start(12)

        self.device_title = Gtk.Label(label="Select a device")
        self.device_title.set_xalign(0)
        self.device_title.add_css_class("device-title")
        right.append(self.device_title)

        self.device_meta = Gtk.Label(label="")
        self.device_meta.set_xalign(0)
        self.device_meta.add_css_class("device-meta")
        right.append(self.device_meta)

        zone_caption = Gtk.Label(label="CHANNELS")
        zone_caption.set_xalign(0)
        zone_caption.add_css_class("eyebrow")
        right.append(zone_caption)

        self.zone_scroll = Gtk.ScrolledWindow()
        self.zone_scroll.set_vexpand(True)
        self.zone_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.zone_scroll.set_child(self.zone_box)
        right.append(self.zone_scroll)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        apply_all = Gtk.Button(label="Apply to every channel")
        apply_all.add_css_class("apply")
        apply_all.connect("clicked", lambda *_: self.apply_all())
        actions.append(apply_all)
        right.append(actions)

        paned.set_end_child(right)

        presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cap = Gtk.Label(label="EVERYTHING")
        cap.add_css_class("eyebrow")
        presets.append(cap)
        for name, colour in PRESETS:
            b = Gtk.Button(label=name)
            b.add_css_class("preset")
            b.connect("clicked", lambda _b, c=colour: self.apply_everything(c))
            presets.append(b)
        root.append(presets)

        self.status = Gtk.Label(label="Scanning…")
        self.status.set_xalign(0)
        self.status.add_css_class("status")
        root.append(self.status)

        self.scan()

    # ---------------------------------------------------------------- devices
    def scan(self):
        while (child := self.listbox.get_first_child()):
            self.listbox.remove(child)
        self.devices = parse_devices()
        for dev in self.devices:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            name = Gtk.Label(label=dev.name)
            name.set_xalign(0)
            name.add_css_class("device-name")
            name.set_ellipsize(Pango.EllipsizeMode.END)
            meta = Gtk.Label(label=f"{dev.type or 'device'} · {len(dev.zones)} channel(s)")
            meta.set_xalign(0)
            meta.add_css_class("device-sub")
            box.append(name)
            box.append(meta)
            row.set_child(box)
            row.device = dev
            self.listbox.append(row)
        self.set_status(f"{len(self.devices)} device(s) found", True)
        first = self.listbox.get_first_child()
        if first:
            self.listbox.select_row(first)

    def on_row_selected(self, _lb, row):
        if row is None:
            return
        self.selected = row.device
        dev = self.selected
        self.device_title.set_text(dev.name)
        self.device_meta.set_text(f"{dev.type} · {len(dev.zones)} channel(s) · {dev.led_count} LED(s)")
        while (child := self.zone_box.get_first_child()):
            self.zone_box.remove(child)
        modes = dev.modes or ["static"]
        for i, zone in enumerate(dev.zones):
            self.zone_box.append(ZoneRow(self, dev, i, zone, modes))
        if not dev.zones:
            empty = Gtk.Label(label="This device does not report any channels.")
            empty.add_css_class("device-meta")
            self.zone_box.append(empty)

    def apply_all(self):
        if not self.selected:
            return
        for child in self._zone_rows():
            child.apply()

    def _zone_rows(self):
        rows, child = [], self.zone_box.get_first_child()
        while child:
            if isinstance(child, ZoneRow):
                rows.append(child)
            child = child.get_next_sibling()
        return rows

    def apply_everything(self, colour):
        hexcol = colour.lstrip("#")
        for dev in self.devices:
            run_openrgb(["-d", str(dev.index), "-m", "static", "-c", hexcol, "-b", str(self.last_brightness)])
        self.set_status(f"Every device set to {colour} at {self.last_brightness}%", True)

    # ----------------------------------------------------------------- chrome
    def set_status(self, text, ok=True):
        self.status.set_text(text)
        self.status.remove_css_class("bad")
        if not ok:
            self.status.add_css_class("bad")

    def show_about(self):
        dlg = Gtk.AboutDialog(transient_for=self, modal=True)
        dlg.set_program_name("PeaceMachine RGB Control")
        dlg.set_version("1.0.0")
        dlg.set_comments("Every LED in the box from one window — board, fans, "
                         "keyboard, GPU and mouse.")
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
    css = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rgb.css")
    if os.path.exists(css):
        provider.load_from_path(css)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER)
    RgbApp().run(sys.argv)


if __name__ == "__main__":
    main()
