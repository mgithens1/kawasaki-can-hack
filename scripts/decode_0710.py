#!/usr/bin/env python3
"""Systematic 0x0710 frame collection and decode."""
import can, time

bus = can.Bus(interface='socketcan', channel='can0', bitrate=500000)

# Flush
for _ in range(30):
    bus.recv(timeout=0.02)

# Collect 0x0710 frames for 8 seconds
frames = {}
start = time.time()
while time.time() - start < 8:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x0710:
        idx = msg.data[0]
        d = msg.data
        hexval = d.hex()
        if idx not in frames:
            frames[idx] = [hexval]
        elif hexval not in frames[idx]:
            frames[idx].append(hexval)

print(f'Collected {len(frames)} unique frame indices from 0x0710\n')

# Decode each frame
for idx in sorted(frames):
    vals = frames[idx]
    d = bytes.fromhex(vals[0])
    ascii_str = ''.join(chr(b) if 0x20 <= b < 0x7f else '.' for b in d)
    b12 = (d[1]<<8)|d[2]
    b34 = (d[3]<<8)|d[4]
    b56 = (d[5]<<8)|d[6]
    b7 = d[7] if len(d) > 7 else 0

    # Check if mostly ASCII
    ascii_count = sum(1 for b in d[1:] if 0x20 <= b < 0x7f)
    is_ascii = ascii_count > 4

    label = "ASCII" if is_ascii else "BIN"
    live = "LIVE" if len(vals) > 1 else "STATIC"
    print(f'\nFrame 0x{idx:02x} ({label}, {live}, {len(vals)} variant(s)):')
    print(f'  First: {vals[0]}  "{ascii_str}"')
    if len(vals) > 1:
        print(f'  Also:  {vals[1]}')
    if len(vals) > 2:
        print(f'  Also:  {vals[2]}')
    if not is_ascii:
        print(f'  b12={b12:5d}(0x{b12:04x}) b34={b34:5d}(0x{b34:04x}) b56={b56:5d}(0x{b56:04x}) b7={b7}')
        # Try known formulas
        for val_name, val in [('b12', b12), ('b34', b34), ('b56', b56)]:
            if 100 < val < 500:
                print(f'  {val_name}-40={val-40}C  {val_name}/8={val/8:.1f}V  {val_name}/256={val/256:.2f}')
            elif 0 < val < 100:
                print(f'  {val_name}={val} (small int)')

bus.shutdown()