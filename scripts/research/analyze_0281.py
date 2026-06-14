#!/usr/bin/env python3
"""Deep analysis of 0x0281 motor/electrical data."""
import can, time

bus = can.Bus(interface='socketcan', channel='can0', bitrate=500000)

# Collect many 0x0281 samples
samples = []
start = time.time()
while time.time() - start < 10:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x0281:
        d = msg.data
        samples.append({
            'b0': d[0], 'b1': d[1], 'b2': d[2],
            'b3': d[3], 'b4': d[4], 'b5': d[5],
            'b6': d[6], 'b7': d[7]
        })

print(f'Collected {len(samples)} samples')

# Analyze patterns
b1_vals = sorted(set(s['b1'] for s in samples))
b3_vals = sorted(set(s['b3'] for s in samples))
b2_vals = sorted(set(s['b2'] for s in samples))
b5_vals = sorted(set(s['b5'] for s in samples))

print(f'b1 range: {min(b1_vals)}-{max(b1_vals)} ({len(b1_vals)} unique)')
print(f'b2 range: {b2_vals}')
print(f'b3 range: {min(b3_vals)}-{max(b3_vals)} ({len(b3_vals)} unique)')
print(f'b5 range: {b5_vals}')

# Check if b3 is a function of b1
print('\nb1 vs b3 (sorted by b1):')
by_b1 = {}
for s in samples:
    if s['b1'] not in by_b1:
        by_b1[s['b1']] = []
    by_b1[s['b1']].append(s['b3'])

for b1 in sorted(by_b1)[:10]:
    b3s = by_b1[b1]
    print(f'  b1={b1:3d} b3={min(b3s):3d}-{max(b3s):3d} (range={max(b3s)-min(b3s)})')

# Check if b5 is a counter
print('\nb5 sequence (first 20):')
for s in samples[:20]:
    print(f'  b5={s["b5"]:2d}', end='')
print()

# Check b1 signed interpretation
print('\nb1 as signed (-128 to 127 interpretation):')
for b1 in sorted(set(s['b1'] for s in samples))[:5]:
    signed = b1 - 256 if b1 > 127 else b1
    print(f'  b1={b1:3d} (signed={signed:4d})')

# Try: b3 might be scaled from b1 or independent
# Check b3/256 patterns (since b4 is always 0)
print('\nb3 * 256 (since b4=0, b3 is the high byte of a 16-bit value):')
for b3 in sorted(set(s['b3'] for s in samples))[:10]:
    print(f'  b3={b3:3d} b3*256={b3*256:6d}')

# Also check 0x0284 and 0x0285 current values for correlation
print('\n0x0284 current value:')
v284 = set()
start = time.time()
while time.time() - start < 2:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x0284:
        v284.add(msg.data.hex())
print(f'  {v284}')

print('\n0x0285 current value:')
v285 = set()
start = time.time()
while time.time() - start < 2:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x0285:
        v285.add(msg.data.hex())
print(f'  {v285}')

bus.shutdown()