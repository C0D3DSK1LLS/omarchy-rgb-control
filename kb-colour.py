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


def validate_response(response, command):
    if len(response) < 3 or response[:2] != bytes((0, command)):
        raise RuntimeError('Unexpected reply: ' + response[:16].hex(' '))
    if response[2]:
        raise RuntimeError(f'Keyboard rejected command {command:02x}: status {response[2]:02x}')


def exchange(fd, packet):
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
        return
    raise RuntimeError(f'No reply to command {packet[1]:02x}; another RGB controller may be competing')


def self_test():
    packets = capture_packets()
    for _, packet in packets:
        assert recolour(packet, bytes.fromhex('1b33ff')) == packet
        changed = recolour(packet, bytes.fromhex('00ff41'))
        assert len(changed) == 1024
        if packet[1:3] == b'\x06\x00' and packet[7:9] == b'\x12\x00':
            assert changed[:9] == packet[:9] and changed[435:] == packet[435:]
            assert sum(changed[i:i+3] == b'\x00\xff\x41' for i in range(9,435,3)) == sum(packet[i:i+3] == bytes.fromhex('1b33ff') for i in range(9,435,3))
            for i in range(9,435,3):
                if packet[i:i+3] in (b'\0\0\0', b'\xff\xff\xff'):
                    assert changed[i:i+3] == packet[i:i+3]
    validate_response(b'\0\x06\0', 6)
    for bad in (b'\0\x06\x03', b'\0\x0d\0', b''):
        try:
            validate_response(bad, 6)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Accepted a failed/mismatched response')
    print('PASS: exact captured packets, 142 RGB slots, colour slots replaced, unused/white indicator slots preserved, errors rejected')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('colour', nargs='?', default='00FF41', help='RRGGBB')
    parser.add_argument('--self-test', action='store_true', help='check capture fixtures without opening hardware')
    parser.add_argument('--brightness', type=int, default=100, choices=range(101), metavar='0-100',
                        help='scale key RGB values without another RGB controller')
    parser.add_argument('--restore', action='store_true', help='return to the stored hardware lighting profile')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.restore:
        raise RuntimeError('Keyboard colour control disabled after input malfunction; use --restore for hardware mode')
    colour = args.colour.lstrip('#')
    if len(colour) != 6:
        parser.error('colour must contain six hexadecimal digits')
    try:
        rgb = bytes.fromhex(colour)
    except ValueError:
        parser.error('colour must contain six hexadecimal digits')
    rgb = bytes(round(channel * args.brightness / 100) for channel in rgb)
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
            exchange(fd, bytes.fromhex('08 01 03 00 01').ljust(1024, b'\0'))
            print('Hardware profile requested and accepted.')
            return 0
        print(f'{path}: requesting #{colour.upper()} at {args.brightness}% using captured iCUE lighting setup', flush=True)
        for number, packet in capture_packets():
            exchange(fd, recolour(packet, rgb))
            time.sleep(0.003)
    print('All commands accepted. Check the keyboard LEDs; this does not save a boot profile.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'K70: {exc}', file=sys.stderr)
        sys.exit(1)
