#!/usr/bin/env python3
"""Motor controller decode capture — engine running with known RPMs."""
import can
import time
import sys
from datetime import datetime

CAN_CHANNEL = 0
CAN_BITRATE = 500000
ECU_REQ = 0x764
ECU_RESP = 0x746

LOG_DIR = "/tmp"
LOG_FILE = f"{LOG_DIR}/can_motor_capture.log"

bus = can.Bus(interface='socketcan', channel=f'can{CAN_CHANNEL}', bitrate=CAN_BITRATE)

# Start KWP2000 session
def kwp_send(data, timeout=0.3):
    padded = list(data) + [0x55] * (8 - len(data))
    bus.send(can.Message(arbitration_id=ECU_REQ, data=padded, is_extended_id=False))
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = bus.recv(timeout=0.05)
        if r and r.arbitration_id == ECU_RESP:
            return r
    return None

# Flush
for _ in range(20):
    bus.recv(timeout=0.02)

# Session
r = kwp_send([0x02, 0x10, 0x80], timeout=1.0)
if r and r.data[1] == 0x50:
    print("KWP2000 session OK")
else:
    print(f"KWP2000 session failed: {r.data.hex() if r else 'no response'}")

print(f"Capturing to {LOG_FILE}")
print("Steps: key ON (5s) → start engine (10s idle) → 2000 RPM (5s) → 3000 RPM (5s) → idle (5s)")
print()

start = time.time()
kwp_last = time.time()
kwp_interval = 0.5  # Read RPM every 0.5s
rpm_log = []

with open(LOG_FILE, 'w') as f:
    while time.time() - start < 45:
        msg = bus.recv(timeout=0.01)
        if msg is None:
            # Time for KWP2000 RPM read?
            if time.time() - kwp_last >= kwp_interval:
                r = kwp_send([0x02, 0x21, 0x09], timeout=0.1)
                if r and r.data[1] == 0x61 and len(r.data) >= 5:
                    rpm = ((r.data[3] << 8) | r.data[4]) / 4
                    rpm_log.append((time.time() - start, rpm))
                    elapsed = time.time() - start
                    print(f"  {elapsed:5.1f}s  RPM={rpm:.0f}", flush=True)
                kwp_last = time.time()
            continue
        
        ts = time.time() - start
        arb_id = msg.arbitration_id
        data_hex = msg.data.hex()
        f.write(f'{ts:.6f} 0x{arb_id:04x} [{msg.dlc}] {data_hex}\n')
        f.flush()

bus.shutdown()
print(f"\nCaptured {len(rpm_log)} RPM readings")
print("RPM log:")
for t, rpm in rpm_log:
    print(f"  {t:5.1f}s  {rpm:.0f}")