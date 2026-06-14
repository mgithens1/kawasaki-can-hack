#!/usr/bin/env python3
"""Test: can we request another seed after a wrong key?"""
import can
import time
from datetime import datetime

bus = can.interface.Bus(channel="can0", bustype="socketcan", bitrate=500000)
for _ in range(50):
    bus.recv(0.01)
time.sleep(0.5)

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

def parse_response(r):
    if r is None:
        return "TIMEOUT"
    if r[0] == 0x67:
        return f"POSITIVE: {r.hex(' ')}"
    if len(r) >= 3 and r[0] == 0x7F:
        nrc_names = {0x12: "subFnNotSupported", 0x22: "conditionsNotCorrect", 0x24: "sequenceError", 0x33: "accessDenied", 0x35: "invalidKey", 0x36: "exceededAttempts", 0x37: "timeDelay"}
        return f"NRC 0x{r[2]:02X} ({nrc_names.get(r[2], 'unknown')})"
    return f"RAW: {r.hex(' ')}"

# Test: Can we get multiple seed+key attempts per session?
print(f"[{ts()}] === Test: Multiple attempts per session ===")

# Step 1: Open session
print(f"[{ts()}] Opening session...")
r = send_recv([0x10, 0x80])
print(f"[{ts()}] Session: {parse_response(r)}")
if not r or r[0] != 0x50:
    bus.shutdown()
    exit(1)

# Step 2: Get seed
print(f"\n[{ts()}] Requesting seed #1...")
r = send_recv([0x27, 0x07])
seed1 = None
if r and r[0] == 0x67:
    seed1 = r[2:]
    print(f"[{ts()}] Seed #1: [{seed1.hex(' ')}]")
elif r:
    print(f"[{ts()}] Seed #1: {parse_response(r)}")
    bus.shutdown()
    exit(1)

# Step 3: Send wrong key (0x27 0x06)
print(f"\n[{ts()}] Sending wrong key (all zeros)...")
r = send_recv([0x27, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], timeout=2.0)
print(f"[{ts()}] Wrong key result: {parse_response(r)}")

# Step 4: Try requesting another seed
time.sleep(0.2)
print(f"\n[{ts()}] Requesting seed #2 (after wrong key)...")
r = send_recv([0x27, 0x07])
if r:
    if r[0] == 0x67:
        seed2 = r[2:]
        print(f"[{ts()}] Seed #2: [{seed2.hex(' ')}]")
        print(f"[{ts()}] *** CAN GET ANOTHER SEED AFTER WRONG KEY! ***")
    else:
        print(f"[{ts()}] Seed #2: {parse_response(r)}")
else:
    print(f"[{ts()}] Seed #2: TIMEOUT")

# Step 5: Send another wrong key
if r and r[0] == 0x67:
    print(f"\n[{ts()}] Sending second wrong key (all 0xFF)...")
    r = send_recv([0x27, 0x06, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], timeout=2.0)
    print(f"[{ts()}] Second wrong key: {parse_response(r)}")

    # Step 6: Try requesting yet another seed
    time.sleep(0.2)
    print(f"\n[{ts()}] Requesting seed #3 (after two wrong keys)...")
    r = send_recv([0x27, 0x07])
    print(f"[{ts()}] Seed #3: {parse_response(r)}")

bus.shutdown()
print(f"\n[{ts()}] Done")