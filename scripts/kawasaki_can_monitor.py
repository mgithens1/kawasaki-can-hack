#!/usr/bin/env python3
"""
Kawasaki Ninja 7 Hybrid — CAN Bus Monitor v1.1
Passively reads broadcast CAN messages (no ECU requests needed).
Decodes known broadcast IDs in real-time.

Confirmed broadcast map (June 2026, Ninja 7 Hybrid ECU ML5CXGA11RDA04358):

  0x0100 (100 Hz) — Cluster/Status (all zeros with engine off)
  0x0111 (50 Hz)  — Status flags (all zeros with engine off)
  0x0112 (100 Hz) — Status flags (all zeros with engine off)
  0x0120 (5 Hz)   — Config constant (00 CE 00 00)
  0x0121 (100 Hz) — Status flags (all zeros with engine off)
  0x0125 (10 Hz)  — Status (all zeros with engine off)
  0x0174 (100 Hz) — Motor Controller A (rapidly changing)
  0x0178 (100 Hz) — Motor Controller B (rapidly changing)
  0x017C (100 Hz) — Motor Controller C (rapidly changing)
  0x0222 (50 Hz)  — Status (00 20 = some flag)
  0x0271 (1 Hz)   — ECU ID part 1 (ASCII: "ML5CXGA1")
  0x0272 (1 Hz)   — ECU ID part 2 (ASCII: "1RDA0435")
  0x0273 (1 Hz)   — ECU ID part 3 (ASCII: "8")
  0x0280 (50 Hz)  — Controller data (64 9D 11 00 45 04)
  0x0281 (4 Hz)   — Motor/Electrical (fluctuating with engine)
  0x0282 (10 Hz)  — System voltage/status (00 58/59 00 00)
  0x0283 (100 Hz) — Status flags (all zeros with engine off)
  0x0284 (1 Hz)   — Temp/voltage (decreases with engine warmup)
  0x0285 (4 Hz)   — Temp/voltage (decreases with engine warmup)
  0x0500 (33 Hz)  — Status (00 00 00 00)
  0x0054 (49 Hz)  — Status (9D 01 00 00)
  0x03E3 (20 Hz)  — Status (01 BB 00 00 00 C7)
  0x070C (10 Hz)  — ECU Identification (ISO-TP multi-frame broadcast)
  0x0710 (10 Hz)  — ECU Data (ISO-TP multi-frame broadcast)
  0x0720 (10 Hz)  — Temperatures (IAT×2 + 4× coolant-style sensors, byte-40)
  0x0728 (10 Hz)  — Controller data (0E 00 00 00 00 00 00)

  0x070C ISO-TP frames (1 Hz cycle):
    0x01: Calibration date — bytes 0-1 = year (0x07E8=2024), byte 2 = month, byte 3 = day
    0x02: Software version string (ASCII)
    0x03: Software version string (ASCII)
    0x04: Additional version (ASCII)
    0x05: Build/config value (0x07D0 = 2000)
    0x06: Flags (00 00 01 00 00 00 00)
    0x07: Part number (ASCII: "26105-0")
    0x08: Revision (ASCII: "001")
    0x09: Serial/model (ASCII)
    0x0A: Additional ID (ASCII)
    0xFF: End marker

Usage:
  1. Connect CAN adapter to bike's diagnostic port
  2. Key ON (engine OFF or ON)
  3. Run this script
  4. Ctrl+C to stop
"""

import can
import time
import sys
from datetime import datetime
from collections import defaultdict

CAN_CHANNEL = 0
CAN_BITRATE = 500000

