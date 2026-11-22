#!/usr/bin/env python3
"""PeaceMachine RGB Control — every LED in the box from one window.

Talks to a running `openrgb --server` through the SDK (see orbg.py) instead of
shelling out: the CLI re-opens every device on each run, which wipes whatever was
applied to the other channels, and that is what kept knocking colours out.

The K70 Optical keyboard uses the capture-backed HID sender for colour and
OpenRGB for brightness. Apply it last because OpenRGB can reset its mode.
"""
import json
import os
import re
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import orbg  # noqa: E402

APP_ID = "org.jimmy.RgbControl"
OPENRGB = "/usr/local/bin/openrgb"
STATE = os.path.join(HERE, "state.json")

PRESETS = [
    ("Matrix", "#00ff41"),
    ("Crimson", "#dc143c"),
    ("Ice", "#8fd6ff"),
    ("Amber", "#ffa500"),
    ("White", "#ffffff"),
    ("Off", "#000000"),
]

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


class Device:
    def __init__(self, index, name):
        self.index = index
        self.name = name
        self.type = ""
        self.zones = []
        self.led_count = 0
        self.modes = []
        self.keyboard = False


def parse_devices():
    try:
        out = subprocess.run([OPENRGB, "--list-detailed"], capture_output=True,
                             text=True, timeout=25).stdout
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
            cur.keyboard = cur.type.lower() == "keyboard"
        elif line.startswith("Zones:"):
            cur.zones = [z.strip("'") for z in re.findall(r"'[^']*'|\S+", line[6:])]
        elif line.startswith("Modes:"):
            cur.modes = [m.strip("'[]") for m in re.findall(r"'[^']*'|\[[^\]]*\]|\S+", line[6:])]
        elif line.startswith("LEDs:"):
            cur.led_count = len(re.findall(r"'[^']*'|\S+", line[5:]))
    return devices


def cli(args):
    try:
        r = subprocess.run([OPENRGB] + args, capture_output=True, text=True, timeout=25)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as exc:
        return False, str(exc)


def is_k70_optical(dev):
    return dev.keyboard and "k70 rgb pro optical" in dev.name.lower()


def keyboard_colour(colour):
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "kb-colour.py"), colour.lstrip("#")],
            capture_output=True, text=True, timeout=15)
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except Exception as exc:
        return False, str(exc)


class Panel(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="PeaceMachine RGB Control")
        self.set_default_size(940, 620)
        self.devices = []
        self.selected = None
        self.client = None
        self.colour_hex = "#00ff41"
        self.brightness = 80

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        title = Gtk.Label(label="PEACEMACHINE RGB")
        title.add_css_class("app-title")
        header.set_title_widget(title)
        rescan = Gtk.Button(label="Rescan")
        rescan.connect("clicked", lambda *_: self.scan())
        header.pack_start(rescan)
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

        apply = Gtk.Button(label="Apply to this device")
        apply.add_css_class("apply")
        apply.connect("clicked", lambda *_: self.apply_selected())
        right.append(apply)

        self.zones_label = Gtk.Label(label="")
        self.zones_label.set_xalign(0)
        self.zones_label.add_css_class("device-meta")
        self.zones_label.set_wrap(True)
        right.append(self.zones_label)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        right.append(spacer)
        paned.set_end_child(right)

        presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pcap = Gtk.Label(label="EVERYTHING")
        pcap.add_css_class("eyebrow")
        presets.append(pcap)
        for name, colour in PRESETS:
            b = Gtk.Button(label=name)
            b.add_css_class("preset")
            b.connect("clicked", lambda _b, c=colour: self.apply_everything(c))
            presets.append(b)
        root.append(presets)

        self.status = Gtk.Label(label="Starting…")
        self.status.set_xalign(0)
        self.status.add_css_class("status")
        root.append(self.status)

        self.scan()

    # ------------------------------------------------------------------ state
    def connect(self):
        # Deliberately no OpenRGB server: a running server holds the board open
        # and the command-line writes then land nowhere. CLI only.
        return None

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
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.add_css_class("device-name")
            sub = Gtk.Label(label=f"{dev.type or 'device'} · {dev.led_count} LED(s)")
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
        self.meta_label.set_text(f"{dev.type} · {len(dev.zones)} channel(s) · {dev.led_count} LED(s)")
        self.zones_label.set_text("Channels: " + (", ".join(dev.zones) if dev.zones else "none"))

    # ------------------------------------------------------------------ apply
    def apply_selected(self):
        if self.selected:
            self.apply_device(self.selected)

    def apply_device(self, dev):
        colour = rgb_to_hex(self.colour_button.get_rgba())
        self.colour_hex = colour
        self.brightness = int(self.bright.get_value())

        if dev.keyboard:
            if is_k70_optical(dev):
                # Brightness works through OpenRGB; colour needs the actual
                # optical keyboard protocol. Run HID last, after CLI teardown.
                ok, msg = cli(["-d", dev.name, "-b", str(self.brightness)])
                if ok:
                    ok, msg = keyboard_colour(colour)
                self.set_status(f"{dev.name}: {colour} at {self.brightness}%" if ok else
                                f"{dev.name}: {msg.splitlines()[-1] if msg else 'failed'}", ok)
                return ok
            ok, msg = cli(["-d", dev.name, "-m", "Static", "-c", colour.lstrip("#"),
                           "-b", str(self.brightness)])
            self.set_status(f"{dev.name}: hardware Static {colour}" if ok else
                            f"{dev.name}: {msg.splitlines()[-1] if msg else 'failed'}", ok)
            return ok

        known = [z.lower().replace(" ", "") for z in dev.zones]
        ok = True
        if known and all(k in ZONE_LEDS for k in known):
            for zi, key in enumerate(known):
                args = ["-d", dev.name, "-z", str(zi)]
                if key in ADDRESSABLE:
                    args += ["-sz", str(ADDRESSABLE_LEN)]
                args += ["-m", "static", "-c", colour.lstrip("#"), "-b", str(self.brightness)]
                good, msg = cli(args)
                ok = ok and good
        else:
            ok, msg = cli(["-d", dev.name, "-m", "Static", "-c", colour.lstrip("#"),
                           "-b", str(self.brightness)])
        self.set_status(f"{dev.name}: {colour}" if ok else
                        f"{dev.name}: {msg.splitlines()[-1] if msg else 'failed'}", ok)
        return ok

    def apply_everything(self, colour):
        rgba = hex_to_rgba(colour)
        self.colour_button.set_rgba(rgba)
        failed = []
        # OpenRGB scans can reset the keyboard's software mode. Finish its HID
        # update after every OpenRGB command, regardless of enumeration order.
        for dev in sorted(self.devices, key=is_k70_optical):
            if not self.apply_device(dev):
                failed.append(dev.name)
        if failed:
            self.set_status("Failed: " + ", ".join(failed), False)
        else:
            self.set_status(f"Every device set to {colour} at {self.brightness}%")

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
