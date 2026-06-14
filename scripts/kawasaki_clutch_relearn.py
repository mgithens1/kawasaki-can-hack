#!/usr/bin/env python3
"""
Kawasaki Ninja 7 Hybrid — Clutch Relearn Tool v6.0
Opens diagnostic session, reads ECU ID + DTCs, holds session for clutch relearn.

What works on this ECU (KWP2000 over CAN, TX=0x764, RX=0x746):
  - Session 0x80 (Extended Diagnostic): ✅
  - Service 0x1A (ReadECUIdentification): ✅ — ECU part/serial
  - Service 0x18 0x01 (ReadDTCByStatus): ✅ — confirmed zero DTCs
  - Service 0x21 (ReadLocalIdentifier): ✅ — many PIDs readable without security
  - Service 0x3E (TesterPresent): ✅ — holds session

What doesn't work (requires SecurityAccess, seed-key unknown):
  - Service 0x27 (SecurityAccess): seed→key algorithm unknown after 70 attempts
  - VIN read, SW version, drive mode config, ALPF: all behind SecurityAccess

Usage:
  1. Key ON, kill switch RUN, engine OFF
  2. Run this script
  3. Wait for "DIAGNOSTIC SESSION ACTIVE" message
  4. Start engine, hold E-BOOST + START until boost gauge counts to zero
  5. Ctrl+C to stop
  6. Turn key OFF to save calibration
"""

import can
import time
import sys
import os
from datetime import datetime

# --- CONFIGURATION ---
CAN_CHANNEL = "can0"
CAN_BITRATE = 500000
ECU_TX = 0x764
ECU_RX = 0x746
LOG_DIR = os.path.expanduser("~/Downloads/can-logs")


# --- ISO-TP PROTOCOL LAYER ---

def iso_tp_send(bus, uds_payload, tx_id=ECU_TX, description=""):
    """Send a UDS/KWP payload via ISO-TP. Handles single and multi-frame."""
    data = bytearray(uds_payload)

    if len(data) <= 7:
        # Single Frame
        frame = bytearray(8)
        frame[0] = len(data)
        frame[1:1 + len(data)] = data
        msg = can.Message(arbitration_id=tx_id, data=frame, is_extended_id=False)
        bus.send(msg)
    else:
        # First Frame
        total = len(data)
        ff = bytearray(8)
        ff[0] = 0x10 | ((total >> 8) & 0x0F)
        ff[1] = total & 0xFF
        ff[2:8] = data[:6]
        bus.send(can.Message(arbitration_id=tx_id, data=ff, is_extended_id=False))

        # Wait for Flow Control
        deadline = time.time() + 3.0
        while time.time() < deadline:
            resp = bus.recv(0.5)
            if resp and resp.arbitration_id == ECU_RX:
                pci = resp.data[0]
                if (pci & 0xF0) == 0x30:  # Flow Control
                    break
                elif (pci & 0xF0) == 0x00:  # Single Frame response (unexpected)
                    sf_len = pci & 0x0F
                    return bytes(resp.data[1:1 + sf_len])
        else:
            print(f"  [ERROR] No Flow Control received for multi-frame send")
            return None

        # Send Consecutive Frames
        remaining = data[6:]
        seq = 1
        while remaining:
            chunk = remaining[:7]
            remaining = remaining[7:]
            cf = bytearray(8)
            cf[0] = 0x20 | (seq & 0x0F)
            cf[1:1 + len(chunk)] = chunk
            bus.send(can.Message(arbitration_id=tx_id, data=cf, is_extended_id=False))
            seq += 1
            time.sleep(0.005)  # Small inter-frame delay

    if description:
        print(f"  [TX] {description}")
    return None  # For sends, caller doesn't expect response here


