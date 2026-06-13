#!/usr/bin/env python3
"""Test Service 0x13 routines more deeply - start them and observe behavior."""
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

def send_request(service, data_bytes, timeout=3.0):
    uds = bytearray([service] + list(data_bytes))
    req = bytearray([len(uds)] + list(uds) + [0x00] * (8 - 1 - len(uds)))
    bus.send(can.Message(arbitration_id=0x764, data=req[:8], is_extended_id=False))
    s = time.time()
    responses = []
    while time.time() - s < timeout:
        resp = bus.recv(0.5)
        if not resp or resp.arbitration_id != 0x746:
            continue
        fd = bytes(resp.data)
        pci = fd[0]
        if (pci & 0xF0) == 0x00:
            sf_len = pci & 0x0F
            if sf_len == 0: continue
            responses.append(bytes(fd[1:1 + sf_len]))
            # Check if this is a final response (positive or negative)
            if len(responses[-1]) >= 1:
                sid = responses[-1][0]
                if sid == 0x53 or sid == 0x7F:  # positive routine response or negative
                    return responses
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
                responses.append(bytes(reassembled[:total_len]))
                return responses
            return [("PARTIAL", len(reassembled))]
    return responses if responses else [("TIMEOUT", None)]

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

print("=" * 74)
print("  Service 0x13 — Routine Deep Test")
print("=" * 74)

# Test routine 0x00 and 0x01 with longer timeout to see if there's delayed response
for rid in [0x00, 0x01]:
    print(f"\n--- Starting Routine 0x{rid:02X} (3s timeout) ---")
    responses = send_request(0x13, [rid], timeout=5.0)
    for i, resp in enumerate(responses):
        if isinstance(resp, tuple):
            print(f"  Response {i+1}: {resp[0]} ({resp[1]})")
        elif isinstance(resp, bytes):
            if len(resp) >= 3 and resp[0] == 0x7F:
                nrc = resp[2]
                desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
                print(f"  Response {i+1}: NEGATIVE - {desc}")
            elif len(resp) >= 1 and resp[0] == 0x53:
                print(f"  Response {i+1}: POSITIVE - {hex_ascii(resp)}")
            else:
                print(f"  Response {i+1}: {hex_ascii(resp)}")
        else:
            print(f"  Response {i+1}: {resp}")

# Try routine 0x01 with additional data bytes (some routines need parameters)
print(f"\n--- Starting Routine 0x01 with params ---")
for params in [[0x01, 0x00], [0x01, 0x01], [0x01, 0x02], [0x01, 0x80], [0x01, 0xFF]]:
    responses = send_request(0x13, params, timeout=3.0)
    for resp in responses:
        if isinstance(resp, tuple):
            print(f"  0x13 {params.hex(' ')}  →  {resp[0]} ({resp[1]})")
        elif isinstance(resp, bytes):
            if len(resp) >= 3 and resp[0] == 0x7F:
                nrc = resp[2]
                desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
                print(f"  0x13 {params.hex(' ')}  →  {desc}")
            elif len(resp) >= 1 and resp[0] == 0x53:
                print(f"  0x13 {params.hex(' ')}  →  POSITIVE: {hex_ascii(resp)}")
            else:
                print(f"  0x13 {params.hex(' ')}  →  {hex_ascii(resp)}")
        else:
            print(f"  0x13 {params.hex(' ')}  →  {resp}")

# Try reading sensor 0x01 (status flags) after starting routine 0x01
# to see if anything changed
print(f"\n--- Read status flags (0x01) after routine start ---")
for _ in range(3):
    responses = send_request(0x21, [0x01], timeout=2.0)
    for resp in responses:
        if isinstance(resp, bytes) and len(resp) >= 2:
            print(f"  0x01 status: {hex_ascii(resp)}")
    time.sleep(0.5)

# Try Service 0x14 (ClearDiagnosticInfo) — different from 0x14 in our earlier test
# The earlier test used subfunc 0xFF, try 0x00 (clear all)
print(f"\n--- Service 0x14 — Clear Diagnostic Info variants ---")
for param in [[0x00], [0x01], [0xFF], [0x00, 0x00]]:
    responses = send_request(0x14, param, timeout=2.0)
    for resp in responses:
        if isinstance(resp, tuple):
            print(f"  0x14 {param.hex(' ')}  →  {resp[0]} ({resp[1]})")
        elif isinstance(resp, bytes):
            if len(resp) >= 3 and resp[0] == 0x7F:
                nrc = resp[2]
                desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
                print(f"  0x14 {param.hex(' ')}  →  {desc}")
            else:
                print(f"  0x14 {param.hex(' ')}  →  {hex_ascii(resp)}")

# Try Service 0x27 SecurityAccess with different levels
print(f"\n--- Service 0x27 — Security Access Levels ---")
for level in range(0x01, 0x10):
    responses = send_request(0x27, [level], timeout=2.0)
    for resp in responses:
        if isinstance(resp, tuple):
            print(f"  Level 0x{level:02X}  →  TIMEOUT")
        elif isinstance(resp, bytes):
            if len(resp) >= 3 and resp[0] == 0x7F:
                nrc = resp[2]
                desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
                print(f"  Level 0x{level:02X}  →  {desc}")
            elif len(resp) >= 2 and resp[0] == 0x67:
                seed_data = resp[2:] if len(resp) > 2 else b""
                print(f"  Level 0x{level:02X}  →  SEED! {hex_ascii(resp)}")
            else:
                print(f"  Level 0x{level:02X}  →  {hex_ascii(resp)}")

print("\n" + "=" * 74)
print("  Done!")
bus.shutdown()