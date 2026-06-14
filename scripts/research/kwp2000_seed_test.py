#!/usr/bin/env python3
"""Seed-key testing and routine 0x01 probing."""
import can, time

bus = can.interface.Bus(interface="socketcan", channel="can0", bitrate=500000)
print("CAN connected")
for _ in range(30): bus.recv(0.01)

def open_session():
    init = bytearray([0x02, 0x10, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00])
    bus.send(can.Message(arbitration_id=0x764, data=init, is_extended_id=False))
    s = time.time()
    while time.time() - s < 5:
        r = bus.recv(1.0)
        if r and r.arbitration_id == 0x746:
            fd = bytes(r.data)
            if (fd[0] & 0xF0) == 0x00:
                p = fd[1:1+(fd[0]&0x0F)]
                if len(p) >= 2 and p[0] == 0x50:
                    return True
    return False

def send_recv(data, timeout=3.0):
    uds = bytearray(data)
    req = bytearray([len(uds)] + list(uds) + [0x00]*(8-1-len(uds)))
    bus.send(can.Message(arbitration_id=0x764, data=req[:8], is_extended_id=False))
    s = time.time()
    while time.time() - s < timeout:
        r = bus.recv(0.5)
        if not r or r.arbitration_id != 0x746: continue
        fd = bytes(r.data)
        pci = fd[0]
        if (pci & 0xF0) == 0x00:
            sf = pci & 0x0F
            if sf == 0: continue
            return bytes(fd[1:1+sf])
        elif (pci & 0xF0) == 0x10:
            total = ((pci & 0x0F) << 8) | fd[1]
            reasm = bytearray(fd[2:8])
            fc = bytearray([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            bus.send(can.Message(arbitration_id=0x764, data=fc, is_extended_id=False))
            while len(reasm) < total:
                cf = bus.recv(1.0)
                if cf and cf.arbitration_id == 0x746:
                    cfd = bytes(cf.data)
                    if (cfd[0] & 0xF0) == 0x20:
                        rem = total - len(reasm)
                        reasm.extend(cfd[1:1+min(7,rem)])
            if len(reasm) >= total:
                return bytes(reasm[:total])
    return None

def read_pid(pid):
    uds = bytearray([0x21, pid])
    req = bytearray([len(uds)] + list(uds) + [0x00]*(8-1-len(uds)))
    bus.send(can.Message(arbitration_id=0x764, data=req[:8], is_extended_id=False))
    s = time.time()
    while time.time() - s < 1.5:
        r = bus.recv(0.5)
        if not r or r.arbitration_id != 0x746: continue
        fd = bytes(r.data)
        pci = fd[0]
        if (pci & 0xF0) == 0x00:
            sf = pci & 0x0F
            if sf == 0: continue
            payload = fd[1:1+sf]
            if len(payload) >= 3 and payload[0] == 0x7F:
                return "NRC 0x{:02X}".format(payload[2])
            if len(payload) >= 2 and payload[0] == 0x61:
                return payload[2:].hex(" ")
            return "raw: " + bytes(payload).hex(" ")
    return "TIMEOUT"

def fresh_session():
    for _ in range(20): bus.recv(0.01)
    return open_session()

# ==========================================
# PART 1: Fresh seeds
# ==========================================
print("\n=== PART 1: Fresh Seed Requests ===")
for i in range(3):
    if not fresh_session():
        print("  Failed to open session")
        continue
    r = send_recv([0x27, 0x07])
    if r and r[0] == 0x67:
        seed = r[2:]
        print("  Seed {}: {} ({} bytes)".format(i+1, seed.hex(" "), len(seed)))
    elif r and len(r) >= 3 and r[0] == 0x7F:
        print("  Seed {}: NRC 0x{:02X}".format(i+1, r[2]))
    else:
        print("  Seed {}: {}".format(i+1, r.hex(" ") if r else "TIMEOUT"))
    time.sleep(0.5)

# ==========================================
# PART 2: Key attempts
# ==========================================
print("\n=== PART 2: Key Attempts ===")
known_keys_5 = [
    [0x63, 0x27, 0x53, 0x67, 0x42],
    [0x30, 0x20, 0x39, 0x48, 0x74],
    [0x58, 0x49, 0x57, 0x69, 0x84],
]

# Try each key with fresh session + seed
for ki, key5 in enumerate(known_keys_5):
    if not fresh_session():
        print("  Failed to open session for key {}".format(ki+1))
        continue
    
    # Get seed
    r = send_recv([0x27, 0x07])
    if not r or r[0] != 0x67:
        print("  Key pair {}: Could not get seed".format(ki+1))
        continue
    seed = r[2:]
    print("  Key pair {}: seed={}".format(ki+1, seed.hex(" ")))
    
    # Try 5-byte key on level 0x08
    r2 = send_recv([0x27, 0x08] + key5, timeout=2.0)
    if r2:
        if len(r2) >= 3 and r2[0] == 0x7F:
            print("    Level 0x08, 5-byte key: NRC 0x{:02X}".format(r2[2]))
        elif len(r2) >= 2 and r2[0] == 0x67:
            print("    Level 0x08, 5-byte key: ACCEPTED! {}".format(r2.hex(" ")))
        else:
            print("    Level 0x08, 5-byte key: {}".format(r2.hex(" ")))
    else:
        print("    Level 0x08, 5-byte key: TIMEOUT")
    
    time.sleep(0.3)

    # Try 6-byte key (5-byte + 0x00 pad) on level 0x08
    if not fresh_session():
        continue
    r = send_recv([0x27, 0x07])
    if not r or r[0] != 0x67:
        continue
    seed = r[2:]
    
    r2 = send_recv([0x27, 0x08] + key5 + [0x00], timeout=2.0)
    if r2:
        if len(r2) >= 3 and r2[0] == 0x7F:
            print("    Level 0x08, 5+1 pad: NRC 0x{:02X}".format(r2[2]))
        elif len(r2) >= 2 and r2[0] == 0x67:
            print("    Level 0x08, 5+1 pad: ACCEPTED!")
        else:
            print("    Level 0x08, 5+1 pad: {}".format(r2.hex(" ")))
    else:
        print("    Level 0x08, 5+1 pad: TIMEOUT")
    time.sleep(0.3)

# Try some algorithm-based keys
print("\n  Algorithm-based key attempts:")
for name, key_fn in [
    ("XOR 0x50", lambda s: [(b ^ 0x50) & 0xFF for b in s]),
    ("XOR 0xAA", lambda s: [(b ^ 0xAA) & 0xFF for b in s]),
    ("NOT (complement)", lambda s: [(0xFF - b) & 0xFF for b in s]),
    ("+0x28 mod 256", lambda s: [(b + 0x28) & 0xFF for b in s]),
    ("+0x50 mod 256", lambda s: [(b + 0x50) & 0xFF for b in s]),
    ("byte swap", lambda s: list(reversed(s))),
    ("identity (seed=key)", lambda s: list(s)),
]:
    if not fresh_session():
        continue
    r = send_recv([0x27, 0x07])
    if not r or r[0] != 0x67:
        print("    {}: Could not get seed".format(name))
        continue
    seed = r[2:]
    key = key_fn(seed)
    r2 = send_recv([0x27, 0x08] + key, timeout=2.0)
    if r2:
        if len(r2) >= 3 and r2[0] == 0x7F:
            print("    {}: NRC 0x{:02X}".format(name, r2[2]))
        elif len(r2) >= 2 and r2[0] == 0x67:
            print("    {}: ACCEPTED!!!".format(name))
        else:
            print("    {}: {}".format(name, r2.hex(" ")))
    else:
        print("    {}: TIMEOUT".format(name))
    time.sleep(0.3)

# ==========================================
# PART 3: Start Routine 0x01 and observe
# ==========================================
print("\n=== PART 3: Start Routine 0x01 ===")
if not fresh_session():
    print("  Failed to open session")
else:
    # Baseline sensors
    baseline = {}
    pids = [(0x04,"Load"), (0x05,"IAP"), (0x06,"Cool"), (0x07,"IAT"),
            (0x09,"RPM"), (0x0B,"Gear"), (0x44,"Hyb44"), (0x45,"Hyb45"),
            (0x47,"HybMd"), (0x50,"Clutch"), (0x76,"Voltage")]
    print("  Baseline (before routine):")
    for pid, label in pids:
        raw = read_pid(pid)
        baseline[pid] = raw
        print("    0x{:02X} {:10s} {}".format(pid, label, raw))
        bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
        time.sleep(0.05)

    # Start routine
    print("  Starting routine 0x01...")
    r = send_recv([0x13, 0x01], timeout=5.0)
    if r:
        if len(r) >= 2 and r[0] == 0x53:
            print("  Routine 0x01 ACCEPTED: {}".format(r.hex(" ")))
        elif len(r) >= 3 and r[0] == 0x7F:
            nrc = r[2]
            names = {0x12: "Not Supported", 0x22: "Conditions Not Met", 0x33: "Security Access"}
            print("  Routine 0x01 REJECTED: {}".format(names.get(nrc, "NRC 0x{:02X}".format(nrc))))
        else:
            print("  Routine 0x01 response: {}".format(r.hex(" ")))
    else:
        print("  Routine 0x01: TIMEOUT")

    # Read sensors after
    print("  After routine:")
    for pid, label in pids:
        raw = read_pid(pid)
        changed = " **CHANGED**" if baseline.get(pid) != raw else ""
        print("    0x{:02X} {:10s} {}{}".format(pid, label, raw, changed))
        bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
        time.sleep(0.05)

    time.sleep(3)
    print("  After 3s wait:")
    for pid, label in pids:
        raw = read_pid(pid)
        changed = " **CHANGED**" if baseline.get(pid) != raw else ""
        print("    0x{:02X} {:10s} {}{}".format(pid, label, raw, changed))
        bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
        time.sleep(0.05)

print("\nDone!")
bus.shutdown()