def iso_tp_request(bus, service_id, subfunction_data, description="", timeout=3.0):
    """Send a UDS/KWP request and receive the full ISO-TP response.
    Returns the complete response payload (service byte onward) or None."""

    uds_payload = bytearray([service_id]) + bytearray(subfunction_data)

    # Build and send the request frame
    if len(uds_payload) <= 7:
        frame = bytearray(8)
        frame[0] = len(uds_payload)
        frame[1:1 + len(uds_payload)] = uds_payload
        bus.send(can.Message(arbitration_id=ECU_TX, data=frame, is_extended_id=False))
    else:
        # Multi-frame send
        iso_tp_send(bus, uds_payload, description=description)
        # Response handling below
        pass

    if description:
        print(f"  [TX] {description}")

    # Receive response
    start = time.time()
    while time.time() - start < timeout:
        resp = bus.recv(0.5)
        if not resp or resp.arbitration_id != ECU_RX:
            continue

        frame = bytes(resp.data)
        pci = frame[0]

        # Single Frame
        if (pci & 0xF0) == 0x00:
            sf_len = pci & 0x0F
            if sf_len == 0:
                continue
            payload = frame[1:1 + sf_len]

            # Check for negative response
            if len(payload) >= 3 and payload[0] == 0x7F:
                nrc = payload[2]
                nrc_names = {
                    0x10: "General Reject", 0x11: "Service Not Supported",
                    0x12: "Sub-Function Not Supported", 0x13: "Incorrect Message Length",
                    0x22: "Conditions Not Correct", 0x31: "Request Out of Range",
                    0x33: "Security Access Denied", 0x35: "Invalid Key",
                    0x36: "Exceeded Attempts", 0x37: "Time Delay Not Expired",
                    0x72: "General Programming Failure",
                    0x78: "Request Correctly Received - Response Pending",
                }
                print(f"  [RX] Negative: NRC 0x{nrc:02X} ({nrc_names.get(nrc, 'Unknown')})")
                return None

            return bytes(payload)

        # First Frame (multi-frame response)
        elif (pci & 0xF0) == 0x10:
            total_len = ((pci & 0x0F) << 8) | frame[1]
            reassembled = bytearray(frame[2:8])

            # Send Flow Control
            fc = bytearray([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            bus.send(can.Message(arbitration_id=ECU_TX, data=fc, is_extended_id=False))

            expected_seq = 1
            while len(reassembled) < total_len:
                cf = bus.recv(2.0)
                if not cf or cf.arbitration_id != ECU_RX:
                    continue
                cf_data = bytes(cf.data)
                if (cf_data[0] & 0xF0) == 0x20:  # Consecutive Frame
                    seq = cf_data[0] & 0x0F
                    remaining = total_len - len(reassembled)
                    reassembled.extend(cf_data[1:1 + min(7, remaining)])
                    expected_seq += 1
                elif (cf_data[0] & 0xF0) == 0x00:  # Single Frame in multi-frame context
                    sf_len = cf_data[0] & 0x0F
                    payload = cf_data[1:1 + sf_len]
                    if len(payload) >= 3 and payload[0] == 0x7F:
                        nrc = payload[2]
                        print(f"  [RX] Negative during multi-frame: NRC 0x{nrc:02X}")
                        return None

            reassembled = reassembled[:total_len]

            # Check for negative response in multi-frame
            if len(reassembled) >= 3 and reassembled[0] == 0x7F:
                nrc = reassembled[2]
                print(f"  [RX] Negative: NRC 0x{nrc:02X}")
                return None

            print(f"  [RX] Multi-frame: {total_len} bytes")
            return bytes(reassembled)

        # Flow Control (for our multi-frame sends — skip)
        elif (pci & 0xF0) == 0x30:
            continue

    print(f"  [RX] Timeout — no response within {timeout}s")
    return None


# --- DATA HELPERS ---

def try_decode_ascii(raw):
    """Try to decode bytes as ASCII, return string or hex."""
    if not raw:
        return "(empty)"
    try:
        text = raw.decode('ascii')
        if all(32 <= ord(c) < 127 for c in text):
            return text
    except (UnicodeDecodeError, ValueError):
        pass
    return raw.hex(' ')


def format_dtc(code):
    """Format a 2-byte DTC code."""
    prefix_map = {0: "P0", 1: "P1", 2: "P2", 3: "P3",
                  4: "C0", 5: "C1", 6: "C2", 7: "C3",
                  8: "B0", 9: "B1", 0xA: "B2", 0xB: "B3",
                  0xC: "U0", 0xD: "U1", 0xE: "U2", 0xF: "U3"}
    prefix = prefix_map.get((code >> 12) & 0xF, "??")
    return f"{prefix}{code & 0xFFF:04X}"


# --- DIAGNOSTIC FUNCTIONS ---

def open_session(bus):
    """Open KWP2000 diagnostic session (type 0x80). Returns True on success."""
    # Flush receive buffer
    deadline = time.time() + 0.3
    while time.time() < deadline:
        if not bus.recv(0.01):
            break

    resp = iso_tp_request(bus, 0x10, [0x80],
                           description="Open Diagnostic Session (0x10 0x80)")
    if resp and len(resp) >= 2 and resp[0] == 0x50 and resp[1] == 0x80:
        print("  ✅ Session opened")
        return True
    else:
        print("  ❌ Session failed — check key switch and kill switch")
        return False


def read_ecu_id(bus):
    """Read ECU identification via service 0x1A 0x80."""
    print("\n--- ECU Identification (0x1A) ---")
    resp = iso_tp_request(bus, 0x1A, [0x80],
                           description="Read ECU ID (0x1A 0x80)")
    if resp and resp[0] == 0x5A:
        raw = bytes(resp[1:])
        print(f"  ECU ID: {try_decode_ascii(raw)}")
        print(f"  Raw:    {raw.hex(' ')}")
        return raw
    print("  (no response)")
    return None


def read_dtcs(bus):
    """Read DTCs via service 0x18 0x01."""
    print("\n--- Diagnostic Trouble Codes (0x18) ---")
    resp = iso_tp_request(bus, 0x18, [0x01],
                           description="Read DTCs (0x18 0x01)")
    if resp and resp[0] == 0x58:
        if len(resp) == 2 and resp[1] == 0x00:
            print("  ✅ No DTCs — system clean!")
            return []
        elif len(resp) >= 4:
            count = (resp[1] << 8) | resp[2] if len(resp) > 2 else 0
            if count == 0:
                print("  ✅ No DTCs — system clean!")
                return []
            print(f"  DTC count: {count}")
            dtcs = []
            i = 3
            while i + 2 < len(resp):
                code = (resp[i] << 8) | resp[i + 1]
                status = resp[i + 2]
                if code != 0 or status != 0:
                    dtcs.append((code, status))
                i += 3
            for code, status in dtcs:
                flags = []
                if status & 0x01: flags.append("Failed")
                if status & 0x02: flags.append("Incomplete")
                if status & 0x08: flags.append("Confirmed")
                if status & 0x20: flags.append("Pending")
                print(f"  {format_dtc(code)} (0x{code:04X}) Status: {', '.join(flags) or f'0x{status:02X}'}")
            return dtcs
    print("  (no response)")
    return None


# --- MAIN ---

def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"clutch_relearn_{timestamp}.txt")

    print("Kawasaki Ninja 7 Hybrid — Clutch Relearn Tool v6.0")
    print(f"CAN: {CAN_CHANNEL} @ {CAN_BITRATE}bps, TX=0x{ECU_TX:03X}, RX=0x{ECU_RX:03X}\n")

    try:
        bus = can.interface.Bus(interface='socketcan', channel=CAN_CHANNEL, bitrate=CAN_BITRATE)
    except Exception as e:
        print(f"[ERROR] CAN bus init failed: {e}")
        print("  Make sure can0 is up: sudo ip link set can0 up type can bitrate 500000")
        sys.exit(1)

    with open(log_path, 'w') as log:
        log.write(f"Kawasaki Ninja 7 Hybrid — Clutch Relearn v6.0\n")
        log.write(f"Started: {datetime.now().isoformat()}\n\n")

        # Step 1: Open session
        print("=" * 50)
        print("STEP 1: Open Diagnostic Session")
        print("=" * 50)
        if not open_session(bus):
            bus.shutdown()
            sys.exit(1)

        # Step 2: Read ECU info
        print("\n" + "=" * 50)
        print("STEP 2: Read ECU Info")
        print("=" * 50)
        ecu_id = read_ecu_id(bus)
        dtcs = read_dtcs(bus)

        # Step 3: Hold session for clutch relearn
        print("\n" + "=" * 50)
        print("STEP 3: Hold Session for Clutch Relearn")
        print("=" * 50)
        print()
        print("  ✅ Diagnostic session is active.")
        print()
        print("  CLUTCH RELEARN PROCEDURE:")
        print("  1. Start the engine")
        print("  2. Hold E-BOOST + START simultaneously")
        print("  3. Wait for boost gauge to count down to zero")
        print("  4. Press Ctrl+C to end this script")
        print("  5. Turn key OFF to save calibration")
        print()

        tester_present = can.Message(arbitration_id=ECU_TX,
                                      data=[0x01, 0x3E], is_extended_id=False)
        last_keepalive = 0

        try:
            while True:
                now = time.time()
                if now - last_keepalive >= 2.0:
                    bus.send(tester_present)
                    ts = time.strftime('%H:%M:%S')
                    print(f"  [{ts}] Tester Present sent")
                    log.write(f"{ts} Tester Present\n")
                    last_keepalive = now

                msg = bus.recv(0.1)
                if msg and msg.arbitration_id == ECU_RX:
                    ts = time.strftime('%H:%M:%S')
                    print(f"  [{ts}] ECU: {msg.data.hex(' ')}")
                    log.write(f"{ts} ECU 0x{ECU_RX:03X} {msg.data.hex(' ')}\n")

        except KeyboardInterrupt:
            print("\n\n  Script stopped by user.")
            log.write(f"\nStopped by user at {datetime.now().isoformat()}\n")

    bus.shutdown()
    print(f"  Log saved to: {log_path}")


if __name__ == "__main__":
    main()