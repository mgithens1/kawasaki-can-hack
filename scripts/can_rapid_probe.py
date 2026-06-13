#!/usr/bin/env python3
"""Rapid multi-cycle read of key dynamic PIDs while engine is revving."""
import can, time

bus = can.interface.Bus(interface="socketcan", channel="can0", bitrate=500000)
print("CAN connected")

# Flush
for _ in range(30):
    bus.recv(0.01)

# Open session
init = bytearray([0x02, 0x10, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00])
bus.send(can.Message(arbitration_id=0x764, data=init, is_extended_id=False))
start = time.time()
while time.time() - start < 5.0:
    resp = bus.recv(1.0)
    if resp and resp.arbitration_id == 0x746:
        fd = bytes(resp.data)
        if (fd[0] & 0xF0) == 0x00:
            payload = fd[1:1 + (fd[0] & 0x0F)]
            if len(payload) >= 2 and payload[0] == 0x50:
                print("SESSION OPEN\n")
                break

def read_pid(pid, timeout=1.5):
    uds = bytearray([0x21, pid])
    req = bytearray([len(uds)] + list(uds) + [0x00] * (8 - 1 - len(uds)))
    bus.send(can.Message(arbitration_id=0x764, data=req[:8], is_extended_id=False))
    s = time.time()
    while time.time() - s < timeout:
        resp = bus.recv(0.5)
        if not resp or resp.arbitration_id != 0x746:
            continue
        fd = bytes(resp.data)
        pci = fd[0]
        if (pci & 0xF0) == 0x00:
            sf_len = pci & 0x0F
            if sf_len == 0:
                continue
            payload = fd[1:1 + sf_len]
            if len(payload) >= 3 and payload[0] == 0x7F and payload[1] == 0x21:
                return f"NRC 0x{payload[2]:02X}"
            if len(payload) >= 2 and payload[0] == 0x61 and payload[1] == pid:
                data = bytes(payload[2:])
                return data.hex(" ")
            return f"raw: {payload.hex(' ')}"
        elif (pci & 0xF0) == 0x10:
            total_len = ((pci & 0x0F) << 8) | fd[1]
            reassembled = bytearray(fd[2:8])
            fc = bytearray([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            bus.send(can.Message(arbitration_id=0x764, data=fc, is_extended_id=False))
            while len(reassembled) < total_len:
                cf = bus.recv(1.0)
                if cf and cf.arbitration_id == 0x746:
                    cfd = bytes(cf.data)
                    if (cfd[0] & 0xF0) == 0x20:
                        remaining = total_len - len(reassembled)
                        take = min(7, remaining)
                        reassembled.extend(cfd[1:1 + take])
            if len(reassembled) >= total_len:
                reassembled = reassembled[:total_len]
                data = bytes(reassembled[2:])
                return data.hex(" ")
            return "PARTIAL"
    return "TIMEOUT"

# Key PIDs to read rapidly
key_pids = [
    (0x04, "Load"),
    (0x05, "IAP"),
    (0x06, "Cool"),
    (0x07, "IAT"),
    (0x08, "Oil/MAP"),
    (0x09, "RPM"),
    (0x0A, "0x0A"),
    (0x0B, "Gear"),
    (0x0C, "Speed"),
    (0x0D, "SpeedD"),
    (0x44, "Hybrid44"),
    (0x45, "HybSt45"),
    (0x46, "HybDt46"),
    (0x47, "HybMd47"),
    (0x48, "HybDt48"),
    (0x49, "HybSt49"),
    (0x50, "Clutch"),
    (0x51, "Gear51"),
    (0x52, "TPS52"),
    (0xB4, "0xB4"),
]

def decode(pid, raw):
    parts = raw.split(" ") if " " in raw else [raw]
    try:
        vals = [int(x, 16) for x in parts]
    except:
        return ""
    if pid == 0x09 and len(vals) == 2:
        return f"{(vals[0]<<8|vals[1])//4} RPM"
    if pid in (0x06, 0x07) and len(vals) == 1:
        return f"{vals[0]-40}°C"
    if pid == 0x08 and len(vals) == 1:
        return f"{vals[0]-40}°C or {vals[0]*4*0.136:.1f}kPa"
    if pid == 0x05 and len(vals) == 1:
        return f"{vals[0]*4*0.136:.1f} kPa"
    if pid == 0x04 and len(vals) == 1:
        return f"{vals[0]*100/255:.1f}%"
    if pid == 0x0A and len(vals) == 2:
        return f"{(vals[0]<<8|vals[1])}"
    if pid == 0x0C and len(vals) == 1:
        return f"{vals[0]} km/h"
    if pid == 0x0D and len(vals) == 2:
        return f"{(vals[0]<<8|vals[1])//2} kph"
    return ""

print("Reading 8 rapid cycles — REV THE ENGINE!")
hdr = f"{'#':>2}  {'PID':>4}  {'Label':8}  {'Raw':20}  {'Decoded':>18}"
print(hdr)
print("-" * len(hdr))

for cycle in range(8):
    print(f"\n--- Cycle {cycle+1} ---")
    for pid, label in key_pids:
        raw = read_pid(pid)
        d = decode(pid, raw)
        print(f"  0x{pid:02X}  {label:8}  {raw:20}  {d}")
        bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
        time.sleep(0.05)
    time.sleep(0.3)

bus.shutdown()
print("\nDone!")