#!/usr/bin/env python3
"""Phase 2 key attempts - multi-byte transforms and exotic algorithms."""
import can
import time
import json
import os
import argparse
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
        bus.send(can.Message(arbitration_id=tx_id, data=ff[:8], is_extended_id=False))
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
            bus.send(can.Message(arbitration_id=tx_id, data=cf[:8], is_extended_id=False))
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

# Multi-byte transform candidates
def generate_candidates(seed):
    candidates = []
    s = list(seed)
    
    # CRC-8 based transforms
    # CRC-8 with various polynomials applied to seed bytes
    for poly_name, poly in [("crc8_0x07", 0x07), ("crc8_0x31", 0x31), ("crc8_0x9B", 0x9B), ("crc8_0xD5", 0xD5)]:
        # XOR each byte with running CRC of previous bytes
        key = bytearray(6)
        crc = 0xFF
        for i in range(6):
            key[i] = seed[i] ^ crc
            crc = seed[i] ^ ((crc << 8) ^ (poly << 8)) & 0xFF if False else 0
            # Simpler: XOR with running accumulator
        # Running XOR accumulator
        key = bytearray(6)
        acc = 0
        for i in range(6):
            acc = acc ^ seed[i]
            key[i] = (seed[i] ^ acc ^ 0x34) & 0xFF
        candidates.append((f"running_xor_{poly_name}", bytes(key)))
    
    # Rotation-based transforms (rotate pairs)
    # Swap adjacent bytes
    key = bytearray(6)
    for i in range(0, 6, 2):
        key[i] = seed[i+1]
        key[i+1] = seed[i]
    candidates.append(("swap_pairs", bytes(key)))
    
    # Rotate bytes left by 1 position
    candidates.append(("rot_left_1", bytes(seed[1:] + seed[:1])))
    
    # Rotate bytes right by 1 position
    candidates.append(("rot_right_1", bytes(seed[-1:] + seed[:-1])))
    
    # Rotate bytes left by 2 positions
    candidates.append(("rot_left_2", bytes(seed[2:] + seed[:2])))
    
    # Rotate bytes right by 2 positions
    candidates.append(("rot_right_2", bytes(seed[-2:] + seed[:-2])))
    
    # XOR with position index
    key = bytes([(seed[i] ^ i) & 0xFF for i in range(6)])
    candidates.append(("xor_position", key))
    
    # XOR with position + 0x34
    key = bytes([(seed[i] ^ (i + 0x34)) & 0xFF for i in range(6)])
    candidates.append(("xor_pos_plus_34", key))
    
    # Cumulative XOR (each byte = current XOR all previous)
    key = bytearray(6)
    key[0] = seed[0]
    for i in range(1, 6):
        key[i] = seed[i] ^ seed[i-1]
    candidates.append(("cumulative_xor", bytes(key)))
    
    # Reverse cumulative XOR
    key = bytearray(6)
    key[5] = seed[5]
    for i in range(4, -1, -1):
        key[i] = seed[i] ^ seed[i+1]
    candidates.append(("rev_cumulative_xor", bytes(key)))
    
    # XOR with previous byte (chained)
    key = bytearray(6)
    key[0] = seed[0] ^ 0x34  # XOR first byte with the constant
    for i in range(1, 6):
        key[i] = seed[i] ^ seed[i-1]
    candidates.append(("chain_xor_34", bytes(key)))
    
    # Add with carry chain
    key = bytearray(6)
    carry = 0
    for i in range(6):
        val = (seed[i] + 0x34 + carry) & 0xFF
        carry = 1 if (seed[i] + 0x34 + carry) > 255 else 0
        key[i] = val
    candidates.append(("add_carry_34", bytes(key)))
    
    # Subtract with borrow chain
    key = bytearray(6)
    borrow = 0
    for i in range(6):
        val = (seed[i] - 0x34 - borrow) & 0xFF
        borrow = 1 if (seed[i] - 0x34 - borrow) < 0 else 0
        key[i] = val
    candidates.append(("sub_borrow_34", bytes(key)))
    
    # Known pair pattern analysis:
    # Pair 1: seed[0]+0x50=key[0], seed[1]-0x2B=key[1], etc.
    # But try applying those specific byte offsets to our 6-byte seed
    # Pair 1 offsets: +0x50, -0x2B, +0x10, +0x03, +0x11
    offsets1 = [0x50, 0xD5, 0x10, 0x03, 0x11, 0x6D]  # D5 = -2B mod 256
    key = bytes([(seed[i] + offsets1[i]) & 0xFF for i in range(6)])
    candidates.append(("pair1_offsets", key))
    
    offsets2 = [0x27, 0xC8, 0xE1, 0xE4, 0x1C, 0x2C]  # Pair 2 offsets
    key = bytes([(seed[i] + offsets2[i]) & 0xFF for i in range(6)])
    candidates.append(("pair2_offsets", key))
    
    offsets3 = [0x00, 0x12, 0x0F, 0x00, 0x42, 0xEF]  # Pair 3 offsets
    key = bytes([(seed[i] + offsets3[i]) & 0xFF for i in range(6)])
    candidates.append(("pair3_offsets", key))
    
    # 5-byte key (drop last byte from 6-byte seed, use known pattern)
    # Maybe key is only 5 bytes?
    # Try first 5 bytes of seed XOR'd with known offsets
    key5 = bytes([(seed[i] ^ seed[5]) & 0xFF for i in range(5)]) + bytes([0x34])
    candidates.append(("xor_with_byte5", key5))
    
    # Seed bytes multiplied mod 256
    key = bytearray(6)
    for i in range(5):
        key[i] = (seed[i] * seed[i+1]) & 0xFF
    key[5] = 0x34
    candidates.append(("multiply_adjacent", bytes(key)))
    
    # Try 5-byte key (truncating seed to 5 bytes with various padding)
    # Maybe the key should be 5 bytes, not 6?
    # Using only first 5 bytes of seed with transforms
    candidates.append(("5byte_identity", seed[:5]))
    candidates.append(("5byte_xor_ff", bytes([b ^ 0xFF for b in seed[:5]])))
    candidates.append(("5byte_xor_34", bytes([b ^ 0x34 for b in seed[:5]])))
    
    # Try sending just the 5 known Kawasaki keys directly (5-byte, no padding)
    for i, pair in enumerate([
        (bytes([0x13, 0x52, 0x43, 0x64, 0x75]), bytes([0x63, 0x27, 0x53, 0x67, 0x42])),
        (bytes([0x57, 0x48, 0x58, 0x49, 0x58]), bytes([0x30, 0x20, 0x39, 0x48, 0x74])),
        (bytes([0x58, 0x37, 0x48, 0x45, 0x95]), bytes([0x58, 0x49, 0x57, 0x69, 0x84])),
    ]):
        candidates.append((f"known5_raw_{i}", pair[1]))
    
    return candidates

