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

    def resize_zone(self, device, zone, size):
        self._send(PKT_RESIZEZONE, device, struct.pack("<II", zone, size))
        self.drain(0.08)
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
        payload = struct.pack("<I", len(colours))
        for r, g, b in colours:
            payload += bytes((r, g, b))
        self._send(PKT_UPDATELEDS, device, payload)
        return True

    def update_zone_leds(self, device, zone, colours):
        payload = struct.pack("<II", zone, len(colours))
        for r, g, b in colours:
            payload += bytes((r, g, b))
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
