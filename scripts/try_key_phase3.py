#!/usr/bin/env python3
"""Phase 3 key attempts - CRC, VW-style, S-box, and other automotive algorithms."""
import can
import time
import json
import os
import argparse
import struct
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

# CRC implementations
def crc16_ccitt(data, init=0xFFFF):
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc

def crc16_arc(data, init=0x0000):
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF

def crc8(data, poly=0x07, init=0x00):
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc

# AES S-box
SBOX = [
    0x63,0x7C,0x77,0x7B,0xF2,0x6B,0x6F,0xC5,0x30,0x01,0x67,0x2B,0xFE,0xD7,0xAB,0x76,
    0xCA,0x82,0xC9,0x7D,0xFA,0x59,0x47,0xF0,0xAD,0xD4,0xA2,0xAF,0x9C,0xA4,0x72,0xC0,
    0xB7,0xFD,0x93,0x26,0x36,0x3F,0xF7,0xCC,0x34,0xA5,0xE5,0xF1,0x71,0xD8,0x31,0x15,
    0x04,0xC7,0x23,0xC3,0x18,0x96,0x05,0x9A,0x07,0x12,0x80,0xE2,0xEB,0x27,0xB2,0x75,
    0x09,0x83,0x2C,0x1A,0x1B,0x6E,0x5A,0xA0,0x52,0x3B,0xD6,0xB3,0x29,0xE3,0x2F,0x84,
    0x53,0xD1,0x00,0xED,0x20,0xFC,0xB1,0x5B,0x6A,0xCB,0xBE,0x39,0x4A,0x4C,0x58,0xCF,
    0xD0,0xEF,0xAA,0xFB,0x43,0x4D,0x33,0x85,0x45,0xF9,0x02,0x7F,0x50,0x3C,0x9F,0xA8,
    0x51,0xA3,0x40,0x8F,0x92,0x9D,0x38,0xF5,0xBC,0xB6,0xDA,0x21,0x10,0xFF,0xF3,0xD2,
    0xCD,0x0C,0x13,0xEC,0x5F,0x97,0x44,0x17,0xC4,0xA7,0x7E,0x3D,0x64,0x5D,0x19,0x73,
    0x60,0x81,0x4F,0xDC,0x22,0x2A,0x90,0x88,0x46,0xEE,0xB8,0x14,0xDE,0x5E,0x0B,0xDB,
    0xE0,0x32,0x3A,0x0A,0x49,0x06,0x24,0x5C,0xC2,0xD3,0xAC,0x62,0x91,0x95,0xE4,0x79,
    0xE7,0xC8,0x37,0x6D,0x8D,0xD5,0x4E,0xA9,0x6C,0x56,0xF4,0xEA,0x65,0x7A,0xAE,0x08,
    0xBA,0x78,0x25,0x2E,0x1C,0xA6,0xB4,0xC6,0xE8,0xDD,0x74,0x1F,0x4B,0xBD,0x8B,0x8A,
    0x70,0x3E,0xB5,0x66,0x48,0x03,0xF6,0x0E,0x61,0x35,0x57,0xB9,0x86,0xC1,0x1D,0x9E,
    0xE1,0xF8,0x98,0x11,0x69,0xD9,0x8E,0x94,0x9B,0x1E,0x87,0xE9,0xCE,0x55,0x28,0xDF,
    0x8C,0xA1,0x89,0x0D,0xBF,0xE6,0x42,0x68,0x41,0x99,0x2D,0x0F,0xB0,0x54,0xBB,0x16,
]

