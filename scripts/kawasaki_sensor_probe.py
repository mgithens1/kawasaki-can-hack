#!/usr/bin/env python3
"""
Kawasaki Ninja 7 Hybrid — Sensor Probe v3.1
Reads live sensor data from KWP2000 service 0x21.

Confirmed sensor map (June 2026):
  0x04 - Engine Load (byte × 100 / 255) — confirmed with throttle
  0x05 - Intake Air Pressure kPa (byte × 4 × 0.136) — swings with revs
  0x06 - Coolant Temp °C (byte − 40) — matches dash
  0x07 - Intake Air Temp °C (byte − 40) — stable at ambient
  0x08 - Reference/Calibration value? (static 0x53) — NOT live sensor
  0x09 - Engine RPM ((A<<8|B) / 4) — confirmed
  0x0A - Static value ~733 — NOT motor RPM, likely calibration
  0x0B - Gear Position (0=neutral) — from kawaduino
  0x0C - Vehicle Speed (single byte km/h) — confirmed stationary=0
  0x0D - Vehicle Speed (2-byte, (A<<8|B)/2 kph) — from kawaduino
  0xB4 - Secondary MAP/throttle pressure — tracks IAP

Passive broadcast CAN IDs (no ECU request needed):
  0x0100 (100Hz) - Cluster Status
  0x0111 (50Hz)  - Status Flags
  0x0112 (100Hz) - Status Flags
  0x0120 (5Hz)   - Config Constant
  0x0121 (100Hz) - Status Flags
  0x0125 (10Hz)  - Status
  0x0174 (100Hz) - Motor Controller A (rapidly changing)
  0x0178 (100Hz) - Motor Controller B (rapidly changing)
  0x017C (100Hz) - Motor Controller C (rapidly changing)
  0x0222 (50Hz)  - Status flag (0x0020)
  0x0271-0x0273   - ECU ID ASCII broadcast (1Hz): "ML5CXGA11RDA04358"
  0x0280 (50Hz)  - Controller Data
  0x0281 (4Hz)   - Motor/Electrical (fluctuating with engine)
  0x0282 (10Hz)  - System Voltage/Status
  0x0283 (100Hz) - Status Flags
  0x0284 (1Hz)   - Temp/Voltage A (decreases with warmup)
  0x0285 (4Hz)   - Temp/Voltage B (decreases with warmup)
  0x0050 (33Hz)  - Status
  0x0054 (49Hz)  - Status
  0x03E3 (20Hz)  - Status
  0x070C (10Hz)  - ECU Ident ISO-TP broadcast (1Hz cycle):
    Frame 0x01: Cal date (0x07E8=year, month, day)
    Frame 0x02-0x04: SW version (ASCII)
    Frame 0x05: Build value
    Frame 0x06: Flags
    Frame 0x07-0x08: Part number (ASCII "26105-001")
    Frame 0x09-0x0A: Serial/model (ASCII)
  0x0710 (10Hz)  - ECU Data ISO-TP broadcast
  0x0720 (10Hz)  - Temperatures? (0x0F38 0x0F34/35 0x50×4)
  0x0728 (10Hz)  - Controller Data

Usage:
  1. Key ON, kill switch RUN (engine OFF or ON)
  2. Run this script
  3. Ctrl+C to stop
"""

import can
import time
import sys
import os
from datetime import datetime

CAN_CHANNEL = 0
CAN_BITRATE = 500000
ECU_REQUEST_ID = 0x764
ECU_RESPONSE_ID = 0x746
CAN_DL = 8
LOG_DIR = os.path.expanduser("~/Downloads/can-logs")

def decode_temp(data):
    return data[0] - 40 if data and data[0] != 0xFF else None

def decode_rpm(data):
    if len(data) >= 2:
        return round(((data[0] << 8) | data[1]) / 4, 1)
    return None

def decode_speed_kph(data):
    if len(data) >= 2:
        return round(((data[0] << 8) | data[1]) / 2, 1)
    return None

def decode_iap(data):
    if data:
        return round(data[0] * 4 * 0.136, 1)
    return None

def decode_load(data):
    if data:
        return round(data[0] * 100 / 255, 1)
    return None