# Known broadcast IDs with labels and decoders
BROADCAST_IDS = {
    0x0100: ("Cluster Status", 100, lambda d: f"flags={d.hex(' ')}"),
    0x0111: ("Status Flags 0x111", 50, lambda d: f"flags={d.hex(' ')}"),
    0x0112: ("Status Flags 0x112", 100, lambda d: f"flags={d.hex(' ')}"),
    0x0120: ("Config Constant", 5, lambda d: f"val=0x{d[1]:02X} ({d[1]})" if len(d)>=2 else d.hex(' ')),
    0x0121: ("Status Flags 0x121", 100, lambda d: f"flags={d.hex(' ')}"),
    0x0125: ("Status 0x125", 10, lambda d: d.hex(' ')),
    0x0174: ("Motor Controller A", 100, None),  # Too fast to decode inline
    0x0178: ("Motor Controller B", 100, None),
    0x017C: ("Motor Controller C", 100, None),
    0x0222: ("Status 0x222", 50, lambda d: f"flag=0x{d[1]:02X}" if len(d)>=2 else d.hex(' ')),
    0x0271: ("ECU ID Part 1", 1, lambda d: d.decode('ascii', errors='replace').rstrip('\x00')),
    0x0272: ("ECU ID Part 2", 1, lambda d: d.decode('ascii', errors='replace').rstrip('\x00')),
    0x0273: ("ECU ID Part 3", 1, lambda d: d.decode('ascii', errors='replace').rstrip('\x00')),
    0x0280: ("Controller 0x280", 50, lambda d: d.hex(' ')),
    0x0281: ("Motor/Electrical", 4, lambda d: d.hex(' ')),
    0x0282: ("System Voltage?", 10, lambda d: f"raw={d[1]:02X} ({d[1]})" if len(d)>=2 else d.hex(' ')),
    0x0283: ("Status 0x283", 100, lambda d: d.hex(' ')),
    0x0284: ("Temp/Volt A", 1, lambda d: f"b0={d[0]:02X} b1={d[1]:02X}({d[1]})" if len(d)>=2 else d.hex(' ')),
    0x0285: ("Temp/Volt B", 4, lambda d: f"b0={d[0]:02X} b1={d[1]:02X}({d[1]})" if len(d)>=2 else d.hex(' ')),
    0x0050: ("Status 0x050", 33, lambda d: d.hex(' ')),
    0x0054: ("Status 0x054", 49, lambda d: f"0x{d[0]:02X} 0x{d[1]:02X}" if len(d)>=2 else d.hex(' ')),
    0x03E3: ("Status 0x3E3", 20, lambda d: d.hex(' ')),
    0x070C: ("ECU Ident Broadcast", 10, None),  # Special ISO-TP handling
    0x0710: ("ECU Data Broadcast", 10, None),  # Special ISO-TP handling
    0x0720: ("Temperatures", 10, lambda d: 
             f"IAT1={(d[0]<<8|d[1])/256:.1f}°C IAT2={(d[2]<<8|d[3])/256:.1f}°C "
             f"T3={d[4]-40}°C T4={d[5]-40}°C T5={d[6]-40}°C T6={d[7]-40}°C" 
             if len(d)>=8 else d.hex(' ')),
    0x0728: ("Controller 0x728", 10, lambda d: d.hex(' ')),
}

# ISO-TP reassembler for 0x070C ECU ID broadcast
ECU_ID_FRAMES = {}
ECU_ID_LAST_CYCLE = 0

def decode_ecu_id_broadcast():
    """Decode the 0x070C ISO-TP multi-frame ECU identification."""
    global ECU_ID_FRAMES
    if not ECU_ID_FRAMES:
        return None
    
    result = {
        'cal_date': None,
        'sw_version': '',
        'part_number': '',
        'serial': '',
        'raw': {}
    }
    
    # Frame 0x01: Calibration date
    if 0x01 in ECU_ID_FRAMES:
        d = ECU_ID_FRAMES[0x01]
        if len(d) >= 4:
            year = (d[0] << 8) | d[1]
            month = d[2]
            day = d[3]
            result['cal_date'] = f"{year}-{month:02d}-{day:02d}"
            result['raw']['cal_date_hex'] = d[:7].hex(' ')
    
    # Frames 0x02-0x04: Software version (ASCII)
    sw = ''
    for i in [0x02, 0x03, 0x04]:
        if i in ECU_ID_FRAMES:
            sw += ECU_ID_FRAMES[i].decode('ascii', errors='replace').rstrip('\x00')
    result['sw_version'] = sw
    
    # Frame 0x05: Build value
    if 0x05 in ECU_ID_FRAMES:
        d = ECU_ID_FRAMES[0x05]
        if len(d) >= 2:
            val = (d[0] << 8) | d[1]
            result['raw']['build_value'] = f"0x{val:04X} ({val})"
    
    # Frame 0x06: Flags
    if 0x06 in ECU_ID_FRAMES:
        result['raw']['flags'] = ECU_ID_FRAMES[0x06].hex(' ')
    
    # Frames 0x07-0x08: Part number (ASCII)
    pn = ''
    for i in [0x07, 0x08]:
        if i in ECU_ID_FRAMES:
            pn += ECU_ID_FRAMES[i].decode('ascii', errors='replace').rstrip('\x00')
    result['part_number'] = pn
    
    # Frames 0x09-0x0A: Serial/model (ASCII)
    sn = ''
    for i in [0x09, 0x0A]:
        if i in ECU_ID_FRAMES:
            sn += ECU_ID_FRAMES[i].decode('ascii', errors='replace').rstrip('\x00')
    result['serial'] = sn
    
    return result


