#!/usr/bin/env python3
"""A tiny OpenRGB SDK client.

The command line tool re-opens every device on each run, which resets whatever
was applied to the other channels — that is why colours kept knocking each other
out. Speaking the SDK to a running `openrgb --server` keeps the devices open, so
one update lands everywhere at once and nothing is re-initialised behind it.
"""
import socket
import struct
import subprocess
import time

MAGIC = b"ORGB"
HOST, PORT = "127.0.0.1", 6742

PKT_REQUEST_CONTROLLER_COUNT = 0
PKT_REQUEST_CONTROLLER_DATA = 1
PKT_SET_CLIENT_NAME = 50
PKT_RESIZEZONE = 1000
PKT_UPDATELEDS = 1050
PKT_UPDATEZONELEDS = 1051
PKT_SETCUSTOMMODE = 1100


class Client:
    def __init__(self, host=HOST, port=PORT, timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    # -- framing ----------------------------------------------------------
    def _send(self, pkt_id, device=0, payload=b""):
        self.sock.sendall(MAGIC + struct.pack("<III", device, pkt_id, len(payload)) + payload)

    def _recv(self):
        head = b""
        while len(head) < 16:
            chunk = self.sock.recv(16 - len(head))
            if not chunk:
                raise ConnectionError("server closed the connection")
            head += chunk
        magic, device, pkt_id, size = struct.unpack("<4sIII", head)
        if magic != MAGIC:
            raise ConnectionError(f"bad magic {magic!r}")
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("short packet")
            data += chunk
        return device, pkt_id, data

    def recv_until(self, want, timeout=3.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            dev, pkt, data = self._recv()
            if pkt == want:
                return dev, pkt, data
            # ACKs (10) and traffic for other requests are not our answer
        raise TimeoutError(f"no reply for packet {want}")

    def request(self, pkt_id, device=0, payload=b""):
        self._send(pkt_id, device, payload)
        return self.recv_until(pkt_id)

    # -- commands ---------------------------------------------------------
    def set_client_name(self, name="PeaceMachine RGB Control"):
        self._send(PKT_SET_CLIENT_NAME, 0, name.encode() + b"\0")

    def controller_count(self):
        _, _, data = self.request(PKT_REQUEST_CONTROLLER_COUNT)
        return struct.unpack("<I", data)[0] if len(data) >= 4 else 0

    def ack(self, timeout=3.0):
        return self.recv_until(10, timeout)

    def controller_data(self, device):
        """Parse ControllerData (length-prefixed strings) for zones and LEDs."""
        _, _, data = self.request(PKT_REQUEST_CONTROLLER_DATA, device)
        pos = 0

        def u32():
            nonlocal pos
            value = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            return value

        def u16():
            nonlocal pos
            value = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            return value

        def text():
            nonlocal pos
            size = u16()
            raw = data[pos:pos + size]
            pos += size
            return raw.decode("utf-8", "replace")

        index, kind = u32(), u32()
        name, vendor, description, version, serial, location = (text() for _ in range(6))
        modes = []
        for _ in range(u32()):
            mode_name = text()
            modes.append((mode_name, [u32() for _ in range(11)]))
        zones = []
        for _ in range(u32()):
            zone_name = text()
            zone_type, leds_min, leds_max, leds_count = u32(), u32(), u32(), u32()
            matrix = u32()
            if matrix:
                pos += matrix * 4
            zones.append({"name": zone_name, "type": zone_type, "min": leds_min,
                          "max": leds_max, "count": leds_count})
        led_count = u32()
        leds = []
        for _ in range(led_count):
            led_name = text()
            leds.append((led_name, u32()))
        return {"index": index, "type": kind, "name": name, "modes": modes,
                "zones": zones, "led_count": led_count, "leds": leds}

    def resize_zone(self, device, zone, size):
        body = struct.pack("<II", zone, size)
        payload = struct.pack("<I", 4 + len(body)) + body
        self._send(PKT_RESIZEZONE, device, payload)
        self.drain(0.05)
        return True

    def custom_mode(self, device):
        self._send(PKT_SETCUSTOMMODE, device)
        return True

    def drain(self, wait=0.05):
        """Read whatever the server has already sent, without blocking long."""
        old = self.sock.gettimeout()
        self.sock.settimeout(wait)
        try:
            while True:
                self._recv()
        except (socket.timeout, TimeoutError, OSError):
            pass
        finally:
            self.sock.settimeout(old)

    def update_leds(self, device, colours):
        body = b"".join(bytes((r, g, b, 0)) for r, g, b in colours)
        payload = struct.pack("<I", 4 + len(body)) + body
        self._send(PKT_UPDATELEDS, device, payload)
        return True

    def update_zone_leds(self, device, zone, colours):
        body = struct.pack("<I", zone) + b"".join(bytes((r, g, b, 0)) for r, g, b in colours)
        payload = struct.pack("<I", 4 + len(body)) + body
        self._send(PKT_UPDATEZONELEDS, device, payload)
        return True


# ------------------------------------------------------------------ helpers
def server_running():
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


def ensure_server(binary="/usr/local/bin/openrgb", wait=6.0):
    """Start `openrgb --server` if nothing already answers on the port."""
    if server_running():
        return True
    subprocess.Popen([binary, "--server"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                     start_new_session=True)
    deadline = time.time() + wait
    while time.time() < deadline:
        if server_running():
            return True
        time.sleep(0.2)
    return False
