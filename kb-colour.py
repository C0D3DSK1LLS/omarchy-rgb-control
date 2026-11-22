#!/usr/bin/env python3
"""Capture-backed Corsair 1b1c:1bc6 sender. No GUI or background process.

The HID descriptor is unnumbered: write(2) needs a zero report-number byte
BEFORE the 1024-byte protocol packet. Protocol 08 is not a HID report ID.
Only the vendor usage-1 control interface supports output; usage 2 is input only.
"""
import argparse
import json
import os
from pathlib import Path
import select
import sys
import time

HERE = Path(__file__).resolve().parent
DESCRIPTOR = bytes.fromhex('06 42 ff 09 01 a1 01 15 00 26 ff 00 75 08 96 00 04 09 01 81 02 96 00 04 09 01 91 02 c0')


def capture_packets():
    rows = json.loads((HERE / 'k70-capture.json').read_text())['frames']
    packets = [(row['number'], bytes.fromhex(row['hex'])) for row in rows]
    for number, packet in packets:
        if len(packet) != 1024 or packet[0] != 8:
            raise ValueError(f'Invalid capture fixture {number}')
    return packets


def recolour(packet, rgb):
    if packet[:7] != bytes.fromhex('08 06 00 ac 01 00 00'):
        return packet
    if packet[7:9] != b'\x12\x00':
        raise ValueError('Unexpected RGB payload type')
    result = bytearray(packet)
    # 428-byte payload = type(2) + RGB(142*3). Preserve unused black slots.
    old = bytes.fromhex('1b33ff')
    for offset in range(9, 435, 3):
        triplet = packet[offset:offset + 3]
        if triplet == old:
            result[offset:offset + 3] = rgb
        elif triplet not in (b'\0\0\0', b'\xff\xff\xff'):
            raise ValueError(f'Unexpected colour in capture slot {(offset-9)//3}')
    return bytes(result)


SLOTS = 142


def recolour_slots(packet, colours):
    """Paint the LED slots the capture proved are colour carriers.

    Only slots that hold the captured colour are touched; black and white
    slots are left exactly as captured, so no unknown field is ever written.
    """
    if packet[:7] != bytes.fromhex('08 06 00 ac 01 00 00'):
        raise ValueError('Unexpected packet shape')
    if packet[7:9] != b'\x12\x00':
        raise ValueError('Unexpected RGB payload type')
    result = bytearray(packet)
    old = bytes.fromhex('1b33ff')
    slot = 0
    for offset in range(9, 435, 3):
        if packet[offset:offset + 3] == old:
            colour = colours[slot] if slot < len(colours) else (0, 0, 0)
            result[offset:offset + 3] = bytes(colour)
            slot += 1
    return bytes(result), slot


def control_path():
    matches = []
    for node in Path('/sys/class/hidraw').glob('hidraw*'):
        try:
            identity = (node / 'device/uevent').read_text()
            descriptor = (node / 'device/report_descriptor').read_bytes()
        except OSError:
            continue
        if 'HID_ID=0003:00001B1C:00001BC6' in identity and descriptor == DESCRIPTOR:
            matches.append(Path('/dev') / node.name)
    if len(matches) != 1:
        raise RuntimeError(f'Expected one K70 usage-1 interface; found {len(matches)}')
    return matches[0]


class ProtocolError(RuntimeError):
    def __init__(self, command, status):
        self.command, self.status = command, status
        super().__init__(f"Keyboard rejected command {command:02x}: status {status:02x}")


def validate_packet(packet):
    """Strict boundary: no key assignments, performance, macros or flash writes."""
    if len(packet) != 1024:
        raise ValueError("Expected a 1024-byte protocol packet")
    allowed = (
        '08 02 03',                 # read current control mode
        '08 01 03 00 01',           # restore hardware control
        '08 01 03 00 02',           # enable software lighting
        '08 0d 00 22',              # lighting resource only, handle 0
        '08 05 01 00',              # close lighting handle
        '08 12',                   # firmware keepalive
    )
    if any(packet == bytes.fromhex(head).ljust(1024, b'\0') for head in allowed):
        return
    if (packet[:9] == bytes.fromhex('08 06 00 ac 01 00 00 12 00')
            and not any(packet[435:])):
        return
    raise ValueError("Refusing a non-lighting keyboard command")


def validate_response(response, command):
    if len(response) < 3 or response[:2] != bytes((0, command)):
        raise RuntimeError('Unexpected reply: ' + response[:16].hex(' '))
    if response[2]:
        raise ProtocolError(command, response[2])


def packet(hex_string):
    return bytes.fromhex(hex_string).ljust(1024, b'\0')


def exchange(fd, packet):
    validate_packet(packet)
    report = b'\0' + packet
    count = os.write(fd, report)
    if count != len(report):
        raise RuntimeError(f'Short HID write: {count}/{len(report)}')
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], max(0, deadline-time.monotonic()))
        if not ready:
            break
        try:
            response = os.read(fd, 1024)
        except BlockingIOError:
            continue
        # Other notifications must not count as the requested command's reply.
        if response[:2] != bytes((0, packet[1])):
            continue
        validate_response(response, packet[1])
        print(f'  {packet[:8].hex(" ")} -> {response[:4].hex(" ")}', flush=True)
        return response
    raise RuntimeError(f'No reply to command {packet[1]:02x}; another RGB controller may be competing')


