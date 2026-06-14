#!/usr/bin/env python3
"""Test if seeds change between sessions."""
import can
import time
from datetime import datetime

bus = can.interface.Bus(channel="can0", bustype="socketcan", bitrate=500000)

# Drain stale messages
for _ in range(50):
    bus.recv(0.01)

time.sleep(1.0)

def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def send_recv(data, tx_id=0x764, rx_id=0x746, timeout=3.0):
    uds = bytearray(data)
    req = bytearray([len(uds)] + list(uds) + [0x00] * (7 - len(uds)))
    bus.send(can.Message(arbitration_id=tx_id, data=req[:8], is_extended_id=False))
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

seeds = []
for attempt in range(5):
    # Drain and wait
    for _ in range(30):
        bus.recv(0.01)
    time.sleep(0.5)

    # Open session
    print(f"[{ts()}] Attempt {attempt+1}/5: Opening session...")
    r = send_recv([0x10, 0x80])
    if not r or r[0] != 0x50:
        print(f"[{ts()}]   FAILED to open session")
        continue
    print(f"[{ts()}]   Session opened")

    time.sleep(0.2)

    # Request seed
    print(f"[{ts()}]   Requesting seed...")
    r = send_recv([0x27, 0x07])
    if r and r[0] == 0x67:
        seed = r[2:]
        seed_hex = seed.hex(" ")
        seeds.append(seed)
        print(f"[{ts()}]   Seed: [{seed_hex}] ({len(seed)} bytes)")
    elif r and len(r) >= 3 and r[0] == 0x7F:
        print(f"[{ts()}]   DENIED: NRC 0x{r[2]:02X}")
        # Need key cycle
        break
    else:
        print(f"[{ts()}]   No seed: {r.hex(' ') if r else 'TIMEOUT'}")
        break

    time.sleep(1.0)

print(f"\n[{ts()}] === Results ===")
print(f"Seeds collected: {len(seeds)}")
for i, s in enumerate(seeds):
    print(f"  Seed {i+1}: {s.hex(' ')}")

if len(seeds) >= 2:
    unique = set(s.hex() for s in seeds)
    print(f"Unique seeds: {len(unique)}")
    if len(unique) == 1:
        print("*** ALL SEEDS IDENTICAL — Fixed lookup table! ***")
    elif len(unique) == len(seeds):
        print("*** ALL SEEDS DIFFERENT — Random/PRNG ***")
    else:
        print("*** SOME SEEDS REPEAT — Small lookup table ***")

bus.shutdown()