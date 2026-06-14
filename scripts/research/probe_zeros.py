#!/usr/bin/env python3
"""Probe zero-value and mystery CAN IDs for hidden data."""
import can, time

bus = can.Bus(interface='socketcan', channel='can0', bitrate=500000)

# Flush
for _ in range(30):
    bus.recv(timeout=0.02)

# Target IDs that were all zeros before - check if any have changed
zero_ids = {0x0100, 0x0111, 0x0112, 0x0125, 0x0283, 0x03E3, 0x0728}
results = {i: set() for i in zero_ids}

start = time.time()
while time.time() - start < 5:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id in zero_ids:
        results[msg.arbitration_id].add(msg.data.hex())

print('=== Previously-Zero IDs ===')
for can_id in sorted(zero_ids):
    vals = results[can_id]
    if vals:
        for v in sorted(vals):
            d = bytes.fromhex(v)
            all_zero = all(b == 0 for b in d)
            print(f'  0x{can_id:04X}: {v}  all_zero={all_zero}')
    else:
        print(f'  0x{can_id:04X}: not seen')

# Also check some IDs we haven't looked at recently
print('\n=== Additional Mystery IDs ===')
mystery_ids = {0x0004, 0x0008, 0x0120, 0x0222, 0x0710}
# Actually let's just dump ALL unique IDs for a few seconds
all_ids = {}
start = time.time()
while time.time() - start < 3:
    msg = bus.recv(timeout=0.02)
    if msg:
        aid = msg.arbitration_id
        if aid not in all_ids:
            all_ids[aid] = set()
        all_ids[aid].add(msg.data.hex())

print(f'\nAll {len(all_ids)} unique CAN IDs seen in 3 seconds:')
for aid in sorted(all_ids):
    vals = all_ids[aid]
    unique_count = len(vals)
    first_val = sorted(vals)[0]
    d = bytes.fromhex(first_val)
    all_zero = all(b == 0 for b in d)
    if unique_count == 1 and all_zero:
        label = "ALL-ZERO"
    elif unique_count == 1:
        label = f"STATIC"
    else:
        label = f"LIVE({unique_count} vals)"
    print(f'  0x{aid:04X}: {label}  {first_val[:16]}{"..." if len(first_val)>16 else ""}')

bus.shutdown()