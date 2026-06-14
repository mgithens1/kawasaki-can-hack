#!/usr/bin/env python3
"""
One-shot key attempt per key cycle - with seed retry for cooldowns.
"""
import can
import time
import json
import os
import argparse
from datetime import datetime

parser = argparse.ArgumentParser(description="One-shot key attempt per key cycle")
parser.add_argument("--candidate", "-c", type=int, default=0, help="Candidate index to try (0-based, default: 0)")
parser.add_argument("--list", "-l", action="store_true", help="List candidates for last seed and exit")
args = parser.parse_args()

bus = can.interface.Bus(channel="can0", bustype="socketcan", bitrate=500000)

# Drain stale messages
for _ in range(50):
    bus.recv(0.01)

time.sleep(0.5)

LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "key_attempts.json")
SEED_LOG = os.path.join(os.path.dirname(__file__), "..", "seed_log.json")

KNOWN_PAIRS_5BYTE = [
    {"seed": bytes([0x13, 0x52, 0x43, 0x64, 0x75]), "key": bytes([0x63, 0x27, 0x53, 0x67, 0x42])},
    {"seed": bytes([0x57, 0x48, 0x58, 0x49, 0x58]), "key": bytes([0x30, 0x20, 0x39, 0x48, 0x74])},
    {"seed": bytes([0x58, 0x37, 0x48, 0x45, 0x95]), "key": bytes([0x58, 0x49, 0x57, 0x69, 0x84])},
]

def generate_candidates(seed):
    candidates = []
    # Known 5-byte pairs padded to 6
    for i, pair in enumerate(KNOWN_PAIRS_5BYTE):
        key = pair["key"]
        candidates.append((f"known_{i}_pad_front", b'\x00' + key))
        candidates.append((f"known_{i}_pad_back", key + b'\x00'))
        candidates.append((f"known_{i}_pad_34", key + b'\x34'))
    # Simple transforms
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
    # Kawasaki pattern extrapolation
    key5 = bytes([(seed[j] ^ [0x50, 0x2B, 0x10, 0x03, 0x11][j]) & 0xFF for j in range(5)])
    candidates.append(("kawa_diff_pad_34", key5 + b'\x34'))
    candidates.append(("kawa_diff_pad_00", key5 + b'\x00'))
    # Nibble/shift
    candidates.append(("nibble_swap", bytes([((b >> 4) | ((b & 0x0F) << 4)) for b in seed])))
    candidates.append(("shl1", bytes([(b << 1) & 0xFF for b in seed])))
    candidates.append(("shr1", bytes([b >> 1 for b in seed])))
    return candidates

