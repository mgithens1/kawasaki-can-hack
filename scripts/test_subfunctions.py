#!/usr/bin/env python3
"""Quick test: try different SecurityAccess key sub-functions."""
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
        # Multi-frame
        total_len = len(uds)
        ff = bytearray([0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + list(uds[:6]))
        ff += bytearray([0x00] * (8 - len(ff)))
        bus.send(can.Message(arbitration_id=tx_id, data=ff, is_extended_id=False))
        # Wait for flow control
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
        # Send consecutive frames
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

# Get seed
print(f"[{ts()}] Requesting seed...")
r = send_recv([0x27, 0x07])
if not r or r[0] != 0x67:
    print(f"[{ts()}] Seed failed: {r.hex(' ') if r else 'TIMEOUT'}")
    bus.shutdown()
    exit(1)

seed = r[2:]
print(f"[{ts()}] Seed: [{seed.hex(' ')}] ({len(seed)} bytes)")

# Now try sending the seed BACK as the key at different sub-function levels
# This tests whether the ECU accepts different SecurityAccess formats
test_keys = [
    # (sub_function, key_data, description)
    (0x01, seed, "send seed back at 0x01"),
    (0x02, seed, "send seed back at 0x02"),
    (0x06, seed, "send seed back at 0x06"),
    (0x08, seed, "send seed back at 0x08 (standard)"),
]

for sub_fn, key, desc in test_keys:
    print(f"\n[{ts()}] Trying: 0x27 0x{sub_fn:02X} + seed = [{desc}]")
    payload = [0x27, sub_fn] + list(key)
    r = send_recv(payload, timeout=2.0)
    if r:
        if r[0] == 0x67:
            print(f"[{ts()}] *** GRANTED at sub-function 0x{sub_fn:02X}! ***")
        elif len(r) >= 3 and r[0] == 0x7F:
            nrc = r[2]
            nrc_names = {0x12: "subFunctionNotSupported", 0x24: "sequenceError", 0x33: "accessDenied", 0x35: "invalidKey", 0x36: "exceededAttempts", 0x37: "timeDelay"}
            print(f"[{ts()}]   NRC 0x{nrc:02X} ({nrc_names.get(nrc, 'unknown')})")
        else:
            print(f"[{ts()}]   Response: {r.hex(' ')}")
    else:
        print(f"[{ts()}]   TIMEOUT")

bus.shutdown()
print(f"\n[{ts()}] Done")