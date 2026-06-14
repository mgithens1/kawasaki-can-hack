#!/usr/bin/env python3
"""Quick grab of key CAN IDs for correlation."""
import can, time

bus = can.Bus(interface='socketcan', channel='can0', bitrate=500000)

# 0x0710 key frames
targets = {0x30, 0x80, 0x90, 0xB0, 0xC0}
found = {}
start = time.time()
while time.time() - start < 4 and len(found) < 5:
    msg = bus.recv(timeout=0.2)
    if msg and msg.arbitration_id == 0x0710 and msg.data[0] in targets:
        idx = msg.data[0]
        if idx not in found:
            d = msg.data
            found[idx] = list(d)
            b12 = (d[1]<<8)|d[2]
            b34 = (d[3]<<8)|d[4]
            b56 = (d[5]<<8)|d[6]
            print(f'0x0710 frame 0x{idx:02x}: {d.hex()} b12={b12} b34={b34} b56={b56}')

# 0x0281 samples
print('\n0x0281 samples:')
cnt = 0
start = time.time()
while time.time() - start < 3 and cnt < 10:
    msg = bus.recv(timeout=0.1)
    if msg and msg.arbitration_id == 0x0281:
        d = msg.data
        cnt += 1
        b1 = d[1]
        b34 = (d[3]<<8)|d[4]
        b5 = d[5]
        b67 = (d[6]<<8)|d[7]
        print(f'  {d.hex()} b1={b1:3d} b34={b34:5d} b5={b5:2d} b67={b67}')

# 0x0282 for voltage reference
print('\n0x0282 samples:')
v282 = set()
start = time.time()
while time.time() - start < 2:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x0282:
        v282.add(msg.data.hex())
print(f'  {v282}')

bus.shutdown()