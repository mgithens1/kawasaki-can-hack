#!/usr/bin/env python3
"""Run switch toggle capture — watch specific IDs for changes."""
import can
import time

bus = can.Bus(interface='socketcan', channel='can0', bitrate=500000)

# Track these IDs for changes
watch_ids = {0x0004, 0x0008, 0x0025, 0x0050, 0x0054, 0x0100, 0x0111, 0x0112, 
             0x0120, 0x0121, 0x0125, 0x0222, 0x0273, 0x0280, 0x0281, 0x0282,
             0x0283, 0x0284, 0x0285, 0x03E3}

prev = {}
print('Watching for run switch toggle (15s)...', flush=True)
print('Current state captured. Flip run switch now!', flush=True)
print()

start = time.time()
while time.time() - start < 15:
    msg = bus.recv(timeout=0.1)
    if msg is None:
        continue
    ts = time.time() - start
    arb_id = msg.arbitration_id
    
    # Only watch our target IDs plus any new ones
    if arb_id not in watch_ids:
        continue
    
    data_hex = msg.data.hex()
    key = (arb_id, data_hex)
    if key != prev.get(arb_id):
        prev[arb_id] = key
        d = msg.data
        label = {
            0x0050: 'MODE', 0x0054: 'MODE_EV', 0x0280: 'FULL_MODE',
            0x0120: 'CONFIG', 0x0121: 'GEAR', 0x0222: 'STATUS',
            0x0281: 'MOTOR_ELEC', 0x0282: 'VOLTAGE',
        }.get(arb_id, '')
        
        extra = ''
        if arb_id == 0x0120:
            extra = f'b0=0x{d[0]:02x} b1=0x{d[1]:02x}'
        elif arb_id == 0x0054:
            ev = 'EV' if d[0] in (0x5d,0x1d,0x15) else 'HEV' if d[0] in (0x9d,0x64,0x95,0x55) else f'0x{d[0]:02x}'
            extra = f'{ev} m={d[1]}'
        elif arb_id == 0x0280:
            mode = {0x11:'SPORT',0x12:'ECO',0x13:'ECO+AUTO',0x16:'WALK',0x19:'KEY-OFF'}.get(d[2], f'0x{d[2]:02x}')
            ev = 'EV' if d[0] in (0x5d,0x1d,0x15) else 'HEV' if d[0] in (0x9d,0x64,0x95,0x55) else f'0x{d[0]:02x}'
            gear = 'N' if d[4]==0x45 else 'G' if d[4]==0x55 else f'0x{d[4]:02x}'
            extra = f'{mode} {ev} {gear}'
        elif arb_id == 0x0050:
            extra = f'b0={d[0]}'
        
        print(f'{ts:6.1f}s  0x{arb_id:04X}  {data_hex}  {extra}', flush=True)

bus.shutdown()
print('\nDone!', flush=True)