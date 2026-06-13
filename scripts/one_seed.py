#!/usr/bin/env python3
"""Single seed request - run after key cycle. Saves seed to file."""
import can
import time
from datetime import datetime
import json
import os

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

# Open session
print(f"[{ts()}] Opening session...")
r = send_recv([0x10, 0x80])
if not r or r[0] != 0x50:
    print(f"[{ts()}] FAILED to open session: {r.hex(' ') if r else 'TIMEOUT'}")
    bus.shutdown()
    exit(1)
print(f"[{ts()}] Session opened")

time.sleep(0.2)

# Request seed
print(f"[{ts()}] Requesting seed at level 0x07...")
r = send_recv([0x27, 0x07])
if r and r[0] == 0x67:
    seed = r[2:]
    print(f"[{ts()}] *** SEED: [{seed.hex(' ')}] ({len(seed)} bytes) ***")

    # Save to file
    results_file = os.path.join(os.path.dirname(__file__), "..", "seed_log.json")
    results = []
    if os.path.exists(results_file):
        with open(results_file, "r") as f:
            try:
                results = json.load(f)
            except json.JSONDecodeError:
                results = []

    results.append({
        "timestamp": datetime.now().isoformat(),
        "seed": list(seed),
        "seed_hex": seed.hex(" "),
        "seed_length": len(seed),
        "level": "0x07"
    })

    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"[{ts()}] Seed saved to seed_log.json (total: {len(results)})")

elif r and len(r) >= 3 and r[0] == 0x7F:
    print(f"[{ts()}] DENIED: NRC 0x{r[2]:02X}")
else:
    print(f"[{ts()}] Unexpected: {r.hex(' ') if r else 'TIMEOUT'}")

bus.shutdown()
print(f"[{ts()}] Done")