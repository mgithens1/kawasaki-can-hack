#!/usr/bin/env python3
"""Kawasaki Ninja 7 Hybrid — Focused capture of fast-changing PIDs.
Captures motor controller (0x0174/0178/017C), electrical (0x0281),
voltage (0x0282/0x0284/0x0285), and temp (0x0720) during:
1. Idle
2. Rev (hold ~3-4K RPM)
3. Return to idle

Usage: python3 can_rev_capture.py [duration_seconds]
"""
import can
import time
import sys
from datetime import datetime

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 30

WATCH_IDS = {
    0x0174: "MotorA",
    0x0178: "MotorB",
    0x017C: "MotorC",
    0x0281: "Elec",
    0x0282: "Volt",
    0x0284: "TempA",
    0x0285: "TempB",
    0x0720: "Temps?",
    0x0100: "Cluster",
    0x0120: "Config",
    0x0125: "Status125",
    0x0054: "Status054",
}

bus = can.interface.Bus(interface="socketcan", channel="can0", bitrate=500000)
# Flush
for _ in range(50):
    bus.recv(0.01)

print(f"=== Rev Capture — {DURATION}s ===")
print(f"Start: {datetime.now().strftime('%H:%M:%S')}")
print(f"Rev the bike! Watch for changes in MotorA/B/C and Elec.")
print(f"{'Time':>8s} {'ID':>6s} {'Label':>8s} {'Data'}")
print("-" * 70)

start = time.time()
last = {}

try:
    while time.time() - start < DURATION:
        msg = bus.recv(0.05)
        if not msg:
            continue
        arb_id = msg.arbitration_id
        if arb_id not in WATCH_IDS:
            continue
        dlc = msg.dlc
        data = bytes(msg.data[:dlc])
        ts = time.time() - start
        label = WATCH_IDS[arb_id]
        hex_str = " ".join(f"{b:02X}" for b in data)
        
        # Only print if data changed from last seen
        prev = last.get(arb_id)
        curr = (arb_id, hex_str)
        if prev != curr:
            print(f"{ts:8.3f} 0x{arb_id:04X} {label:>8s} {hex_str}")
            last[arb_id] = curr
except KeyboardInterrupt:
    pass

print(f"\nDone at {datetime.now().strftime('%H:%M:%S')}")
bus.shutdown()