def generate_candidates(seed):
    """Generate phase 3 candidates - automotive algorithms."""
    s = list(seed)
    s5 = list(seed[:5])  # First 5 bytes (0x34 is likely metadata)
    candidates = []

    # === CRC-based derivations ===
    
    # 1. CRC-16/CCITT on 5-byte seed, key = CRC result + XOR mix
    crc = crc16_ccitt(s5)
    k = bytes([crc >> 8, crc & 0xFF,
               s5[0] ^ s5[2] ^ s5[4],
               s5[1] ^ s5[3],
               0x34, 0x34])
    candidates.append(("crc16_ccitt_5b", k))
    
    # Same but on 6-byte seed
    crc = crc16_ccitt(s)
    k = bytes([crc >> 8, crc & 0xFF,
               s[0] ^ s[2] ^ s[4],
               s[1] ^ s[3],
               s[5] ^ (crc & 0xFF), 0x34])
    candidates.append(("crc16_ccitt_6b", k))
    
    # 2. CRC-16/ARC on 5-byte seed
    crc = crc16_arc(s5)
    k = bytes([crc >> 8, crc & 0xFF,
               s5[0] ^ s5[2] ^ s5[4],
               s5[1] ^ s5[3],
               0x34, 0x34])
    candidates.append(("crc16_arc_5b", k))
    
    # 3. CRC-16/CCITT result as full key (6 bytes padded)
    crc = crc16_ccitt(s5)
    k = bytes([s5[0], s5[1], crc >> 8, crc & 0xFF, 0x34, 0x34])
    candidates.append(("crc16_ccitt_embed", k))
    
    # === VW-style algorithms ===
    
    # 4. VW-style: XOR 0x5A + nibble swap + additive with next byte
    k = bytearray(5)
    for i in range(5):
        k[i] = ((s5[i] ^ 0x5A) + (s5[(i+1) % 5] >> 4)) & 0xFF
    # Nibble swap on even positions
    for i in [0, 2, 4]:
        k[i] = ((k[i] >> 4) | ((k[i] & 0x0F) << 4)) & 0xFF
    candidates.append(("vw_xor5a_nibswap", bytes(k) + b'\x34'))
    
    # 5. VW-style variant: XOR 0x99 instead of 0x5A
    k = bytearray(5)
    for i in range(5):
        k[i] = ((s5[i] ^ 0x99) + (s5[(i+1) % 5] >> 4)) & 0xFF
    for i in [0, 2, 4]:
        k[i] = ((k[i] >> 4) | ((k[i] & 0x0F) << 4)) & 0xFF
    candidates.append(("vw_xor99_nibswap", bytes(k) + b'\x34'))
    
    # === S-box based ===
    
    # 6. AES S-box substitution on each byte
    k = bytes([SBOX[b] for b in s5]) + b'\x34'
    candidates.append(("aes_sbox_5b_34", k))
    
    # S-box on 6 bytes
    k = bytes([SBOX[b] for b in s])
    candidates.append(("aes_sbox_6b", k))
    
    # 7. S-box(XOR with neighbor) 
    k = bytes([SBOX[(s5[i] ^ s5[(i+1)%5]) & 0xFF] for i in range(5)]) + b'\x34'
    candidates.append(("sbox_xor_neighbor", k))
    
    # S-box then XOR with original
    k = bytes([(SBOX[b] ^ s5[i]) & 0xFF for i, b in enumerate(s5)]) + b'\x34'
    candidates.append(("sbox_xor_orig", k))
    
    # === LCG / multiplicative ===
    
    # 8. Simple LCG seeded from first 2 bytes
    state = (s5[0] << 8) | s5[1]
    k = bytearray(6)
    for i in range(6):
        state = (state * 0x41C6 + 0x3039) & 0xFFFF  # Common glibc LCG constants
        k[i] = (state >> 8) & 0xFF
    candidates.append(("lcg_glibc", bytes(k)))
    
    # LCG with different constants (MINSTD)
    state = (s5[0] << 8) | s5[1]
    k = bytearray(6)
    for i in range(6):
        state = (state * 16807 + 0) & 0x7FFFFFFF
        k[i] = (state >> 19) & 0xFF  # Take bits 19-26
    candidates.append(("lcg_minstd", bytes(k)))
    
    # === Checksum-based ===
    
    # 9. Sum of all bytes mod 256 as each key byte (shifted)
    total = sum(s5) & 0xFF
    k = bytes([(s5[i] + total) & 0xFF for i in range(5)]) + b'\x34'
    candidates.append(("sum_shift_5b", k))
    
    # XOR all bytes, then XOR each byte with that
    xor_all = 0
    for b in s5:
        xor_all ^= b
    k = bytes([(b ^ xor_all) & 0xFF for b in s5]) + b'\x34'
    candidates.append(("xor_all_mix", k))
    
    # 10. Double XOR: first pass left-to-right, second pass right-to-left
    k = bytearray(5)
    k[0] = s5[0]
    for i in range(1, 5):
        k[i] = s5[i] ^ k[i-1]
    # Second pass
    for i in range(3, -1, -1):
        k[i] = k[i] ^ k[i+1]
    candidates.append(("double_xor_pass", bytes(k) + b'\x34'))
    
    # === Key might be only 4 bytes (CRC-32 truncated) ===
    # CRC-32 on 5-byte seed, take 4 bytes, plus 0x34 0x34
    import zlib
    crc32 = zlib.crc32(bytes(s5)) & 0xFFFFFFFF
    k = struct.pack(">I", crc32) + b'\x34\x34'
    candidates.append(("crc32_4b_3434", k))
    
    # CRC-32, take low 2 bytes, mix with seed
    k = bytes([s5[0], s5[1], (crc32 >> 24) & 0xFF, (crc32 >> 16) & 0xFF, 0x34, 0x34])
    candidates.append(("crc32_mix", k))
    
    # === Try the 0x34 byte differently ===
    # Maybe key is 5 bytes derived from first 5, and 0x34 is echoed back
    # S-box on first 5 bytes + 0x34 as 6th byte (already tried as "aes_sbox_5b_34")
    # But also: what if key = seed[:5] with S-box applied, 6th byte = derived separately
    crc8_val = crc8(s5, poly=0x07, init=0xFF)
    k = bytes([SBOX[b] for b in s5]) + bytes([crc8_val])
    candidates.append(("sbox_crc8", k))
    
    # CRC-8 of 5-byte seed as each byte XOR'd
    c = crc8(s5, poly=0x07, init=0x00)
    k = bytes([(b ^ c) & 0xFF for b in s5]) + bytes([c])
    candidates.append(("seed_xor_crc8", k))
    
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
    "phase": 3,
})

with open(LOG_FILE, "w") as f:
    json.dump(attempts, f, indent=2)

print(f"\n[{ts()}] Logged (attempt #{len(attempts)}, phase 3) — next: -c {cidx+1}")
bus.shutdown()