def restore_hardware(fd):
    # Always try mode restoration even if the optional handle close is rejected.
    try:
        exchange(fd, packet('08 05 01 00'))
    except (OSError, RuntimeError):
        pass
    exchange(fd, packet('08 01 03 00 01'))


def enter_software(fd):
    reply = exchange(fd, packet('08 02 03'))
    if len(reply) < 4 or reply[3] not in (1, 2):
        raise RuntimeError('Unexpected keyboard mode')
    if reply[3] == 1:
        exchange(fd, packet('08 01 03 00 02'))
    try:
        exchange(fd, packet('08 0d 00 22'))
    except ProtocolError as exc:
        if exc.status != 3:
            raise
        # ckb-next's bragi_open_handle does this when a handle is already open.
        exchange(fd, packet('08 05 01 00'))
        exchange(fd, packet('08 0d 00 22'))


def set_colour(fd, rgb):
    enter_software(fd)
    template = dict(capture_packets())[10948]
    exchange(fd, recolour(template, rgb))


def set_keys(fd, colours):
    """Paint per-key colours: a list of (r, g, b), one per captured LED slot."""
    enter_software(fd)
    template = dict(capture_packets())[10948]
    frame, painted = recolour_slots(template, colours)
    exchange(fd, frame)
    return painted


def self_test():
    template = dict(capture_packets())[10948]
    assert recolour(template, bytes.fromhex('1b33ff')) == template
    for colour in ('00ff41', 'dc143c', '000000', 'ffffff'):
        changed = recolour(template, bytes.fromhex(colour))
        validate_packet(changed)
        assert changed[:9] == template[:9] and changed[435:] == template[435:]
    # Old input/performance/indicator configuration is forbidden at transport.
    rejected = 0
    for _, captured in capture_packets():
        try:
            validate_packet(captured)
        except ValueError:
            rejected += 1
    assert rejected == 6
    validate_response(b'\0\x06\0', 6)
    try:
        validate_response(b'\0\x06\x03', 6)
    except ProtocolError:
        pass
    else:
        raise AssertionError('Accepted an error response')
    print('PASS: colour packets valid; key-assignment, performance and indicator writes blocked')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('colour', nargs='?', default='00FF41', help='RRGGBB, or a comma list with --keys')
    parser.add_argument('--keys', action='store_true',
                        help='treat the colour argument as a comma-separated list, one per key')
    parser.add_argument('--self-test', action='store_true', help='check capture fixtures without opening hardware')
    parser.add_argument('--brightness', type=int, default=100, choices=range(101), metavar='0-100',
                        help='scale key RGB values without another RGB controller')
    parser.add_argument('--ping', action='store_true', help='keep software lighting active without changing inputs')
    parser.add_argument('--restore', action='store_true', help='return to the stored hardware lighting profile')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.keys:
        colours = []
        for token in args.colour.split(','):
            token = token.strip().lstrip('#')
            if not token:
                colours.append((0, 0, 0))
                continue
            if len(token) != 6:
                parser.error('each key colour needs six hexadecimal digits')
            try:
                rgb = bytes.fromhex(token)
            except ValueError:
                parser.error('each key colour needs six hexadecimal digits')
            colours.append(tuple(round(channel * args.brightness / 100) for channel in rgb))
    else:
        colours = None
    colour = args.colour.lstrip('#')
    if args.keys:
        rgb = b''
        caption = f'{len(colours)} key colour(s)'
    else:
        if len(colour) != 6:
            parser.error('colour must contain six hexadecimal digits')
        try:
            rgb = bytes.fromhex(colour)
        except ValueError:
            parser.error('colour must contain six hexadecimal digits')
        rgb = bytes(round(channel * args.brightness / 100) for channel in rgb)
        caption = f'#{colour.upper()} at {args.brightness}%'
    path = control_path()
    if not path.exists():
        raise RuntimeError(f'{path} is not available here; run this command in your host terminal')
    with path.open('r+b', buffering=0) as handle:
        fd = handle.fileno()
        os.set_blocking(fd, False)
        # Discard stale input before starting our first request.
        for _ in range(32):
            if not select.select([fd], [], [], 0)[0]:
                break
            os.read(fd, 1024)
        if args.restore:
            restore_hardware(fd)
            print('Hardware profile requested and accepted.')
            return 0
        try:
            if args.ping:
                exchange(fd, packet('08 12'))
            elif args.keys:
                print(f'{path}: painting {caption} (lighting only)', flush=True)
                set_keys(fd, colours)
            else:
                print(f'{path}: requesting {caption} (lighting only)', flush=True)
                set_colour(fd, rgb)
        except (OSError, RuntimeError, ValueError):
            try:
                restore_hardware(fd)
            except (OSError, RuntimeError):
                print('Hardware reset also failed; reconnect the keyboard.', file=sys.stderr)
            raise
    print('Lighting command accepted; keyboard assignments were not changed.')
    return 0



if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'K70: {exc}', file=sys.stderr)
        sys.exit(1)
