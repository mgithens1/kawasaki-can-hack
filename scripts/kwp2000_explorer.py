#!/usr/bin/env python3
"""KWP2000 Service Explorer — probe all service IDs and sub-functions."""
import can, time, sys

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

def send_request(service, data_bytes, timeout=2.0):
    """Send a KWP2000 request, return (status, raw_response_bytes)."""
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

        # Single Frame
        if (pci & 0xF0) == 0x00:
            sf_len = pci & 0x0F
            if sf_len == 0:
                continue
            payload = fd[1:1 + sf_len]
            return ("OK", bytes(payload))

        # First Frame (multi-frame)
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

def hex_dump(data):
    """Return hex string with printable ASCII."""
    if data is None:
        return "None"
    hex_str = data.hex(" ")
    ascii_str = ""
    for b in data:
        ascii_str += chr(b) if 32 <= b < 127 else "."
    return f"{hex_str}  |{ascii_str}|"

# =====================================================
# KWP2000 Service Probing
# =====================================================

services_to_try = [
    # (service_id, description, [(subfunc, desc), ...])
    (0x10, "StartDiagnosticSession", [(0x80, "default"), (0x89, "programming"), (0x90, "dyno"), (0x01, "default_alt")]),
    (0x12, "ReadFreezeFrameData", [(0x00, "frame_0"), (0x01, "frame_1")]),
    (0x17, "ReadStatusOfDTC", [(0x01, "active"), (0x00, "all")]),
    (0x18, "ReadDTCByStatus", [(0x01, "active_dtc"), (0x00, "all_dtc"), (0xFF, "all_extended")]),
    (0x1A, "ReadECUIdentification", [
        (0x00, "ECU_ID_0"), (0x01, "ECU_ID_1"), (0x02, "ECU_ID_2"),
        (0x03, "ECU_ID_3"), (0x04, "ECU_ID_4"), (0x05, "ECU_ID_5"),
        (0x06, "ECU_ID_6"), (0x07, "ECU_ID_7"), (0x08, "ECU_ID_8"),
        (0x09, "ECU_ID_9"), (0x0A, "ECU_ID_10"),
        (0x80, "ECU_ID_80"), (0x81, "ECU_ID_81"), (0x82, "ECU_ID_82"),
        (0x83, "ECU_ID_83"), (0x84, "ECU_ID_84"), (0x85, "ECU_ID_85"),
        (0x90, "VIN"), (0x91, "SW_version"), (0x92, "HW_version"),
        (0x93, "manufacturer"), (0x94, "supplier"), (0x95, "date"),
    ]),
    (0x1B, "ReadStatusInformation", [(0x01, "status_1"), (0x00, "status_0")]),
    (0x1C, "ReadDiagnosticIdentification", [(0x00, "diag_0"), (0x01, "diag_1")]),
    (0x1E, "ReadECUIdentificationMore", [(0x00, "id_0"), (0x01, "id_1")]),
    (0x21, "ReadDataByLocalId", [(0x01, "status_flags"), (0x02, "freeze_frame"), (0x03, "fuel_sys")]),
    (0x22, "ReadDataByIdentifier (UDS)", [(0xF1, 0x90, "VIN_UDS"), (0xF1, 0x93, "SW_UDS"), (0xF1, 0x95, "date_UDS")]),
]

print("=" * 74)
print("  KWP2000 Service Explorer")
print("=" * 74)

for svc_id, svc_name, subfuncs in services_to_try:
    print(f"\n{'─' * 74}")
    print(f"  Service 0x{svc_id:02X} — {svc_name}")
    print(f"{'─' * 74}")

    for subfunc in subfuncs:
        if isinstance(subfunc, tuple) and len(subfunc) == 3:
            # UDS-style 3-byte subfunc
            sub_data = [subfunc[0], subfunc[1]]
            label = subfunc[2]
        else:
            sub_data = [subfunc[0]] if isinstance(subfunc, tuple) else [subfunc]
            label = subfunc[1] if isinstance(subfunc, tuple) else f"0x{subfunc:02X}"

        status, data = send_request(svc_id, sub_data)

        if status == "TIMEOUT":
            print(f"  {label:20s}  →  TIMEOUT")
        elif data is None:
            print(f"  {label:20s}  →  {status}")
        elif len(data) >= 3 and data[0] == 0x7F:
            nrc = data[2]
            nrc_names = {0x10: "General Reject", 0x11: "Service Not Supported",
                         0x12: "Sub-Function Not Supported", 0x22: "Conditions Not Correct",
                         0x31: "Request Out of Range", 0x33: "Security Access Denied",
                         0x72: "General Programming Failure"}
            desc = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
            print(f"  {label:20s}  →  {desc}")
        else:
            # Strip response SID
            resp_data = data
            if len(data) > 1:
                # Response SID = request SID + 0x40
                expected_resp = svc_id + 0x40
                if data[0] == expected_resp:
                    resp_data = data[1:]
            print(f"  {label:20s}  →  {hex_dump(resp_data)}")

        # Tester present between requests
        bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
        time.sleep(0.05)

print(f"\n{'=' * 74}")
print("  Done!")
bus.shutdown()