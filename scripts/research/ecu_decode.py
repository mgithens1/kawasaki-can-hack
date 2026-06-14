#!/usr/bin/env python3
"""Decode 0x070C ECU identification and 0x0281 motor data."""
import can
import time

bus = can.Bus(interface='socketcan', channel='can0', bitrate=500000)

# Collect 0x070C frames
print('=== 0x070C ECU Identification ===')
frames = {}
start = time.time()
while time.time() - start < 6:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x070C:
        frames[msg.data[0]] = msg.data

for idx in sorted(frames):
    d = frames[idx]
    ascii_str = ''.join(chr(b) if 0x20 <= b < 0x7f else '.' for b in d)
    print(f'  0x{idx:02x}: {d.hex()}  "{ascii_str}"')

# Build full ASCII string from frames 0x02-0x0B
sw = ''
for idx in range(2, 12):
    if idx in frames:
        d = frames[idx]
        for b in d[1:]:
            sw += chr(b) if 0x20 <= b < 0x7f else ''
print(f'\nSW version string: "{sw}"')

# Decode binary frames 0x0C-0x11 (calibration data)
print('\nBinary frames (0x0C-0x11):')
for idx in [0x0c, 0x0d, 0x0e, 0x0f, 0x10, 0x11]:
    if idx in frames:
        d = frames[idx]
        b12 = (d[1] << 8) | d[2]
        b34 = (d[3] << 8) | d[4]
        b56 = (d[5] << 8) | d[6] if len(d) > 6 else 0
        b7 = d[7] if len(d) > 7 else 0
        print(f'  0x{idx:02x}: b12={b12:5d}(0x{b12:04x}) b34={b34:5d}(0x{b34:04x}) b56={b56:5d}(0x{b56:04x}) b7={b7}')

# Frame 0x01 decode
if 1 in frames:
    d = frames[1]
    year = (d[1] << 8) | d[2]
    month = d[3]
    day = d[4]
    print(f'\nFrame 0x01: year={year} month={month} day={day} → date: {year}-{month:02d}-{day:02d}')

bus.shutdown()