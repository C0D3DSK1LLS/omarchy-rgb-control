"""Model firmware replies; never open a USB device."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('k70', Path(__file__).with_name('kb-colour.py'))
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)

class Firmware:
    def __init__(self):
        self.mode = 1
        self.open = False
        self.calls = []
        self.colour = None
        self.fail_rgb = False
    def exchange(self, fd, report):
        k.validate_packet(report)
        self.calls.append(report)
        command = report[1]
        if command == 2:
            return bytes((0, command, 0, self.mode))
        if command == 1:
            self.mode = report[4]
        elif command == 13:
            if self.open:
                raise k.ProtocolError(command, 3)
            self.open = True
        elif command == 5:
            self.open = False
        elif command == 6:
            if self.fail_rgb:
                raise k.ProtocolError(command, 3)
            assert self.open and self.mode == 2
            self.colour = report[21:24]
        return bytes((0, command, 0, 0))

fw = Firmware()
with patch.object(k, 'exchange', side_effect=fw.exchange):
    k.set_colour(42, bytes.fromhex('dc143c'))
    assert fw.colour == bytes.fromhex('dc143c')
    k.set_colour(42, bytes.fromhex('00ff41'))
    assert fw.colour == bytes.fromhex('00ff41')
    assert sum(p[1] == 1 for p in fw.calls) == 1  # No repeated mode switching.
    k.restore_hardware(42)
    assert fw.mode == 1 and not fw.open
# Every control packet is mode/read/ping or handle0 lighting, not input config.
for p in fw.calls:
    k.validate_packet(p)
    if p[1] == 13:
        assert p[:5] == bytes.fromhex('08 0d 00 22 00')
    if p[1] == 6:
        assert p[:9] == bytes.fromhex('08 06 00 ac 01 00 00 12 00')
# Transport itself must reject old key assignments before os.write is reached.
with patch.object(k.os, 'write') as write:
    for number, p in k.capture_packets():
        if number in (10874, 10884, 10888, 10926, 10930, 10958):
            try:
                k.exchange(42, p)
            except ValueError:
                pass
            else:
                raise AssertionError(f'Unsafe frame {number} reached transport')
    assert not write.called
# Real transport framing and reply validation, using mocked system calls.
with patch.object(k.os, 'write', return_value=1025) as write, patch.object(k.os, 'read', return_value=b'\0\x12\0\0'), patch.object(k.select, 'select', return_value=([42], [], [])):
    reply = k.exchange(42, k.packet('08 12'))
    assert reply == b'\0\x12\0\0'
    assert write.call_args.args[1] == b'\0' + k.packet('08 12')
print('PASS: crimson/green updates; repeated-open recovery; no repeated mode switch; hardware restore; old input writes forbidden; exact transport framing')