# Open session
print(f"[{ts()}] Opening session...")
r = send_recv([0x10, 0x80])
if not r or r[0] != 0x50:
    print(f"[{ts()}] FAILED to open session")
    bus.shutdown()
    exit(1)
print(f"[{ts()}] Session opened")

# Get seed with retry
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
            print(f"[{ts()}] Cooldown — retrying...")
            continue

if seed is None:
    print(f"[{ts()}] Could not get seed")
    bus.shutdown()
    exit(1)

candidates = generate_candidates(seed)

parser = argparse.ArgumentParser()
parser.add_argument("--candidate", "-c", type=int, default=0)
parser.add_argument("--list", "-l", action="store_true")
args = parser.parse_args()

if args.list:
    print(f"Seed: [{seed.hex(' ')}]")
    print(f"\nAll candidates ({len(candidates)}):")
    for i, (n, k) in enumerate(candidates):
        print(f"  {i:2d}. {n}: [{k.hex(' ')}] ({len(k)} bytes)")
    bus.shutdown()
    exit(0)

cidx = min(args.candidate, len(candidates) - 1)
name, key = candidates[cidx]

print(f"\n[{ts()}] Candidate #{cidx}/{len(candidates)-1}: {name} = [{key.hex(' ')}] ({len(key)} bytes)")
print(f"[{ts()}] Sending: 0x27 0x06 + key")

r = send_recv([0x27, 0x06] + list(key), timeout=3.0)
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
        nrc_names = {0x12: "subFunctionNotSupported", 0x22: "conditionsNotCorrect", 0x24: "sequenceError", 0x33: "securityAccessDenied", 0x35: "invalidKey", 0x36: "exceededAttempts", 0x37: "timeDelayNotExpired"}
        print(f"[{ts()}] Result: NRC 0x{nrc:02X} ({nrc_names.get(nrc, 'unknown')})")
        result = f"REJECTED_0x{nrc:02X}"
    else:
        print(f"[{ts()}] Unexpected: {r.hex(' ')}")
        result = f"unexpected"
else:
    print(f"[{ts()}] TIMEOUT")
    result = "TIMEOUT"

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

print(f"\n[{ts()}] Logged (attempt #{len(attempts)}) — next: -c {cidx+1}")
bus.shutdown()