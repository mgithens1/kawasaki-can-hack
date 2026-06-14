#!/usr/bin/env python3
"""Try key with correct sub-function 0x06 (not 0x08)."""
import can
import time
import json
import os
from datetime import datetime

bus = can.interface.Bus(channel="can0", bustype="socketcan", bitrate=500000)

for _ in range(50):
    bus.recv(0.01)
time.sleep(0.5)

LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "key_attempts.json")

def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def send_recv(data, tx_id=0x764, rx_id=0x746, timeout=3.0):
    uds = bytearray(data)
    if len(uds) <= 7:
        req = bytearray([0x0 | len(uds)] + list(uds) + [0x00] * (7 - len(uds)))
        bus.send(can.Message(arbitration_id=tx_id, data=req[:8], is_extended_id=False))
    else:
        total_len = len(uds)
        ff = bytearray([0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + list(uds[:6]))
        ff += bytearray([0x00] * (8 - len(ff)))
        bus.send(can.Message(arbitration_id=tx_id, data=ff, is_extended_id=False))
        start = time.time()
        while time.time() - start < timeout:
            msg = bus.recv(timeout=0.5)
            if msg and msg.arbitration_id == rx_id:
                fd = bytes(msg.data)
                if (fd[0] & 0xF0) == 0x30:
                    break
                elif (fd[0] & 0xF0) == 0x00:
                    sf = fd[0] & 0x0F
                    return bytes(fd[1:1+sf]) if sf > 0 else None
                elif (fd[0] & 0xF0) == 0x10:
                    total_rx = ((fd[0] & 0x0F) << 8) | fd[1]
                    reasm = bytearray(fd[2:8])
                    fc = bytearray([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                    bus.send(can.Message(arbitration_id=tx_id, data=fc, is_extended_id=False))
                    while len(reasm) < total_rx:
                        cf = bus.recv(1.0)
                        if cf and cf.arbitration_id == rx_id:
                            cfd = bytes(cf.data)
                            if (cfd[0] & 0xF0) == 0x20:
                                remaining = total_rx - len(reasm)
                                reasm.extend(cfd[1:1+min(7, remaining)])
                    return bytes(reasm[:total_rx])
        remaining_data = uds[6:]
        seq = 1
        while remaining_data:
            chunk = remaining_data[:7]
            remaining_data = remaining_data[7:]
            cf = bytearray([0x20 | (seq & 0x0F)] + list(chunk) + [0x00] * (7 - len(chunk)))
            bus.send(can.Message(arbitration_id=tx_id, data=cf, is_extended_id=False))
            seq += 1

    start = time.time()
    while time.time() - start < timeout:
        msg = bus.recv(timeout=0.5)
        if msg is None:
            continue
        if msg.arbitration_id == rx_id:
            fd = bytes(msg.data)
            pci = fd[0]
            if (pci & 0xF0) == 0x00:
                sf = pci & 0x0F
                if sf == 0:
                    continue
                return bytes(fd[1:1+sf])
            elif (pci & 0xF0) == 0x10:
                total = ((pci & 0x0F) << 8) | fd[1]
                reasm = bytearray(fd[2:8])
                fc = bytearray([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                bus.send(can.Message(arbitration_id=tx_id, data=fc, is_extended_id=False))
                while len(reasm) < total:
                    cf = bus.recv(1.0)
                    if cf and cf.arbitration_id == rx_id:
                        cfd = bytes(cf.data)
                        if (cfd[0] & 0xF0) == 0x20:
                            remaining = total - len(reasm)
                            reasm.extend(cfd[1:1+min(7, remaining)])
                return bytes(reasm[:total])
    return None

# Open session
print(f"[{ts()}] Opening session...")
r = send_recv([0x10, 0x80])
if not r or r[0] != 0x50:
    print(f"[{ts()}] FAILED to open session")
    bus.shutdown()
    exit(1)
print(f"[{ts()}] Session opened")

# Get seed with retry for cooldown
seed = None
for attempt in range(6):
    if attempt > 0:
        wait = 5 * attempt
        print(f"[{ts()}] Waiting {wait}s...")
        time.sleep(wait)
        for _ in range(30):
            bus.recv(0.01)
        r = send_recv([0x10, 0x80])
        if not r or r[0] != 0x50:
            continue
    time.sleep(0.2)
    print(f"[{ts()}] Requesting seed (attempt {attempt+1})...")
    r = send_recv([0x27, 0x07])
    if r and r[0] == 0x67:
        seed = r[2:]
        print(f"[{ts()}] Seed: [{seed.hex(' ')}] ({len(seed)} bytes)")
        break
    elif r and len(r) >= 3 and r[0] == 0x7F:
        nrc = r[2]
        if nrc in (0x33, 0x36):
            print(f"[{ts()}] Locked out (0x{nrc:02X}) — cycle key")
            break
        elif nrc == 0x37:
            print(f"[{ts()}] Cooldown (0x37) — retrying...")
            continue

if seed is None:
    print(f"[{ts()}] Could not get seed")
    bus.shutdown()
    exit(1)

# Generate candidates — using KEY SUB-FUNCTION 0x06
# Known Kawasaki 5-byte pairs
KNOWN_KEYS = [
    bytes([0x63, 0x27, 0x53, 0x67, 0x42]),
    bytes([0x30, 0x20, 0x39, 0x48, 0x74]),
    bytes([0x58, 0x49, 0x57, 0x69, 0x84]),
]

candidates = []
# Known keys padded
for i, key in enumerate(KNOWN_KEYS):
    candidates.append((f"known_{i}_pad_front", b'\x00' + key))
    candidates.append((f"known_{i}_pad_back", key + b'\x00'))
    candidates.append((f"known_{i}_pad_34", key + b'\x34'))

# Simple transforms of the actual seed
candidates.append(("identity", seed))
candidates.append(("XOR_0xFF", bytes([b ^ 0xFF for b in seed])))
candidates.append(("XOR_0xAA", bytes([b ^ 0xAA for b in seed])))
candidates.append(("XOR_0x55", bytes([b ^ 0x55 for b in seed])))
candidates.append(("XOR_0x34", bytes([b ^ 0x34 for b in seed])))
candidates.append(("NOT", bytes([0xFF - b for b in seed])))
candidates.append(("reverse", seed[::-1]))
candidates.append(("increment", bytes([(b + 1) & 0xFF for b in seed])))
candidates.append(("decrement", bytes([(b - 1) & 0xFF for b in seed])))
candidates.append(("add_0x50", bytes([(b + 0x50) & 0xFF for b in seed])))
candidates.append(("sub_0x50", bytes([(b - 0x50) & 0xFF for b in seed])))
candidates.append(("nibble_swap", bytes([((b >> 4) | ((b & 0x0F) << 4)) for b in seed])))
candidates.append(("shl1", bytes([(b << 1) & 0xFF for b in seed])))
candidates.append(("shr1", bytes([b >> 1 for b in seed])))

# Try the first candidate with sub-function 0x06
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--candidate", "-c", type=int, default=0)
args2 = parser.parse_args()

cidx = args2.candidate
if cidx >= len(candidates):
    print(f"Candidate {cidx} out of range (0-{len(candidates)-1})")
    bus.shutdown()
    exit(1)

name, key = candidates[cidx]

print(f"\n[{ts()}] Candidate #{cidx}: {name} = [{key.hex(' ')}]")
print(f"[{ts()}] Using KEY sub-function 0x06 (not 0x08)")
print(f"[{ts()}] Sending: 0x27 0x06 + [{key.hex(' ')}]")

r = send_recv([0x27, 0x06] + list(key), timeout=3.0)
if r:
    if r[0] == 0x67:
        print(f"\n{'='*60}")
        print(f"*** SECURITY ACCESS GRANTED! ***")
        print(f"*** Seed: {seed.hex(' ')} ***")
        print(f"*** Key:  {key.hex(' ')} ***")
        print(f"*** Method: {name} ***")
        print(f"*** Sub-function: 0x06 ***")
        print(f"{'='*60}")
        result = "GRANTED"
    elif len(r) >= 3 and r[0] == 0x7F:
        nrc = r[2]
        nrc_names = {
            0x12: "subFunctionNotSupported",
            0x22: "conditionsNotCorrect",
            0x24: "requestSequenceError",
            0x33: "securityAccessDenied",
            0x35: "invalidKey",
            0x36: "exceededAttempts",
            0x37: "requiredTimeDelayNotExpired",
        }
        print(f"[{ts()}] Result: NRC 0x{nrc:02X} ({nrc_names.get(nrc, 'unknown')})")
        result = f"REJECTED_0x{nrc:02X}_{nrc_names.get(nrc, 'unknown')}"
    else:
        print(f"[{ts()}] Unexpected: {r.hex(' ')}")
        result = f"unexpected_{r.hex()}"
else:
    print(f"[{ts()}] TIMEOUT")
    result = "TIMEOUT"

# Log
attempts = []
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r") as f:
        try:
            attempts = json.load(f)
        except json.JSONDecodeError:
            pass

attempts.append({
    "timestamp": datetime.now().isoformat(),
    "seed": list(seed),
    "seed_hex": seed.hex(" "),
    "key_tried": list(key),
    "key_hex": key.hex(" "),
    "method": name,
    "sub_function": "0x06",
    "result": result,
})

with open(LOG_FILE, "w") as f:
    json.dump(attempts, f, indent=2)

print(f"\n[{ts()}] Logged (attempt #{len(attempts)})")
print(f"[{ts()}] Cycle key to try next candidate (use -c {cidx+1})")

bus.shutdown()