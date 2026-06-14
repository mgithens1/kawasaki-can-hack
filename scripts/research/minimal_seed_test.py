#!/usr/bin/env python3
"""Minimal seed test - one session, one seed request, no key attempts."""
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
    print(f"[{ts()}] TX: 0x{tx_id:03X} [{req.hex(' ')}]")
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
                payload = bytes(fd[1:1+sf])
                print(f"[{ts()}] RX: 0x{rx_id:03X} [{fd.hex(' ')}] -> payload [{payload.hex(' ')}]")
                return payload
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
                payload = bytes(reasm[:total])
                print(f"[{ts()}] RX: 0x{rx_id:03X} (multi-frame) -> payload [{payload.hex(' ')}]")
                return payload
        # Show other CAN traffic for debugging
        elif msg.arbitration_id not in (0x764,):
            pass  # skip noise
    print(f"[{ts()}] RX: TIMEOUT")
    return None

# Step 1: Open session
print(f"[{ts()}] === Opening session (0x10 0x80) ===")
r = send_recv([0x10, 0x80])
if r:
    if r[0] == 0x50:
        print(f"[{ts()}] Session opened OK")
    elif r[0] == 0x7F and len(r) >= 3:
        print(f"[{ts()}] Session REJECTED: NRC 0x{r[2]:02X}")
    else:
        print(f"[{ts()}] Session response: {r.hex(' ')}")

time.sleep(0.5)

# Step 2: Request seed at level 0x07
print(f"\n[{ts()}] === Requesting seed (0x27 0x07) ===")
r = send_recv([0x27, 0x07])
if r:
    if r[0] == 0x67:
        seed = r[2:]
        print(f"[{ts()}] *** SEED RECEIVED: [{seed.hex(' ')}] ({len(seed)} bytes) ***")
    elif r[0] == 0x7F and len(r) >= 3:
        nrc = r[2]
        nrc_names = {0x12: "subFunctionNotSupported", 0x22: "conditionsNotCorrect", 0x24: "requestSequenceError", 0x33: "securityAccessDenied", 0x35: "invalidKey", 0x36: "exceededAttempts", 0x37: "requiredTimeDelayNotExpired"}
        print(f"[{ts()}] Seed DENIED: NRC 0x{nrc:02X} ({nrc_names.get(nrc, 'unknown')})")
    else:
        print(f"[{ts()}] Unexpected: {r.hex(' ')}")

# Step 3: Try again with 2s delay
print(f"\n[{ts()}] === Waiting 2s, then requesting seed again ===")
time.sleep(2.0)
r = send_recv([0x27, 0x07])
if r:
    if r[0] == 0x67:
        seed = r[2:]
        print(f"[{ts()}] *** SEED #2: [{seed.hex(' ')}] ({len(seed)} bytes) ***")
    elif r[0] == 0x7F and len(r) >= 3:
        nrc = r[2]
        print(f"[{ts()}] Seed #2 DENIED: NRC 0x{nrc:02X}")
    else:
        print(f"[{ts()}] Unexpected: {r.hex(' ')}")

bus.shutdown()
print(f"\n[{ts()}] Done")