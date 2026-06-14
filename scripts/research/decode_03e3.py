#!/usr/bin/env python3
"""Decode 0x03E3 and 0x0004 in detail."""
import can, time
from collections import Counter

bus = can.Bus(interface='socketcan', channel='can0', bitrate=500000)

# Flush
for _ in range(30):
    bus.recv(timeout=0.02)

# Collect 0x03E3 for longer to see byte[7] flicker
print('=== 0x03E3 Detailed ===')
e3_bytes = {i: Counter() for i in range(8)}
e3_full = Counter()
start = time.time()
while time.time() - start < 5:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x03E3:
        e3_full[msg.data.hex()] += 1
        for i, b in enumerate(msg.data):
            e3_bytes[i][b] += 1

print('Byte distribution:')
for i in sorted(e3_bytes):
    items = e3_bytes[i].most_common(5)
    total = sum(e3_bytes[i].values())
    print(f'  byte[{i}]: {items} (total={total})')

print(f'\nUnique values: {len(e3_full)}')
for v, cnt in e3_full.most_common(5):
    d = bytes.fromhex(v)
    b01 = (d[0]<<8)|d[1]
    print(f'  {v} (x{cnt})  len={len(d)} b01={b01}({b01:#06x})')

# 0x0004 key-on event
print('\n=== 0x0004 Check (may not appear) ===')
v004 = set()
start = time.time()
while time.time() - start < 2:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x0004:
        v004.add(msg.data.hex())
        print(f'  0x0004 seen: {msg.data.hex()}')
if not v004:
    print('  0x0004 not seen (only appears at key-on)')

bus.shutdown()