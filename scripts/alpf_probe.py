#!/usr/bin/env python3
"""Probe KWP2000 PIDs for ALPF/shift mode state. Session type 0x80."""
import can
import time

bus = can.Bus('can0', interface='socketcan', bitrate=500000)
ECU_REQ = 0x764
ECU_RESP = 0x746

def flush():
    for _ in range(10):
        bus.recv(timeout=0.02)

def kwp(data, timeout=0.3):
    # Pad to 8 bytes
    padded = list(data) + [0x55] * (8 - len(data))
    bus.send(can.Message(arbitration_id=ECU_REQ, data=padded, is_extended_id=False))
    time.sleep(0.03)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = bus.recv(timeout=0.05)
        if r and r.arbitration_id == ECU_RESP:
            return r
    return None

flush()

# Start session 0x80
print('Starting session 0x80...')
r = kwp([0x02, 0x10, 0x80], timeout=1.0)
if r:
    d = r.data
    print(f'  {d.hex()}')
    if d[1] == 0x50:
        print('  OK!')
    elif d[1] == 0x7F:
        print(f'  NRC 0x{d[3]:02x}')
        bus.shutdown()
        exit()
else:
    print('  No response')
    bus.shutdown()
    exit()

# Read known PIDs
print('\nKnown sensors:')
for pid, name in [(0x04, 'Load'), (0x05, 'IAP'), (0x06, 'Coolant'), (0x07, 'IAT'),
                   (0x09, 'RPM'), (0x0B, 'Gear'), (0x0C, 'Speed')]:
    r = kwp([0x02, 0x21, pid])
    if r and r.data[1] == 0x61:
        d = r.data
        payload = list(d[3:min(len(d),8)])
        if pid == 0x09:
            rpm = ((payload[0] << 8) | payload[1]) / 4
            print(f'  {name}: {rpm:.0f}')
        elif pid in (0x06, 0x07):
            print(f'  {name}: {payload[0]-40}°C')
        elif pid == 0x0B:
            print(f'  {name}: {payload[0]}')
        elif pid == 0x0C:
            print(f'  {name}: {payload[0]} km/h')
        else:
            print(f'  {name}: {" ".join(f"{b:02x}" for b in payload)}')
    time.sleep(0.02)

# Probe all PIDs for ALPF
print('\nProbing all PIDs (ALPF is ON)...')
found = []
all_pids = list(range(0x00, 0x10)) + list(range(0x10, 0x20)) + list(range(0x20, 0x30))
all_pids += list(range(0x30, 0x40)) + list(range(0x40, 0x50)) + list(range(0x50, 0x60))
all_pids += list(range(0x60, 0x70)) + list(range(0x70, 0x80)) + list(range(0x80, 0x90))
all_pids += list(range(0x90, 0xA0)) + list(range(0xA0, 0xB0)) + list(range(0xB0, 0xC0))
all_pids += list(range(0xC0, 0xD0)) + list(range(0xD0, 0xE0))

for pid in all_pids:
    r = kwp([0x02, 0x21, pid], timeout=0.1)
    if r and r.data[1] == 0x61:
        payload = list(r.data[3:min(len(r.data),8)])
        hex_str = ' '.join(f'{b:02x}' for b in payload)
        print(f'  PID 0x{pid:02X}: {hex_str}')
        found.append((pid, payload))
    time.sleep(0.005)

print(f'\n{len(found)} PIDs found')
bus.shutdown()