def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def send_recv(data, tx_id=0x764, rx_id=0x746, timeout=3.0):
    """Send UDS data over ISO-TP and receive response. Handles multi-frame TX and RX."""
    uds = bytearray(data)
    
    # Send: single frame if <=7 bytes, multi-frame otherwise
    if len(uds) <= 7:
        # Single frame: PCI byte = 0x0N where N = length
        frame = bytearray([0x0 | len(uds)] + list(uds) + [0x00] * (7 - len(uds)))
        bus.send(can.Message(arbitration_id=tx_id, data=frame[:8], is_extended_id=False))
    else:
        # Multi-frame: First Frame + wait for Flow Control + Consecutive Frames
        total_len = len(uds)
        # First Frame: PCI 0x10XX, where XX is total length (up to 4095)
        ff = bytearray([0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + list(uds[:6]))
        ff += bytearray([0x00] * (8 - len(ff)))  # Pad to 8 bytes
        bus.send(can.Message(arbitration_id=tx_id, data=ff, is_extended_id=False))
        
        # Wait for Flow Control from ECU
        start = time.time()
        fc_received = False
        while time.time() - start < timeout:
            msg = bus.recv(timeout=0.5)
            if msg is None:
                continue
            if msg.arbitration_id == rx_id:
                fd = bytes(msg.data)
                if (fd[0] & 0xF0) == 0x30:  # Flow Control
                    fc_received = True
                    break
                elif (fd[0] & 0xF0) == 0x00:
                    # Single frame response came before FC (unlikely but handle)
                    sf = fd[0] & 0x0F
                    if sf > 0:
                        return bytes(fd[1:1+sf])
                elif (fd[0] & 0xF0) == 0x10:
                    # First frame response came before FC
                    total_rx = ((fd[0] & 0x0F) << 8) | fd[1]
                    reasm = bytearray(fd[2:8])
                    # Send flow control
                    fc_out = bytearray([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                    bus.send(can.Message(arbitration_id=tx_id, data=fc_out, is_extended_id=False))
                    while len(reasm) < total_rx:
                        cf = bus.recv(1.0)
                        if cf and cf.arbitration_id == rx_id:
                            cfd = bytes(cf.data)
                            if (cfd[0] & 0xF0) == 0x20:
                                remaining = total_rx - len(reasm)
                                reasm.extend(cfd[1:1+min(7, remaining)])
                    return bytes(reasm[:total_rx])
        
        if not fc_received:
            # No flow control received, try sending consecutive frame anyway
            pass
        
        # Send Consecutive Frame(s)
        remaining_data = uds[6:]  # Data after the first 6 bytes in the First Frame
        seq = 1
        while remaining_data:
            chunk = remaining_data[:7]
            remaining_data = remaining_data[7:]
            cf = bytearray([0x20 | (seq & 0x0F)] + list(chunk) + [0x00] * (7 - len(chunk)))
            bus.send(can.Message(arbitration_id=tx_id, data=cf[:8], is_extended_id=False))
            seq += 1
    
    # Receive response
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

# Step 1: Open session (with retries for cooldown)
print(f"[{ts()}] Opening session...")
r = send_recv([0x10, 0x80])
if not r or r[0] != 0x50:
    print(f"[{ts()}] FAILED to open session: {r.hex(' ') if r else 'TIMEOUT'}")
    bus.shutdown()
    exit(1)
print(f"[{ts()}] Session opened")

# Step 2: Get seed (with retries for 0x37 cooldown)
max_retries = 6
seed = None
for attempt in range(max_retries):
    if attempt > 0:
        wait = 5 * attempt  # Increasing backoff: 5s, 10s, 15s...
        print(f"[{ts()}] Waiting {wait}s before retry...")
        time.sleep(wait)
        # Re-open session
        for _ in range(30):
            bus.recv(0.01)
        r = send_recv([0x10, 0x80])
        if not r or r[0] != 0x50:
            print(f"[{ts()}] Failed to re-open session")
            continue

    time.sleep(0.2)
    print(f"[{ts()}] Requesting seed (attempt {attempt+1}/{max_retries})...")
    r = send_recv([0x27, 0x07])
    if r and r[0] == 0x67:
        seed = r[2:]
        print(f"[{ts()}] Seed: [{seed.hex(' ')}] ({len(seed)} bytes)")
        break
    elif r and len(r) >= 3 and r[0] == 0x7F:
        nrc = r[2]
        if nrc == 0x37:
            print(f"[{ts()}] NRC 0x37 (cooldown) — waiting and retrying...")
        elif nrc == 0x33:
            print(f"[{ts()}] NRC 0x33 (access denied) — cycle key and try again")
            break
        elif nrc == 0x36:
            print(f"[{ts()}] NRC 0x36 (exceeded attempts) — cycle key required")
            break
        else:
            print(f"[{ts()}] NRC 0x{nrc:02X}")
    else:
        print(f"[{ts()}] No response: {r.hex(' ') if r else 'TIMEOUT'}")
        break

if seed is None:
    print(f"[{ts()}] Could not get seed — cycle key and try again")
    bus.shutdown()
    exit(1)

# Step 3: Generate candidates
candidates = generate_candidates(seed)

# If --list, just show candidates and exit
if args.list:
    print(f"Seed: [{seed.hex(' ')}]")
    print(f"\nAll candidates ({len(candidates)}):")
    for i, (n, k) in enumerate(candidates):
        print(f"  {i:2d}. {n}: [{k.hex(' ')}]")
    bus.shutdown()
    exit(0)

cidx = args.candidate
if cidx >= len(candidates):
    print(f"Candidate index {cidx} out of range (0-{len(candidates)-1})")
    bus.shutdown()
    exit(1)
name, key = candidates[cidx]

print(f"\n[{ts()}] Top 5 candidates (trying #{cidx}):")
for i, (n, k) in enumerate(candidates[:5]):
    marker = " <-- TRYING" if i == cidx else ""
    print(f"  {i:2d}. {n}: [{k.hex(' ')}]{marker}")

# Step 4: Send key immediately
print(f"\n[{ts()}] Attempting key: {name} = [{key.hex(' ')}]")

r = send_recv([0x27, 0x08] + list(key), timeout=3.0)
if r:
    if r[0] == 0x67:
        print(f"\n{'='*60}")
        print(f"*** SECURITY ACCESS GRANTED! ***")
        print(f"*** Seed: {seed.hex(' ')} ***")
        print(f"*** Key:  {key.hex(' ')} ***")
        print(f"*** Method: {name} ***")
        print(f"{'='*60}")
        result = "GRANTED"
    elif len(r) >= 3 and r[0] == 0x7F:
        nrc = r[2]
        nrc_names = {
            0x22: "conditionsNotCorrect",
            0x24: "requestSequenceError",
            0x33: "securityAccessDenied",
            0x35: "invalidKey",
            0x36: "exceededAttempts",
            0x37: "requiredTimeDelayNotExpired",
        }
        print(f"[{ts()}] Key REJECTED: NRC 0x{nrc:02X} ({nrc_names.get(nrc, 'unknown')})")
        result = f"REJECTED_NRC_{nrc:02X}"
    else:
        print(f"[{ts()}] Unexpected response: {r.hex(' ')}")
        result = f"unexpected_{r.hex()}"
else:
    print(f"[{ts()}] TIMEOUT — no response to key")
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
    "result": result,
})

with open(LOG_FILE, "w") as f:
    json.dump(attempts, f, indent=2)

print(f"\n[{ts()}] Logged to key_attempts.json (attempt #{len(attempts)})")
print(f"[{ts()}] Cycle key to try next candidate")

bus.shutdown()