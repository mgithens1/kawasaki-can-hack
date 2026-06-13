#!/usr/bin/env python3
"""Probe Service 0x13 (StartDiagnosticRoutine) with various routine IDs."""
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

nrc_names = {
    0x10: "General Reject", 0x11: "Service Not Supported",
    0x12: "Sub-Function Not Supported", 0x22: "Conditions Not Correct",
    0x24: "Request Sequence Error", 0x31: "Request Out of Range",
    0x33: "Security Access Denied", 0x35: "Access Denied",
    0x72: "General Programming Failure", 0x78: "Request Correctly Received - Response Pending",
}

# =====================================================
# Service 0x13 — StartDiagnosticRoutine
# Response SID is 0x53 (0x13 + 0x40)
# =====================================================
print("=" * 74)
print("  Service 0x13 — StartDiagnosticRoutine Probe")
print("  (Response SID = 0x53 for positive, 0x7F for negative)")
print("=" * 74)

# Try routine IDs 0x00 through 0xFF
# We know 0x00 returns 0x53 0x00 (positive)
print("\n--- Routine IDs 0x00-0xFF ---")
accepted = []
for rid in range(0x100):
    status, data = send_request(0x13, [rid])
    if data is None:
        continue  # timeout, skip
    
    if len(data) >= 3 and data[0] == 0x7F and data[1] == 0x13:
        nrc = data[2]
        if nrc == 0x12:  # sub-function not supported — skip silently
            pass
        elif nrc == 0x31:  # out of range — skip
            pass
        else:
            desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
            print(f"  0x{rid:02X}  →  {desc}")
    elif len(data) >= 2 and data[0] == 0x53:
        # Positive response! 0x53 = 0x13 + 0x40
        payload = data[1:] if len(data) > 1 else b""
        print(f"  0x{rid:02X}  →  ACCEPTED! Response: {hex_ascii(data)}")
        accepted.append((rid, data))
    else:
        print(f"  0x{rid:02X}  →  {hex_ascii(data)}")
    
    bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
    time.sleep(0.03)

print(f"\n--- Accepted Routine IDs ({len(accepted)}) ---")
for rid, data in accepted:
    print(f"  0x{rid:02X}: {hex_ascii(data)}")

# =====================================================
# Also try Service 0x87 — RequestRoutineResultsByLocalId
# (our earlier scan said "not supported" but let's be thorough)
# =====================================================
print("\n--- Service 0x87 — Routine Results ---")
for rid in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05]:
    status, data = send_request(0x87, [rid])
    if data is None:
        print(f"  0x{rid:02X}  →  TIMEOUT")
    elif len(data) >= 3 and data[0] == 0x7F:
        nrc = data[2]
        desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
        print(f"  0x{rid:02X}  →  {desc}")
    else:
        print(f"  0x{rid:02X}  →  {hex_ascii(data)}")
    bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
    time.sleep(0.05)

# =====================================================
# Try Service 0x86 — StopRoutineByLocalId
# =====================================================
print("\n--- Service 0x86 — Stop Routine ---")
for rid in [0x00, 0x01, 0x02, 0x03]:
    status, data = send_request(0x86, [rid])
    if data is None:
        print(f"  0x{rid:02X}  →  TIMEOUT")
    elif len(data) >= 3 and data[0] == 0x7F:
        nrc = data[2]
        desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
        print(f"  0x{rid:02X}  →  {desc}")
    else:
        print(f"  0x{rid:02X}  →  {hex_ascii(data)}")
    bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
    time.sleep(0.05)

# =====================================================
# Try Service 0x83 — AccessTimingParameter
# =====================================================
print("\n--- Service 0x83 — Access Timing Parameter ---")
for sub in [(0x83, [0x00]), (0x83, [0x01]), (0x83, [0x02]), (0x83, [0x03])]:
    svc, data = sub
    status, resp = send_request(svc, data)
    if resp is None:
        print(f"  0x{data[0]:02X}  →  TIMEOUT")
    elif len(resp) >= 3 and resp[0] == 0x7F:
        nrc = resp[2]
        desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
        print(f"  sub 0x{data[0]:02X}  →  {desc}")
    else:
        print(f"  sub 0x{data[0]:02X}  →  {hex_ascii(resp)}")
    bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
    time.sleep(0.05)

print("\n" + "=" * 74)
print("  Done!")
bus.shutdown()