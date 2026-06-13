#!/usr/bin/env python3
"""Passive CAN bus sniffer for Kawasaki Ninja 7 Hybrid.
Listens to ALL traffic on the bus without sending anything.
Captures everything so we can find hybrid system messages,
mode switches, and other broadcast PIDs.

Usage: python3 can_sniffer.py [duration_seconds] [output_file]
  duration_seconds: how long to listen (default 60)
  output_file: log file path (default: can_sniffer_YYYYMMDD_HHMMSS.log)

Requirements: python-can, SocketCAN can0 at 500kbps

States to test (run script for each):
  1. Key ON, run switch OFF (ignition on, no engine)
  2. Key ON, run switch ON, engine OFF (pump priming)
  3. Engine idling
  4. Switch EV/HYBRID/SPORT modes (restart script each time)
"""
import can
import time
import sys
import os
from datetime import datetime
from collections import defaultdict

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 60
if len(sys.argv) > 2:
    OUTFILE = sys.argv[2]
else:
    OUTFILE = f"can_sniffer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

print(f"=== Kawasaki Ninja 7 Hybrid CAN Bus Sniffer ===")
print(f"Listening for {DURATION}s on can0 (500kbps)")
print(f"Output: {OUTFILE}")
print(f"PASSIVE MODE - no messages sent to ECU")
print()

bus = can.interface.Bus(interface="socketcan", channel="can0", bitrate=500000)

# Track unique messages
msg_counts = defaultdict(int)
msg_data_samples = defaultdict(list)  # arb_id -> list of (timestamp, data)
start_time = time.time()
total_msgs = 0

print(f"{'Time':>8s}  {'ID':>6s}  {'DLC'}  {'Data':24s}  {'ASCII'}")
print("-" * 70)

try:
    with open(OUTFILE, 'w') as f:
        f.write(f"# Kawasaki Ninja 7 Hybrid CAN Bus Sniffer Log\n")
        f.write(f"# Started: {datetime.now().isoformat()}\n")
        f.write(f"# Duration: {DURATION}s\n")
        f.write(f"# Passive mode - no messages sent\n")
        f.write(f"# Format: timestamp arb_id dlc data_bytes\n\n")

        while time.time() - start_time < DURATION:
            msg = bus.recv(0.1)
            if msg is None:
                continue

            total_msgs += 1
            arb_id = msg.arbitration_id
            dlc = msg.dlc
            data = bytes(msg.data[:dlc])
            ts = time.time() - start_time

            # Track
            msg_counts[arb_id] += 1
            # Keep up to 10 samples per ID, spread out
            if len(msg_data_samples[arb_id]) < 10 or msg_counts[arb_id] % max(1, msg_counts[arb_id] // 10) == 0:
                msg_data_samples[arb_id].append((ts, data))

            # Display
            hex_str = " ".join(f"{b:02X}" for b in data)
            ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
            print(f"{ts:8.3f}  0x{arb_id:04X}  {dlc}  {hex_str:24s}  {ascii_str}")

            # Log
            f.write(f"{ts:.6f} {arb_id:05X} {dlc} {data.hex()}\n")
            if total_msgs % 100 == 0:
                f.flush()

except KeyboardInterrupt:
    print("\nInterrupted!")

elapsed = time.time() - start_time

# Summary
print(f"\n{'='*70}")
print(f"CAPTURE COMPLETE — {total_msgs} messages in {elapsed:.1f}s")
print(f"Log saved to: {OUTFILE}")
print(f"\nUnique arbitration IDs: {len(msg_counts)}")
print(f"\n{'ID':>8s}  {'Count':>7s}  {'Rate':>8s}  {'Notes'}")
print("-" * 70)

# Sort by count descending
for arb_id, count in sorted(msg_counts.items(), key=lambda x: -x[1]):
    rate = count / elapsed if elapsed > 0 else 0
    # Known IDs
    notes = ""
    if arb_id == 0x764:
        notes = "← Our request ID (shouldn't appear in passive mode)"
    elif arb_id == 0x746:
        notes = "← ECU response ID"
    elif arb_id == 0x7DF:
        notes = "← Standard OBD2 request"
    elif arb_id == 0x7E0:
        notes = "← OBD2 ECM"
    elif arb_id == 0x7E8:
        notes = "← OBD2 ECM response"
    elif 0x700 <= arb_id <= 0x7FF:
        notes = "← Diagnostic ID range"

    # Show data variation
    samples = msg_data_samples[arb_id]
    if len(samples) > 1:
        first = samples[0][1]
        last = samples[-1][1]
        changed = first != last
        variation = "CHANGING" if changed else "STATIC"
    else:
        variation = "single"

    print(f"0x{arb_id:04X}  {count:7d}  {rate:6.1f}/s  {variation:8s}  {notes}")

print(f"\nData samples for changing IDs:")
for arb_id, count in sorted(msg_counts.items(), key=lambda x: -x[1]):
    samples = msg_data_samples[arb_id]
    if len(samples) > 1:
        first = samples[0][1]
        last = samples[-1][1]
        if first != last:
            print(f"\n  0x{arb_id:04X} ({count} msgs, {len(samples)} samples):")
            for ts, data in samples[:5]:
                hex_str = " ".join(f"{b:02X}" for b in data)
                print(f"    {ts:8.3f}s  {hex_str}")

bus.shutdown()
print(f"\nDone! Analyze the full log with: grep '{OUTFILE}' or load into SavvyCAN")