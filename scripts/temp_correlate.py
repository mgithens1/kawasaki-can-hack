#!/usr/bin/env python3
"""Correlate CAN temps with KWP2000 temps."""
import can, time

bus = can.Bus(interface='socketcan', channel='can0', bitrate=500000)
ECU_REQ = 0x764
ECU_RESP = 0x746

def kwp(data, timeout=0.3):
    padded = list(data) + [0x55] * (8 - len(data))
    bus.send(can.Message(arbitration_id=ECU_REQ, data=padded, is_extended_id=False))
    time.sleep(0.02)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = bus.recv(timeout=0.05)
        if r and r.arbitration_id == ECU_RESP:
            return r
    return None

for _ in range(20):
    bus.recv(timeout=0.02)

# KWP2000 session
r = kwp([0x02, 0x10, 0x80], timeout=1.0)
if r and r.data[1] == 0x50:
    print('KWP OK')
    for pid, name in [(0x06, 'Coolant'), (0x07, 'IAT'), (0x76, 'Voltage')]:
        r = kwp([0x02, 0x21, pid], timeout=0.15)
        if r and r.data[1] == 0x61:
            if pid == 0x76:
                print(f'  {name}: {r.data[3]/8.0:.1f}V (raw={r.data[3]})')
            else:
                print(f'  {name}: {r.data[3]-40}C (raw={r.data[3]})')
else:
    print('KWP FAILED')

# CAN temps
v284 = set()
v720 = set()
start = time.time()
while time.time() - start < 3:
    msg = bus.recv(timeout=0.05)
    if msg and msg.arbitration_id == 0x0284:
        v284.add(msg.data.hex())
    elif msg and msg.arbitration_id == 0x0720:
        v720.add(msg.data.hex())

for v in v284:
    d = bytes.fromhex(v)
    print(f'0x0284: raw_b1={d[1]}  b1-40={d[1]-40}  255-b1={255-d[1]}  b4-40={d[4]-40} b5-40={d[5]-40} b6-40={d[6]-40}')

for v in v720:
    d = bytes.fromhex(v)
    print(f'0x0720: IAT1={((d[0]<<8)|d[1])/256:.1f} IAT2={((d[2]<<8)|d[3])/256:.1f} T3={d[4]-40} T4={d[5]-40} T5={d[6]-40} T6={d[7]-40}')

bus.shutdown()