# PID list with confirmed labels and decoders
SENSOR_IDS = [
    # === Confirmed dynamic sensors ===
    (0x04, "Engine Load (%)",           decode_load),
    (0x05, "Intake Air Press (kPa)",    decode_iap),
    (0x06, "Coolant Temp (°C)",         decode_temp),
    (0x07, "Intake Air Temp (°C)",       decode_temp),
    (0x08, "Reference/Static (0x53)",    lambda b: b[0] if b else None),
    (0x09, "Engine RPM",                decode_rpm),
    (0x0A, "Static/Calibration ~733",    lambda b: ((b[0]<<8)|b[1]) if len(b)>=2 else None),
    (0x0B, "Gear Position",             lambda b: b[0] if b else None),
    (0x0C, "Vehicle Speed (kph)",       lambda b: b[0] if b and b[0] != 0xFF else None),
    (0x0D, "Vehicle Speed 2-byte",      decode_speed_kph),

    # === Unknown but responsive ===
    (0xB4, "Secondary MAP/Pressure",    lambda b: b[0] if b else None),

    # === Hybrid system ===
    (0x44, "Hybrid Data 0x44",          lambda b: ((b[0]<<8)|b[1]) if len(b)>=2 else None),
    (0x45, "Hybrid State 0x45",         lambda b: b[0] if b else None),
    (0x46, "Hybrid Data 0x46",          lambda b: ((b[0]<<8)|b[1]) if len(b)>=2 else None),
    (0x47, "Hybrid Mode",               lambda b: b[0] if b else None),
    (0x48, "Hybrid Data 0x48",          lambda b: ((b[0]<<8)|b[1]) if len(b)>=2 else None),
    (0x49, "Hybrid State 0x49",          lambda b: b[0] if b else None),

    # === Clutch / TPS ===
    (0x50, "Clutch Status",             lambda b: ((b[0]<<8)|b[1]) if len(b)>=2 else None),
    (0x51, "Gear Position Alt",         lambda b: b[0] if b else None),
    (0x52, "TPS Alt",                   lambda b: ((b[0]<<8)|b[1]) if len(b)>=2 else None),

    # === Static/zero PIDs ===
    (0x01, "Status Flags",              None),
    (0x02, "Freeze Frame Info",         None),
    (0x03, "Fuel System Status",        None),
    (0x27, "Unknown 0x27",             None),
    (0x28, "Unknown 0x28",             None),
    (0x29, "Unknown 0x29",             None),
    (0x2A, "Unknown 0x2A",             None),
    (0x2E, "Unknown 0x2E",             None),
    (0x31, "Unknown 0x31",             None),
    (0x32, "Unknown 0x32",             None),
    (0x33, "Unknown 0x33",             None),
    (0x3C, "Unknown 0x3C",             None),
    (0x3D, "Unknown 0x3D",             None),
    (0x3E, "Unknown 0x3E",             None),
    (0x3F, "Unknown 0x3F",             None),
    (0x54, "Unknown 0x54",             None),
    (0x56, "Unknown 0x56",             None),
    (0x5B, "Unknown 0x5B",             None),
    (0x5C, "Unknown 0x5C",             None),
    (0x5D, "Unknown 0x5D",             None),
    (0x5E, "Unknown 0x5E",             None),
    (0x5F, "Unknown 0x5F",             None),
    (0x62, "Unknown 0x62",             None),
    (0x63, "Unknown 0x63",             None),
    (0x64, "Unknown 0x64",             None),
    (0x65, "Unknown 0x65",             None),
    (0x66, "Unknown 0x66",             None),
    (0x67, "Unknown 0x67",             None),
    (0x68, "Unknown 0x68",             None),
    (0x6E, "Unknown 0x6E",             None),
    (0x6F, "Unknown 0x6F",             None),
    (0x9B, "Unknown 0x9B",             None),
]


