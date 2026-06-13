#!/usr/bin/env python3
"""Quick CAN session test + read a few key PIDs."""
import can, time, sys

bus = can.interface.Bus(interface="socketcan", channel="can0", bitrate=500000)
print("CAN connected")

# Flush
flush_end = time.time() + 0.3
while time.time() < flush_end:
    if bus.recv(0.01) is None:
        break
print("Flushed")

# Open session
init = bytearray([0x02, 0x10, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00])
bus.send(can.Message(arbitration_id=0x764, data=init, is_extended_id=False))
print("Session request sent")

start = time.time()
session_ok = False
while time.time() - start < 5.0:
    resp = bus.recv(1.0)
    if resp and resp.arbitration_id == 0x746:
        fd = bytes(resp.data)
        print(f"Session response: {fd.hex(' ')}")
        if (fd[0] & 0xF0) == 0x00:
            sf_len = fd[0] & 0x0F
            payload = fd[1:1 + sf_len]
            print(f"  Payload: {payload.hex(' ')}")
            if len(payload) >= 2 and payload[0] == 0x50 and payload[1] == 0x80:
                session_ok = True
                break
        elif (fd[0] & 0xF0) == 0x10:
            total_len = ((fd[0] & 0x0F) << 8) | fd[1]
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
            print(f"  Reassembled ({len(reassembled)}B): {reassembled.hex(' ')}")
            if len(reassembled) >= 2 and reassembled[0] == 0x50:
                session_ok = True
                break

if not session_ok:
    print("SESSION FAILED")
    bus.shutdown()
    sys.exit(1)

print("SESSION OPEN!\n")

def read_pid(pid, label, timeout=2.0):
    """Read a single PID via KWP2000 service 0x21."""
    uds = bytearray([0x21, pid])
    req = bytearray([len(uds)] + list(uds) + [0x00] * (8 - 1 - len(uds)))
    bus.send(can.Message(arbitration_id=0x764, data=req[:8], is_extended_id=False))

    start = time.time()
    while time.time() - start < timeout:
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
            if len(payload) >= 3 and payload[0] == 0x7F and payload[1] == 0x21:
                return f"NRC 0x{payload[2]:02X}"
            if len(payload) >= 2 and payload[0] == 0x61 and payload[1] == pid:
                data = bytes(payload[2:])
                return data.hex(' ')
            return f"raw: {payload.hex(' ')}"

        # First Frame
        elif (pci & 0xF0) == 0x10:
            total_len = ((pci & 0x0F) << 8) | fd[1]
            reassembled = bytearray(fd[2:8])
            fc = bytearray([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            bus.send(can.Message(arbitration_id=0x764, data=fc, is_extended_id=False))
            fc_timeout = time.time() + timeout
            while len(reassembled) < total_len and time.time() < fc_timeout:
                cf = bus.recv(1.0)
                if cf and cf.arbitration_id == 0x746:
                    cfd = bytes(cf.data)
                    if (cfd[0] & 0xF0) == 0x20:
                        remaining = total_len - len(reassembled)
                        take = min(7, remaining)
                        reassembled.extend(cfd[1:1 + take])
            if len(reassembled) >= total_len:
                reassembled = reassembled[:total_len]
                if len(reassembled) >= 3 and reassembled[0] == 0x7F and reassembled[1] == 0x21:
                    return f"NRC 0x{reassembled[2]:02X}"
                if len(reassembled) >= 2 and reassembled[0] == 0x61:
                    data = bytes(reassembled[2:])
                    return data.hex(' ')
            return f"PARTIAL ({len(reassembled)}/{total_len})"
    return "TIMEOUT"

# Read all the new PIDs
pids = [
    (0x04, "TPS / Engine Load"),
    (0x05, "Air Pressure / IAP"),
    (0x06, "Coolant Temp"),
    (0x07, "Intake Air Temp"),
    (0x08, "Oil Temp / MAP"),
    (0x09, "RPM"),
    (0x0A, "Motor/Assist RPM?"),
    (0x0B, "Gear Position"),
    (0x0C, "Vehicle Speed"),
    (0x0D, "Speed Alt?"),
    (0x20, "Unknown 0x20"),
    (0x27, "Unknown 0x27"),
    (0x28, "Unknown 0x28"),
    (0x29, "Unknown 0x29"),
    (0x2A, "Unknown 0x2A"),
    (0x2E, "Unknown 0x2E"),
    (0x31, "Unknown 0x31"),
    (0x32, "Unknown 0x32"),
    (0x33, "Unknown 0x33"),
    (0x3C, "Unknown 0x3C"),
    (0x3D, "Unknown 0x3D"),
    (0x3E, "Unknown 0x3E"),
    (0x3F, "Unknown 0x3F"),
    (0x40, "Unknown 0x40"),
    (0x44, "Unknown 0x44"),
    (0x45, "Hybrid State"),
    (0x46, "Hybrid Data"),
    (0x47, "Hybrid Mode"),
    (0x48, "Hybrid Data"),
    (0x49, "Hybrid State"),
    (0x50, "Clutch Status"),
    (0x51, "Gear Alt?"),
    (0x52, "TPS Alt?"),
    (0x54, "Unknown 0x54"),
    (0x56, "Unknown 0x56"),
    (0x5B, "Unknown 0x5B"),
    (0x5C, "Unknown 0x5C"),
    (0x5D, "Unknown 0x5D"),
    (0x5E, "Unknown 0x5E"),
    (0x5F, "Unknown 0x5F"),
    (0x60, "Unknown 0x60"),
    (0x61, "Unknown 0x61"),
    (0x62, "Unknown 0x62"),
    (0x63, "Unknown 0x63"),
    (0x64, "Unknown 0x64"),
    (0x65, "Unknown 0x65"),
    (0x66, "Unknown 0x66"),
    (0x67, "Unknown 0x67"),
    (0x68, "Unknown 0x68"),
    (0x6E, "Unknown 0x6E"),
    (0x6F, "Unknown 0x6F"),
    (0x80, "Unknown 0x80"),
    (0x9B, "Unknown 0x9B"),
    (0xA0, "Unknown 0xA0"),
    (0xB4, "Unknown 0xB4"),
]

print(f"{'PID':>6s}  {'Description':30s}  {'Raw Data'}")
print(f"{'─'*6}  {'─'*30}  {'─'*30}")

for pid, label in pids:
    raw = read_pid(pid, label)
    print(f"  0x{pid:02X}  {label:30s}  {raw}")
    # Tester present
    bus.send(can.Message(arbitration_id=0x764, data=[0x01, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
    time.sleep(0.05)

print("\nDone!")
bus.shutdown()