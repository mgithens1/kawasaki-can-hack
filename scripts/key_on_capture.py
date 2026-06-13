#!/usr/bin/env python3
"""Watch for key ON event and track which CAN IDs appear."""
import can
import time

bus = can.Bus(interface='socketcan', channel='can0', bitrate=500000)

print('Waiting for key ON (25s)...', flush=True)

all_ids = {}
start = time.time()
while time.time() - start < 25:
    msg = bus.recv(timeout=0.5)
    if msg is None:
        continue
    ts = time.time() - start
    arb_id = msg.arbitration_id
    data_hex = msg.data.hex()
    
    if arb_id not in all_ids:
        all_ids[arb_id] = ts
        labels = {
            0x0008: 'KEY-ON', 0x0050: 'MODE_STATUS', 0x0054: 'MODE_EV',
            0x0100: 'CLUSTER', 0x0120: 'CONFIG', 0x0121: 'GEAR',
            0x0222: 'STATUS_FLAG', 0x0280: 'MODE_GEAR_EV',
            0x0281: 'MOTOR_ELEC', 0x0282: 'VOLTAGE',
            0x0284: 'TEMP_A', 0x0285: 'TEMP_B',
            0x070C: 'ECU_IDENT', 0x0720: 'TEMPERATURE',
        }
        label = labels.get(arb_id, '')
        print(f'{ts:6.1f}s  0x{arb_id:04X}  {data_hex}  {label}', flush=True)

print(f'\n{len(all_ids)} unique IDs appeared')
bus.shutdown()