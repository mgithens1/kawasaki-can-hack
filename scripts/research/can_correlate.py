#!/usr/bin/env python3
"""Correlate CAN passive data with KWP2000 active readings."""
import can
import time

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

# Flush
for _ in range(20):
    bus.recv(timeout=0.02)

# Start session
r = kwp([0x02, 0x10, 0x80], timeout=1.0)
if r and r.data[1] == 0x50:
    print('KWP2000 session OK')
else:
    print(f'KWP session failed')
    bus.shutdown()
    exit()

# KWP2000 readings
r = kwp([0x02, 0x21, 0x76], timeout=0.15)
if r and r.data[1] == 0x61:
    voltage = r.data[3] / 8.0
    print(f'KWP Voltage (PID 0x76): {voltage:.1f}V (raw=0x{r.data[3]:02x}={r.data[3]})')

r = kwp([0x02, 0x21, 0x06], timeout=0.15)
if r and r.data[1] == 0x61:
    temp = r.data[3] - 40
    print(f'KWP Coolant (PID 0x06): {temp}C (raw=0x{r.data[3]:02x}={r.data[3]})')

r = kwp([0x02, 0x21, 0x07], timeout=0.15)
if r and r.data[1] == 0x61:
    iat = r.data[3] - 40
    print(f'KWP IAT (PID 0x07): {iat}C (raw=0x{r.data[3]:02x}={r.data[3]})')

# PID 0x1B and 0x1C (voltage candidates)
for pid in [0x1B, 0x1C]:
    r = kwp([0x02, 0x21, pid], timeout=0.15)
    if r and r.data[1] == 0x61 and len(r.data) >= 5:
        val16 = (r.data[3] << 8) | r.data[4]
        print(f'KWP PID 0x{pid:02X}: raw=0x{val16:04x}={val16}  (as V: {val16/256:.2f})')

# PID 0x74 (drifting value)
r = kwp([0x02, 0x21, 0x74], timeout=0.15)
if r and r.data[1] == 0x61 and len(r.data) >= 4:
    print(f'KWP PID 0x74: raw=0x{r.data[3]:02x}={r.data[3]}  (as temp: {r.data[3]-40}C)')

# Now grab CAN passive values for 2 seconds
print('\nCAN passive correlation:')
can_0282 = set()
can_0284 = set()
can_0285 = set()
can_0720 = set()
start = time.time()
while time.time() - start < 3:
    msg = bus.recv(timeout=0.05)
    if msg is None:
        continue
    if msg.arbitration_id == 0x0282:
        can_0282.add(msg.data.hex())
    elif msg.arbitration_id == 0x0284:
        can_0284.add(msg.data.hex())
    elif msg.arbitration_id == 0x0285:
        can_0285.add(msg.data.hex())
    elif msg.arbitration_id == 0x0720:
        can_0720.add(msg.data.hex())

print(f'  0x0282 (voltage?): {can_0282}')
print(f'  0x0284 (temp A):   {can_0284}')
print(f'  0x0285 (temp B):   {can_0285}')
print(f'  0x0720 (temps):    {can_0720}')

# Decode 0x0720
for v in can_0720:
    d = bytes.fromhex(v)
    iat1 = ((d[0] << 8) | d[1]) / 256
    iat2 = ((d[2] << 8) | d[3]) / 256
    t3 = d[4] - 40
    t4 = d[5] - 40
    t5 = d[6] - 40
    t6 = d[7] - 40
    print(f'    0x0720 decoded: IAT1={iat1:.1f}C IAT2={iat2:.1f}C T3={t3}C T4={t4}C T5={t5}C T6={t6}C')

# Decode 0x0284
for v in can_0284:
    d = bytes.fromhex(v)
    print(f'    0x0284: b0={d[0]:3d} b1={d[1]:3d} b2={d[2]:3d} b3={d[3]:3d} b4={d[4]:3d} b5={d[5]:3d} b6={d[6]:3d}')

# Decode 0x0282
for v in can_0282:
    d = bytes.fromhex(v)
    val16 = (d[0] << 8) | d[1]
    print(f'    0x0282: b0={d[0]:3d} b1={d[1]:3d}  val16={val16}  val16/256={val16/256:.3f}  val16/100={val16/100:.2f}')

bus.shutdown()