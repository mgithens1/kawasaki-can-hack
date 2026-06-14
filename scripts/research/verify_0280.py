#!/usr/bin/env python3
"""Verify 0x0280 format - specifically which byte has the EV flag."""
import can, time

bus = can.Bus(interface='socketcan', channel='can0', bitrate=500000)

# Flush
for _ in range(30):
    bus.recv(timeout=0.02)

# Collect 0x0280 and 0x0054 together
print('0x0054 samples (EV flag + mode):')
print('0x0280 samples (full status):')
print()

v54 = set()
v280 = set()
start = time.time()
while time.time() - start < 4:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x0054:
        v54.add(msg.data.hex())
    elif msg and msg.arbitration_id == 0x0280:
        v280.add(msg.data.hex())

print('0x0054 unique values:')
for v in sorted(v54):
    d = bytes.fromhex(v)
    print(f'  {v}  b0={d[0]:3d}(0x{d[0]:02x}) b1={d[1]:3d}(0x{d[1]:02x})')

print()
print('0x0280 unique values:')
for v in sorted(v280):
    d = bytes.fromhex(v)
    print(f'  {v}  b0={d[0]:3d}(0x{d[0]:02x}) b1={d[1]:3d}(0x{d[1]:02x}) b2={d[2]:3d}(0x{d[2]:02x}) b3={d[3]:3d} b4={d[4]:3d}(0x{d[4]:02x}) b5={d[5]:3d}(0x{d[5]:02x})')

# Also grab 0x0120 and 0x0004
v120 = set()
v004 = set()
start = time.time()
while time.time() - start < 2:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x0120:
        v120.add(msg.data.hex())
    elif msg and msg.arbitration_id == 0x0004:
        v004.add(msg.data.hex())

print()
print('0x0120 unique values:')
for v in sorted(v120):
    d = bytes.fromhex(v)
    print(f'  {v}  b1={d[1]:3d}(0x{d[1]:02x})')

print()
print('0x0004 values:')
for v in sorted(v004):
    print(f'  {v}')

bus.shutdown()