def iso_tp_request(bus, service_id, subfunc_data, timeout=2.0):
    """Send ISO-TP request, return (status, payload)."""
    uds_payload = bytearray([service_id]) + bytearray(subfunc_data)
    req = bytearray(CAN_DL)
    req[0] = len(uds_payload)
    req[1:1 + len(uds_payload)] = uds_payload

    msg = can.Message(arbitration_id=ECU_REQUEST_ID, data=req, is_extended_id=False)
    try:
        bus.send(msg)
    except can.CanError as e:
        return ("ERROR", str(e), None)

    start = time.time()
    while time.time() - start < timeout:
        resp = bus.recv(0.5)
        if not resp or resp.arbitration_id != ECU_RESPONSE_ID:
            continue

        fd = bytes(resp.data)
        pci = fd[0]

        if (pci & 0xF0) == 0x00:
            sf_len = pci & 0x0F
            if sf_len == 0:
                continue
            payload = fd[1:1 + sf_len]
            if len(payload) >= 3 and payload[0] == 0x7F and payload[1] == service_id:
                return ("NRC", payload[2], None)
            return ("OK", payload, None)

        elif (pci & 0xF0) == 0x10:
            total_len = ((pci & 0x0F) << 8) | fd[1]
            reassembled = bytearray(fd[2:8])
            fc = bytearray([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            bus.send(can.Message(arbitration_id=ECU_REQUEST_ID, data=fc, is_extended_id=False))

            fc_timeout = time.time() + timeout
            while len(reassembled) < total_len and time.time() < fc_timeout:
                cf = bus.recv(1.0)
                if cf and cf.arbitration_id == ECU_RESPONSE_ID:
                    cfd = bytes(cf.data)
                    if (cfd[0] & 0xF0) == 0x20:
                        remaining = total_len - len(reassembled)
                        take = min(7, remaining)
                        reassembled.extend(cfd[1:1 + take])

            if len(reassembled) >= total_len:
                reassembled = reassembled[:total_len]
                if len(reassembled) >= 3 and reassembled[0] == 0x7F and reassembled[1] == service_id:
                    return ("NRC", reassembled[2], None)
                return ("OK", bytes(reassembled), None)
            return ("PARTIAL", len(reassembled), None)

    return ("TIMEOUT", None, None)


def open_session(bus):
    """Open diagnostic session 0x80."""
    flush_end = time.time() + 0.3
    while time.time() < flush_end:
        if bus.recv(0.01) is None:
            break

    init = bytearray(CAN_DL)
    init[0] = 0x02
    init[1] = 0x10
    init[2] = 0x80
    bus.send(can.Message(arbitration_id=ECU_REQUEST_ID, data=init, is_extended_id=False))

    start = time.time()
    while time.time() - start < 5.0:
        resp = bus.recv(1.0)
        if resp and resp.arbitration_id == ECU_RESPONSE_ID:
            fd = bytes(resp.data)
            if (fd[0] & 0xF0) == 0x00:
                sf_len = fd[0] & 0x0F
                payload = fd[1:1 + sf_len]
                if len(payload) >= 2 and payload[0] == 0x50 and payload[1] == 0x80:
                    return True
    return False


def main():
    print("=" * 74)
    print("  Kawasaki Ninja 7 Hybrid — Sensor Probe v3.1")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("  Confirmed: RPM, Load, IAP, Coolant, IAT, Speed, Gear")
    print("=" * 74)

    try:
        if sys.platform == "linux":
            bus = can.interface.Bus(interface='socketcan', channel=f'can{CAN_CHANNEL}', bitrate=CAN_BITRATE)
        else:
            bus = can.interface.Bus(interface='gs_usb', channel=CAN_CHANNEL, bitrate=CAN_BITRATE)
        print("Connected to CAN adapter.")
    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        sys.exit(1)

    if not open_session(bus):
        print("[ERROR] Session not accepted. Key ON, kill switch RUN?")
        bus.shutdown()
        sys.exit(1)
    print("Diagnostic session opened.\n")

    os.makedirs(LOG_DIR, exist_ok=True)
    log_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"sensor_probe_{log_ts}.txt")
    log = open(log_path, 'w')
    log.write(f"Kawasaki Ninja 7 Hybrid — Sensor Probe v3.1\n")
    log.write(f"Started: {datetime.now().isoformat()}\n")
    log.write(f"CAN: 500kbps, Req=0x{ECU_REQUEST_ID:03X}, Resp=0x{ECU_RESPONSE_ID:03X}\n\n")
    print(f"  Logging to: {log_path}")

    flush_end = time.time() + 0.2
    while time.time() < flush_end:
        if bus.recv(0.01) is None:
            break

    try:
        cycle = 0
        while True:
            cycle += 1
            timestamp = datetime.now().strftime('%H:%M:%S')
            ts_iso = datetime.now().isoformat()
            print(f"\n{'─' * 74}")
            print(f"  Sensor Read #{cycle} — {timestamp}")
            print(f"{'─' * 74}")
            print(f"  {'ID':>4s}  {'Sensor':30s}  {'Value':>12s}  {'Raw'}")
            print(f"  {'─'*4}  {'─'*30}  {'─'*12}  {'─'*20}")
            log.write(f"\n{'='*74}\n  Sensor Read #{cycle} — {ts_iso}\n{'='*74}\n")
            log.write(f"  {'ID':>4s}  {'Sensor':30s}  {'Value':>12s}  {'Raw'}\n")

            for local_id, desc, decode_fn in SENSOR_IDS:
                result = iso_tp_request(bus, 0x21, [local_id], timeout=1.5)

                if result[0] == "NRC":
                    nrc = result[1]
                    nrc_names = {0x11: "Not Supported", 0x12: "Not Supported",
                                 0x22: "Conditions Not Met", 0x31: "Out of Range",
                                 0x33: "Security Access"}
                    label = nrc_names.get(nrc, f"NRC 0x{nrc:02X}")
                    print(f"  0x{local_id:02X}  {desc:30s}  {'—':>12s}  {label}")
                    log.write(f"  0x{local_id:02X}  {desc:30s}  {'—':>12s}  {label}\n")
                    continue

                if result[0] == "TIMEOUT":
                    print(f"  0x{local_id:02X}  {desc:30s}  {'—':>12s}  TIMEOUT")
                    log.write(f"  0x{local_id:02X}  {desc:30s}  {'—':>12s}  TIMEOUT\n")
                    continue

                if result[0] in ("ERROR", "PARTIAL"):
                    print(f"  0x{local_id:02X}  {desc:30s}  {'—':>12s}  {result[0]}")
                    log.write(f"  0x{local_id:02X}  {desc:30s}  {'—':>12s}  {result[0]}\n")
                    continue

                payload = result[1]
                if len(payload) >= 2 and payload[0] == 0x61:
                    data = bytes(payload[2:])
                else:
                    data = bytes(payload[1:]) if len(payload) > 1 else bytes(payload)

                if all(b == 0xFF for b in data):
                    print(f"  0x{local_id:02X}  {desc:30s}  {'N/A':>12s}  0xFF")
                    log.write(f"  0x{local_id:02X}  {desc:30s}  {'N/A':>12s}  0xFF\n")
                    continue

                decoded_str = ""
                if decode_fn:
                    try:
                        val = decode_fn(data)
                        if val is not None:
                            decoded_str = f"{val:.1f}" if isinstance(val, float) else str(val)
                    except Exception:
                        pass

                if not decoded_str:
                    decoded_str = f"({len(data)}B)"

                print(f"  0x{local_id:02X}  {desc:30s}  {decoded_str:>12s}  {data.hex(' ')}")
                log.write(f"  0x{local_id:02X}  {desc:30s}  {decoded_str:>12s}  {data.hex(' ')}\n")

                bus.send(can.Message(arbitration_id=ECU_REQUEST_ID,
                                     data=[0x01, 0x3E], is_extended_id=False))
                time.sleep(0.05)

            bus.send(can.Message(arbitration_id=ECU_REQUEST_ID,
                                 data=[0x01, 0x3E], is_extended_id=False))

            log.flush()
            print(f"\n  Next read in 2s... (Ctrl+C to stop)")
            time.sleep(2)

    except KeyboardInterrupt:
        print("\n\nClosing session.")
        log.write(f"\nSession ended: {datetime.now().isoformat()}\n")
        log.close()
        print(f"  Log saved to: {log_path}")
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()