def main():
    print("=" * 74)
    print("  Kawasaki Ninja 7 Hybrid — CAN Bus Monitor v1.1")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("  PASSIVE MODE — No messages sent to ECU")
    print("  Decoding known broadcast IDs in real-time")
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

    global ECU_ID_FRAMES, ECU_ID_LAST_CYCLE
    
    # Track state changes
    last_values = {}
    last_ecu_print = 0
    ecu_id_printed = False
    cycle_count = defaultdict(int)
    start_time = time.time()
    
    # For 0x0174/0178/017C — track min/max for changing bytes
    motor_stats = {
        0x0174: {'min': [255]*8, 'max': [0]*8},
        0x0178: {'min': [255]*8, 'max': [0]*8},
        0x017C: {'min': [255]*8, 'max': [0]*8},
    }
    motor_samples = defaultdict(int)
    
    print("\nListening for CAN messages... (Ctrl+C to stop)\n")
    
    try:
        while True:
            msg = bus.recv(0.1)
            if not msg:
                continue
            
            arb_id = msg.arbitration_id
            dlc = msg.dlc
            data = bytes(msg.data[:dlc])
            now = time.time()
            
            # Handle 0x070C ECU ID broadcast (ISO-TP)
            if arb_id == 0x070C and dlc >= 2:
                frame_num = data[0] & 0x0F
                if frame_num == 0xFF:  # End marker
                    pass
                elif frame_num == 0x00:  # Start marker
                    ECU_ID_FRAMES = {}
                else:
                    ECU_ID_FRAMES[frame_num] = data[1:]
                    
                # Print ECU ID every 5 seconds
                if now - last_ecu_print > 5.0 and len(ECU_ID_FRAMES) >= 5:
                    ecu = decode_ecu_id_broadcast()
                    if ecu and not ecu_id_printed:
                        ecu_id_ascii = ''
                        for mid in [0x0271, 0x0272, 0x0273]:
                            if mid in last_values:
                                ecu_id_ascii += last_values[mid]
                        print(f"\n{'─'*74}")
                        print(f"  ECU IDENTIFICATION (from broadcast 0x070C):")
                        if ecu:
                            print(f"    Calibration Date : {ecu.get('cal_date', '?')}")
                            print(f"    Software Version : {ecu.get('sw_version', '?')}")
                            print(f"    Part Number      : {ecu.get('part_number', '?')}")
                            print(f"    Serial/Model     : {ecu.get('serial', '?')}")
                            print(f"    ECU ID           : {ecu_id_ascii}")
                            if 'build_value' in ecu.get('raw', {}):
                                print(f"    Build Value      : {ecu['raw']['build_value']}")
                            if 'flags' in ecu.get('raw', {}):
                                print(f"    Flags            : {ecu['raw']['flags']}")
                        print(f"{'─'*74}\n")
                        ecu_id_printed = True
                    last_ecu_print = now
                continue
            
            # Handle 0x0710 ECU data broadcast (ISO-TP) — skip for now
            if arb_id == 0x0710:
                continue
            
            # Handle 0x0174/0178/017C motor controller — track stats, don't print every msg
            if arb_id in (0x0174, 0x0178, 0x017C):
                motor_samples[arb_id] += 1
                for i, b in enumerate(data[:8]):
                    if i < len(motor_stats[arb_id]['min']):
                        motor_stats[arb_id]['min'][i] = min(motor_stats[arb_id]['min'][i], b)
                        motor_stats[arb_id]['max'][i] = max(motor_stats[arb_id]['max'][i], b)
                continue
            
            # Handle ECU ID ASCII broadcasts
            if arb_id in (0x0271, 0x0272, 0x0273):
                ascii_val = data.decode('ascii', errors='replace').rstrip('\x00')
                last_values[arb_id] = ascii_val
                continue
            
            # Skip high-frequency zeros (0x0100, 0x0112, 0x0121, 0x0283) unless they change
            if arb_id in (0x0100, 0x0112, 0x0121, 0x0283):
                key = (arb_id, data.hex(' '))
                if key not in last_values:
                    last_values[key] = now
                    label = BROADCAST_IDS.get(arb_id, ("Unknown", 0, None))[0]
                    print(f"  {datetime.now().strftime('%H:%M:%S')}  0x{arb_id:04X}  {label:20s}  {data.hex(' ')}  [FIRST]")
                continue
            
            # Track all IDs
            cycle_count[arb_id] += 1
            
            # Decode and print changes
            label, rate, decoder = BROADCAST_IDS.get(arb_id, (f"Unknown 0x{arb_id:04X}", 0, None))
            
            hex_str = data.hex(' ')
            
            # Check if value changed
            prev = last_values.get(arb_id)
            curr = hex_str
            changed = (prev != curr)
            last_values[arb_id] = curr
            
            if decoder:
                try:
                    decoded = decoder(data)
                except Exception:
                    decoded = hex_str
            else:
                decoded = hex_str
            
            change_marker = " ★" if changed else ""
            if changed or cycle_count[arb_id] <= 3:  # Print first 3 + changes
                print(f"  {datetime.now().strftime('%H:%M:%S')}  0x{arb_id:04X}  {label:20s}  {decoded}{change_marker}")
    
    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print(f"\n\n{'='*74}")
        print(f"  Session Summary — {elapsed:.0f}s")
        print(f"{'='*74}")
        
        # Print ECU identification
        ecu = decode_ecu_id_broadcast()
        ecu_id_ascii = ''
        for mid in [0x0271, 0x0272, 0x0273]:
            if mid in last_values and isinstance(last_values[mid], str):
                ecu_id_ascii += last_values[mid]
        
        print(f"\n  ECU Identification:")
        print(f"    ECU ID           : {ecu_id_ascii}")
        if ecu:
            print(f"    Calibration Date : {ecu.get('cal_date', '?')}")
            print(f"    Software Version : {ecu.get('sw_version', '?')}")
            print(f"    Part Number      : {ecu.get('part_number', '?')}")
            print(f"    Serial/Model     : {ecu.get('serial', '?')}")
        
        # Print motor controller stats
        print(f"\n  Motor Controller Stats (0x0174/0178/017C):")
        for mid in (0x0174, 0x0178, 0x017C):
            label = BROADCAST_IDS.get(mid, ("Unknown",))[0]
            samples = motor_samples.get(mid, 0)
            if samples > 0:
                rate = samples / elapsed if elapsed > 0 else 0
                print(f"    0x{mid:04X} {label}: {samples} samples ({rate:.0f}/s)")
                mins = motor_stats[mid]['min']
                maxs = motor_stats[mid]['max']
                for i in range(8):
                    if mins[i] != maxs[i]:
                        print(f"      byte[{i}]: 0x{mins[i]:02X}–0x{maxs[i]:02X} ({mins[i]}–{maxs[i]})")
                    else:
                        print(f"      byte[{i}]: 0x{mins[i]:02X} (constant)")
        
        # Print message counts
        print(f"\n  Message Counts:")
        for aid, cnt in sorted(cycle_count.items(), key=lambda x: -x[1]):
            label = BROADCAST_IDS.get(aid, (f"0x{aid:04X}",))[0]
            rate = cnt / elapsed if elapsed > 0 else 0
            print(f"    0x{aid:04X}  {label:20s}  {cnt:5d} msgs  {rate:5.1f}/s")
        
        print()
    
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()