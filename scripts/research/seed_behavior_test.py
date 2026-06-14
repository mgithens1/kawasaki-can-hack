#!/usr/bin/env python3
"""Quick seed behavior test - safe, no key attempts."""
import can
import time
from datetime import datetime

bus = can.interface.Bus(channel="can0", bustype="socketcan", bitrate=500000)
time.sleep(0.5)

def drain():
    for _ in range(30):
        bus.recv(0.01)

def send_recv(data, timeout=2.0):
    uds = bytearray(data)
    req = bytearray([len(uds)] + list(uds) + [0x00] * (7 - len(uds)))
    bus.send(can.Message(arbitration_id=0x764, data=req[:8], is_extended_id=False))
    start = time.time()
    while time.time() - start < timeout:
        r = bus.recv(0.5)
        if not r or r.arbitration_id != 0x746:
            continue
        fd = bytes(r.data)
        pci = fd[0]
        if (pci & 0xF0) == 0x00:
            sf = pci & 0x0F
            if sf == 0:
                continue
            return bytes(fd[1:1+sf])
    return None

def open_session():
    drain()
    r = send_recv([0x10, 0x80])
    return r and len(r) >= 2 and r[0] == 0x50

def request_seed():
    r = send_recv([0x27, 0x07])
    if r and r[0] == 0x67:
        seed = r[2:]
        return seed, f"{len(seed)}-byte seed: {seed.hex(' ')}"
    elif r and len(r) >= 3 and r[0] == 0x7F:
        nrc = r[2]
        return None, f"DENIED: NRC 0x{nrc:02X}"
    elif r:
        return None, f"unexpected: {r.hex(' ')}"
    else:
        return None, "TIMEOUT"

def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

# Test 1: Single session, request seed twice
print(f"[{ts()}] === Test 1: Two seeds in same session ===")
print(f"[{ts()}] Opening session...")
if not open_session():
    print("FAILED to open session")
    bus.shutdown()
    exit()

seed1, desc1 = request_seed()
print(f"[{ts()}] Seed #1: {desc1}")

time.sleep(1.0)
seed2, desc2 = request_seed()
print(f"[{ts()}] Seed #2 (same session, 1s delay): {desc2}")

if seed1 and seed2:
    if seed1 == seed2:
        print(f"[{ts()}] *** SAME SEED in same session - key is fixed per session! ***")
    else:
        print(f"[{ts()}] *** DIFFERENT seeds in same session - seeds rotate! ***")

# Test 2: New session after 3s
print(f"\n[{ts()}] === Test 2: New session after 3s delay ===")
time.sleep(3.0)
drain()
if not open_session():
    print("FAILED to re-open session after delay")
else:
    seed3, desc3 = request_seed()
    print(f"[{ts()}] Seed #3 (new session, 3s wait): {desc3}")

# Test 3: Rapid fire in same session
print(f"\n[{ts()}] === Test 3: Rapid seed requests ===")
drain()
if not open_session():
    print("FAILED to open session for rapid test")
else:
    for i in range(5):
        seed, desc = request_seed()
        print(f"[{ts()}] Rapid #{i+1}: {desc}")
        if seed is None:
            break
        time.sleep(0.1)

bus.shutdown()
print(f"\n[{ts()}] Done")