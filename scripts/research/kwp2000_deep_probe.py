#!/usr/bin/env python3
"""KWP2000 Deep Probe — more service IDs and sub-functions."""
import can, time

bus = can.interface.Bus(interface="socketcan", channel="can0", bitrate=500000)
print("CAN connected")

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

def send_request(service, data_bytes, timeout=2.0):
    uds = bytearray([service] + list(data_bytes))
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
            if sf_len == 0: continue
            return ("OK", bytes(fd[1:1 + sf_len]))
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
                return ("OK", bytes(reassembled[:total_len]))
            return ("PARTIAL", len(reassembled))
    return ("TIMEOUT", None)

def hex_ascii(data):
    if data is None: return "None"
    h = data.hex(" ")
    a = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"{h}  |{a}|"

print("=" * 78)
print("  KWP2000 Deep Probe — Extended IDs and Services")
print("=" * 78)

# 1. More 0x1A sub-IDs: 0x86-0x9F
print("\n--- Service 0x1A: Extended ECU IDs (0x86-0x9F) ---")
for i in range(0x86, 0xA0):
    status, data = send_request(0x1A, [i])
    if data and len(data) >= 3 and data[0] == 0x7F and data[1] == 0x1A:
        nrc = data[2]
        if nrc == 0x12:
            pass  # skip "not supported" silently
        else:
            print(f"  0x{i:02X}  →  NRC 0x{nrc:02X}")
    elif data:
        print(f"  0x{i:02X}  →  {hex_ascii(data)}")
    else:
        print(f"  0x{i:02X}  →  TIMEOUT")
    bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
    time.sleep(0.03)

# 2. Service 0x1A with local IDs 0x00-0x1F (we know some from service 0x21, try via 0x1A)
print("\n--- Service 0x1A: Low IDs (0x00-0x1F) ---")
for i in range(0x00, 0x20):
    status, data = send_request(0x1A, [i])
    if data and len(data) >= 3 and data[0] == 0x7F and data[1] == 0x1A:
        nrc = data[2]
        if nrc != 0x12:
            print(f"  0x{i:02X}  →  NRC 0x{nrc:02X}")
    elif data:
        print(f"  0x{i:02X}  →  {hex_ascii(data)}")
    else:
        pass  # skip timeout silently for low IDs
    bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
    time.sleep(0.03)

# 3. Service 0x21 with high local IDs (0xA0-0xBF)
print("\n--- Service 0x21: High Local IDs (0xA0-0xBF) ---")
for i in range(0xA0, 0xC0):
    status, data = send_request(0x21, [i])
    if data and len(data) >= 3 and data[0] == 0x7F and data[1] == 0x21:
        nrc = data[2]
        if nrc != 0x12:
            print(f"  0x{i:02X}  →  NRC 0x{nrc:02X}")
    elif data:
        print(f"  0x{i:02X}  →  {hex_ascii(data)}")
    else:
        pass
    bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
    time.sleep(0.03)

# 4. Service 0x21 with local IDs 0x70-0x9F (gap coverage)
print("\n--- Service 0x21: Gap IDs (0x70-0x9F) ---")
for i in range(0x70, 0xA0):
    status, data = send_request(0x21, [i])
    if data and len(data) >= 3 and data[0] == 0x7F and data[1] == 0x21:
        nrc = data[2]
        if nrc != 0x12:
            print(f"  0x{i:02X}  →  NRC 0x{nrc:02X}")
    elif data:
        print(f"  0x{i:02X}  →  {hex_ascii(data)}")
    else:
        pass
    bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
    time.sleep(0.03)

# 5. Other KWP2000 services we haven't tried
print("\n--- Other KWP2000 Services ---")
other_services = [
    (0x11, "ResetECU", [0x01]),
    (0x13, "StartDiagnosticRoutine", [0x01]),
    (0x14, "ClearDiagnosticInfo", [0xFF]),
    (0x1E, "StopDiagnosticSession", []),
    (0x27, "SecurityAccess", [0x01]),
    (0x2F, "InputOutputControlByLocalId", [0x04]),
    (0x30, "InputOutputControlByLocalId", [0x04]),
    (0x34, "RequestDownload", []),
    (0x3B, "WriteDataByLocalId", [0x01]),
    (0x3E, "TesterPresent", [0x01]),
    (0x85, "StartRoutineByLocalId", [0x01]),
    (0x86, "StopRoutineByLocalId", [0x01]),
    (0x87, "RequestRoutineResultsByLocalId", [0x01]),
]
for svc, name, subfunc in other_services:
    status, data = send_request(svc, subfunc)
    if data is None:
        print(f"  0x{svc:02X} {name:30s}  →  TIMEOUT")
    elif len(data) >= 3 and data[0] == 0x7F:
        nrc = data[2]
        nrc_names = {0x10: "General Reject", 0x11: "Service Not Supported",
                     0x12: "Sub-Function Not Supported", 0x22: "Conditions Not Correct",
                     0x24: "Request Sequence Error", 0x31: "Request Out of Range",
                     0x33: "Security Access Denied", 0x72: "General Programming Failure"}
        desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
        print(f"  0x{svc:02X} {name:30s}  →  {desc}")
    else:
        print(f"  0x{svc:02X} {name:30s}  →  {hex_ascii(data)}")
    bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
    time.sleep(0.05)

print("\n" + "=" * 78)
print("  Done!")
bus.shutdown()