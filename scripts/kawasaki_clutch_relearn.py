#!/usr/bin/env python3
"""
Kawasaki Ninja 7 Hybrid — Clutch Relearn Tool v5.0
Opens diagnostic session, reads ECU info + DTCs, holds session for clutch relearn.

What works on this ECU (KWP2000 over CAN):
  - Session 0x80 (Extended Diagnostic): ✅
  - Service 0x1A (ReadECUIdentification): ✅ — returns ECU part/serial
  - Service 0x18 0x01 (ReadDTCByStatus): ✅ — confirmed zero DTCs
  - Service 0x3E (TesterPresent): ✅ — holds session
  - Clutch relearn procedure: ✅ — session stays active

What doesn't work (behind SecurityAccess):
  - Service 0x27 level 0x07 gives a 6-byte seed, but Kawasaki's proprietary
    seed→key algorithm is unknown. All key attempts return NRC 0x12.
  - VIN, SW version, etc. require security unlock.
  - Dealer tool (KDS) required for full access.

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
CAN_CHANNEL = 0
CAN_BITRATE = 500000
ECU_REQUEST_ID = 0x764
ECU_RESPONSE_ID = 0x746
LOG_DIR = os.path.expanduser("~/Downloads/can-logs")

# ISO-TP frame type masks
ISO_TP_SINGLE_MASK = 0xF0
ISO_TP_FIRST_MASK  = 0x10
ISO_TP_CONSEC_MASK = 0x20
ISO_TP_FLOW_MASK   = 0x30

CAN_DL = 8


# --- ISO-TP PROTOCOL LAYER ---

def iso_tp_send_and_receive(bus, service_id, subfunction_data, description="",
                            timeout=5.0, log_file=None):
    """Send a UDS/KWP request and receive the full ISO-TP response.
    Handles Single Frame, First Frame + Flow Control + Consecutive Frame reassembly.
    Returns the complete response payload (service byte onward) or None."""
    uds_payload = bytearray([service_id]) + bytearray(subfunction_data)
    request_data = bytearray(CAN_DL)
    request_data[0] = len(uds_payload)
    request_data[1:1 + len(uds_payload)] = uds_payload

    msg = can.Message(arbitration_id=ECU_REQUEST_ID, data=request_data, is_extended_id=False)

    try:
        bus.send(msg)
        print(f"  [SENT] 0x{ECU_REQUEST_ID:03X} | {bytes(request_data).hex(' ')} | {description}")
        if log_file:
            log_file.write(f"  [SENT] 0x{ECU_REQUEST_ID:03X} {bytes(request_data).hex(' ')} | {description}\n")
    except can.CanError as e:
        print(f"  [ERROR] Send failed: {e}")
        return None

    start = time.time()
    while time.time() - start < timeout:
        resp = bus.recv(0.5)
        if not resp:
            continue
        if resp.arbitration_id != ECU_RESPONSE_ID:
            continue

        frame_data = bytes(resp.data)
        pci = frame_data[0]

        # --- Single Frame ---
        if (pci & ISO_TP_SINGLE_MASK) == 0x00:
            sf_len = pci & 0x0F
            if sf_len == 0:
                continue
            payload = frame_data[1:1 + sf_len]

            if len(payload) >= 3 and payload[0] == 0x7F and payload[1] == service_id:
                nrc = payload[2]
                nrc_names = {
                    0x10: "General Reject", 0x11: "Service Not Supported",
                    0x12: "Sub-Function Not Supported", 0x13: "Incorrect Message Length",
                    0x22: "Conditions Not Correct", 0x31: "Request Out of Range",
                    0x33: "Security Access Denied", 0x35: "Invalid Key",
                    0x36: "Exceeded Attempts", 0x72: "General Programming Failure",
                    0x78: "Request Correctly Received - Response Pending",
                }
                print(f"  [RECV] Negative Response: NRC 0x{nrc:02X} ({nrc_names.get(nrc, 'Unknown')})")
                if log_file:
                    log_file.write(f"  [RECV] Negative Response: NRC 0x{nrc:02X} ({nrc_names.get(nrc, 'Unknown')})\n")
                return None

            return payload

        # --- First Frame (multi-frame response) ---
        elif (pci & ISO_TP_FIRST_MASK) == 0x10:
            total_len = ((pci & 0x0F) << 8) | frame_data[1]
            print(f"  [ISOTP] First Frame: total_len={total_len}")
            if log_file:
                log_file.write(f"  [ISOTP] First Frame: total_len={total_len}\n")

            reassembled = bytearray(frame_data[2:CAN_DL])
            frames_received = 1

            flow_control = bytearray([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            fc_msg = can.Message(arbitration_id=ECU_REQUEST_ID, data=flow_control, is_extended_id=False)
            try:
                bus.send(fc_msg)
                print(f"  [ISOTP] Sent Flow Control (BS=0, STmin=0)")
                if log_file:
                    log_file.write(f"  [ISOTP] Sent Flow Control (BS=0, STmin=0)\n")
            except can.CanError as e:
                print(f"  [ERROR] Flow Control send failed: {e}")
                return None

            expected_seq = 1
            fc_timeout = time.time() + timeout

            while len(reassembled) < total_len and time.time() < fc_timeout:
                cf_msg = bus.recv(1.0)
                if not cf_msg:
                    continue
                if cf_msg.arbitration_id != ECU_RESPONSE_ID:
                    continue

                cf_data = bytes(cf_msg.data)
                cf_pci = cf_data[0]

                if (cf_pci & ISO_TP_CONSEC_MASK) == 0x20:
                    seq = cf_pci & 0x0F
                    if seq != (expected_seq % 16):
                        print(f"  [ISOTP] WARNING: Expected seq {expected_seq % 16}, got {seq}")
                        if log_file:
                            log_file.write(f"  [ISOTP] WARNING: Expected seq {expected_seq % 16}, got {seq}\n")

                    bytes_remaining = total_len - len(reassembled)
                    bytes_in_frame = min(7, bytes_remaining)
                    reassembled.extend(cf_data[1:1 + bytes_in_frame])
                    frames_received += 1
                    expected_seq += 1

                elif (cf_pci & ISO_TP_SINGLE_MASK) == 0x00:
                    sf_len = cf_pci & 0x0F
                    payload = cf_data[1:1 + sf_len]
                    if len(payload) >= 3 and payload[0] == 0x7F:
                        nrc = payload[2]
                        print(f"  [RECV] Negative Response during multi-frame: NRC 0x{nrc:02X}")
                        if log_file:
                            log_file.write(f"  [RECV] Negative Response during multi-frame: NRC 0x{nrc:02X}\n")
                        return None

            if len(reassembled) >= total_len:
                reassembled = reassembled[:total_len]
                print(f"  [ISOTP] Reassembled {frames_received} frames, {total_len} bytes")
                if log_file:
                    log_file.write(f"  [ISOTP] Reassembled {frames_received} frames, {total_len} bytes\n")

                if len(reassembled) >= 3 and reassembled[0] == 0x7F and reassembled[1] == service_id:
                    nrc = reassembled[2]
                    print(f"  [RECV] Negative Response: NRC 0x{nrc:02X}")
                    if log_file:
                        log_file.write(f"  [RECV] Negative Response: NRC 0x{nrc:02X}\n")
                    return None

                return reassembled
            else:
                print(f"  [ISOTP] Incomplete: got {len(reassembled)}/{total_len} bytes")
                if log_file:
                    log_file.write(f"  [ISOTP] Incomplete: got {len(reassembled)}/{total_len} bytes\n")
                return None

        elif (pci & ISO_TP_FLOW_MASK) == 0x30:
            continue

    print(f"  [RECV] Timeout — no response")
    return None


# --- KWP2000 DATA READERS ---

def read_ecu_identification(bus, timeout=5.0, log_file=None):
    """Read ECU identification via KWP2000 service 0x1A. This one works!"""
    resp = iso_tp_send_and_receive(
        bus, 0x1A, [0x80],
        description="Read ECU Identification (0x1A)",
        timeout=timeout, log_file=log_file
    )
    if resp is None:
        return None
    if len(resp) >= 1 and resp[0] == 0x5A:
        return bytes(resp[1:])
    else:
        print(f"  [WARN] Unexpected ECU ID response: {resp.hex(' ')}")
        return bytes(resp)


def read_kwp_local_id(bus, local_id, description="", timeout=3.0, log_file=None):
    """Read by KWP2000 service 0x21. Most IDs require SecurityAccess."""
    resp = iso_tp_send_and_receive(
        bus, 0x21, [local_id],
        description=f"ReadLocal 0x{local_id:02X} ({description})" if description else f"ReadLocal 0x{local_id:02X}",
        timeout=timeout, log_file=log_file
    )
    if resp is None:
        return None
    if len(resp) >= 2 and resp[0] == 0x61:
        return bytes(resp[2:])
    # Negative response or unexpected — already logged by iso_tp layer
    return None


def try_decode_ascii(raw_bytes):
    """Try to decode bytes as ASCII, return string or hex."""
    if not raw_bytes:
        return "(empty)"
    try:
        text = raw_bytes.decode('ascii')
        if all(32 <= ord(c) < 127 for c in text):
            return text
    except (UnicodeDecodeError, ValueError):
        pass
    return raw_bytes.hex(' ')


def format_dtc(code):
    """Format a 2-byte DTC as readable string."""
    systems = {
        0x0: "P0", 0x1: "P1", 0x2: "P2", 0x3: "P3",
        0x4: "C0", 0x5: "C1", 0x6: "C2", 0x7: "C3",
        0x8: "B0", 0x9: "B1", 0xA: "B2", 0xB: "B3",
        0xC: "U0", 0xD: "U1", 0xE: "U2", 0xF: "U3",
    }
    prefix = systems.get((code >> 12) & 0xF, "??")
    return f"{prefix}{code & 0xFFF:04X}"


# --- ECU INFO ---

KWP_LOCAL_IDS = {
    0x80: "ECU Identification",
    0x84: "VIN",
    0x97: "Software Version",
}


def read_ecu_info(bus, log_file=None):
    """Read ECU identification. Only 0x1A works without security access."""
    print("\n" + "=" * 50)
    print("ECU IDENTIFICATION")
    print("=" * 50)

    results = {}

    # Service 0x1A — known to work
    print("\n  Reading ECU identification (service 0x1A)...")
    ecu_id = read_ecu_identification(bus, log_file=log_file)
    if ecu_id:
        ascii_val = try_decode_ascii(ecu_id)
        hex_val = ecu_id.hex(' ')
        print(f"  ECU ID:  ASCII: {ascii_val}")
        print(f"           Raw:   {hex_val}")
        results["ecu_id"] = {"ascii": ascii_val, "hex": hex_val, "raw": ecu_id}

    # Try service 0x21 local IDs — most will need security access
    print("\n  Reading local identifiers (service 0x21)...")
    print("  (Most require SecurityAccess — will show access denied if locked)")
    for local_id, desc in KWP_LOCAL_IDS.items():
        raw = read_kwp_local_id(bus, local_id, description=desc, log_file=log_file)
        if raw:
            ascii_val = try_decode_ascii(raw)
            hex_val = raw.hex(' ')
            print(f"  0x{local_id:02X} ({desc:25s}): ASCII: {ascii_val:30s} Raw: {hex_val}")
            results[f"local_{local_id:02x}"] = {"ascii": ascii_val, "hex": hex_val, "raw": raw}
        else:
            print(f"  0x{local_id:02X} ({desc:25s}): Not available (requires security access)")
        time.sleep(0.1)

    if not results:
        print("\n  ⚠ No ECU data could be read.")

    if log_file:
        log_file.write(f"\n{'='*50}\nECU IDENTIFICATION — {datetime.now().isoformat()}\n{'='*50}\n")
        for key, val in results.items():
            log_file.write(f"  {key}: ASCII={val['ascii']} Raw={val['hex']}\n")

    return results


def read_ecu_dtcs(bus, log_file=None):
    """Read DTCs via KWP2000 service 0x18. Only 0x18 0x01 (simple) works."""
    print("\n" + "=" * 50)
    print("DIAGNOSTIC TROUBLE CODES")
    print("=" * 50)

    dtcs = []

    # 0x18 0x01 — simple count/status. Returns 0x58 0x00 = zero DTCs
    resp = iso_tp_send_and_receive(
        bus, 0x18, [0x01],
        description="Read DTCs (0x18 0x01)",
        timeout=5.0, log_file=log_file
    )

    if resp and len(resp) >= 1 and resp[0] == 0x58:
        if len(resp) == 2 and resp[1] == 0x00:
            print("  ✅ No DTCs — system clean!")
        elif len(resp) >= 2:
            # Try to parse DTC records
            payload = resp[1:]
            maybe_count = (payload[0] << 8) | payload[1] if len(payload) >= 2 else 0
            if maybe_count == 0:
                print("  ✅ No DTCs — system clean!")
            elif maybe_count < 50:
                print(f"  DTC count: {maybe_count}")
                i = 2
                while i + 3 <= len(payload):
                    code = (payload[i] << 8) | payload[i + 1]
                    status = payload[i + 2]
                    if code != 0 or status != 0:
                        dtcs.append((code, status))
                    i += 3
                if dtcs:
                    print(f"\n  Found {len(dtcs)} DTC(s):")
                    for code, status in dtcs:
                        status_flags = []
                        if status & 0x01: status_flags.append("Test Failed")
                        if status & 0x02: status_flags.append("Test Incomplete")
                        if status & 0x08: status_flags.append("Confirmed")
                        if status & 0x20: status_flags.append("Pending")
                        status_str = ", ".join(status_flags) if status_flags else f"0x{status:02X}"
                        print(f"    {format_dtc(code):8s} (raw: 0x{code:04X}) Status: {status_str}")
        else:
            print(f"  DTC response: {resp.hex(' ')}")
    elif resp and len(resp) >= 3 and resp[0] == 0x7F:
        nrc = resp[2]
        print(f"  DTC read failed: NRC 0x{nrc:02X}")
    else:
        print("  No DTC response received.")

    if log_file:
        log_file.write(f"\n{'='*50}\nDTCs — {datetime.now().isoformat()}\n{'='*50}\n")
        if dtcs:
            for code, status in dtcs:
                log_file.write(f"DTC {format_dtc(code)} (0x{code:04X}) Status: 0x{status:02X}\n")
        else:
            log_file.write("No DTCs found\n")

    return dtcs


# --- CAN BUS INIT ---

def initialize_bus():
    """Initializes the CAN bus based on the host Operating System."""
    tp = sys.platform
    print(f"Detected Operating System: {tp}")

    try:
        if tp == "linux":
            print(f"Connecting via Linux SocketCAN (interface='socketcan', channel='can{CAN_CHANNEL}')...")
            return can.interface.Bus(interface='socketcan', channel=f'can{CAN_CHANNEL}', bitrate=CAN_BITRATE)
        elif tp in ("darwin", "win32"):
            print(f"Connecting via USB abstraction layer (interface='gs_usb', channel={CAN_CHANNEL})...")
            return can.interface.Bus(interface='gs_usb', channel=CAN_CHANNEL, bitrate=CAN_BITRATE)
        else:
            print("Unknown OS. Attempting general fallback...")
            return can.interface.Bus(channel=CAN_CHANNEL, bitrate=CAN_BITRATE)
    except Exception as e:
        print(f"\n[ERROR] Auto-initialization failed: {e}")
        print("\nOS-Specific Verification Checklist:")
        print("  - MAC: Ensure 'brew install libusb' has been executed.")
        print("  - LINUX: Verify: 'sudo ip link set can0 up type can bitrate 500000'")
        print("  - WINDOWS: Missing libusb-1.0.dll? Download or install via pip.")
        sys.exit(1)


# --- MAIN ---

def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"ecu_log_{timestamp}.txt")

    bus = initialize_bus()
    print("Successfully connected to the CAN adapter.\n")

    with open(log_path, 'w') as log_file:
        log_file.write(f"Kawasaki Ninja 7 Hybrid — ECU Log (v5.0)\n")
        log_file.write(f"Started: {datetime.now().isoformat()}\n")
        log_file.write(f"CAN: 500kbps, Request ID: 0x{ECU_REQUEST_ID:03X}, Response ID: 0x{ECU_RESPONSE_ID:03X}\n")

        # --- STEP 1: Open diagnostic session ---
        print("=" * 50)
        print("OPENING DIAGNOSTIC SESSION (0x80)")
        print("=" * 50)

        # Flush receive buffer (bounded — bus has constant traffic)
        flush_deadline = time.time() + 0.3
        while time.time() < flush_deadline:
            msg = bus.recv(0.01)
            if msg is None:
                break

        init_data = bytearray(CAN_DL)
        init_data[0] = 0x02
        init_data[1] = 0x10
        init_data[2] = 0x80

        msg = can.Message(arbitration_id=ECU_REQUEST_ID, data=init_data, is_extended_id=False)
        try:
            bus.send(msg)
            print(f"[SENT] 0x{ECU_REQUEST_ID:03X} | {bytes(init_data).hex(' ')} | Diagnostic Session Request")
            log_file.write(f"[SENT] 0x{ECU_REQUEST_ID:03X} {bytes(init_data).hex(' ')} — Diagnostic Session Request\n")
        except can.CanError as e:
            print(f"[ERROR] Failed to send: {e}")
            bus.shutdown()
            sys.exit(1)

        print("Waiting for session response...")
        response_received = False
        start_time = time.time()

        while time.time() - start_time < 5.0:
            resp = bus.recv(1.0)
            if resp and resp.arbitration_id == ECU_RESPONSE_ID:
                frame_data = bytes(resp.data)
                if (frame_data[0] & ISO_TP_SINGLE_MASK) == 0x00:
                    sf_len = frame_data[0] & 0x0F
                    payload = frame_data[1:1 + sf_len]
                    if len(payload) >= 2 and payload[0] == 0x50 and payload[1] == 0x80:
                        print(f"[RECV] Session accepted! Data: {frame_data.hex(' ')}")
                        log_file.write(f"[RECV] 0x{ECU_RESPONSE_ID:03X} {frame_data.hex(' ')} — Session Accepted\n")
                        response_received = True
                        break

        if not response_received:
            print("[ERROR] No session response. Check key switch, kill switch, wiring.")
            log_file.write("[ERROR] Session handshake failed — timeout\n")
            bus.shutdown()
            sys.exit(1)

        # --- STEP 2: Read ECU info ---
        ecu_info = read_ecu_info(bus, log_file)

        # --- STEP 3: Read DTCs ---
        dtcs = read_ecu_dtcs(bus, log_file)

        # --- STEP 4: Hold session for clutch relearn ---
        print("\n" + "=" * 50)
        print("DIAGNOSTIC SESSION ACTIVE")
        print("=" * 50)
        print()
        print("  ✅ Session is open. ECU is ready for clutch relearn.")
        print()
        print("  CLUTCH RELEARN PROCEDURE:")
        print("  1. Start the engine")
        print("  2. Hold E-BOOST + START simultaneously")
        print("  3. Wait for boost gauge to count down to zero")
        print("  4. Ctrl+C to stop this script")
        print("  5. Turn key OFF to save calibration")
        print()
        print("=" * 50)
        print()

        tester_present_msg = can.Message(arbitration_id=ECU_REQUEST_ID,
                                          data=[0x01, 0x3E], is_extended_id=False)
        last_send_time = 0

        try:
            while True:
                current_time = time.time()
                if current_time - last_send_time >= 2.0:
                    try:
                        bus.send(tester_present_msg)
                        print(f"[KEEP-ALIVE] Tester Present | {time.strftime('%H:%M:%S')}")
                        log_file.write(f"{time.strftime('%H:%M:%S')} [SENT] Tester Present\n")
                        last_send_time = current_time
                    except can.CanOperationError as e:
                        print(f"[CAN ERROR] {e}")
                        time.sleep(1)

                incoming = bus.recv(0.1)
                if incoming:
                    log_file.write(f"{time.strftime('%H:%M:%S')} [BUS] 0x{incoming.arbitration_id:03X} {incoming.data.hex(' ')}\n")
                    if incoming.arbitration_id == ECU_RESPONSE_ID:
                        print(f"[ECU] ID: 0x{incoming.arbitration_id:03X} | Data: {incoming.data.hex(' ')}")

        except KeyboardInterrupt:
            print("\n[INFO] Script stopped by user.")
            log_file.write(f"\n[INFO] Script stopped by user at {datetime.now().isoformat()}\n")
        finally:
            log_file.write(f"\nSession ended: {datetime.now().isoformat()}\n")
            bus.shutdown()
            print("Shutdown complete.")

    print(f"\nLog saved to: {log_path}")


if __name__ == "__main__":
    main()