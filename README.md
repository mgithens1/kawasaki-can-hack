# Kawasaki Ninja 7 Hybrid — CAN Bus Reverse Engineering

Complete documentation and tools for reverse-engineering the Kawasaki Ninja 7 Hybrid (2024+) ECU via KWP2000-over-CAN (ISO 15765) and passive CAN bus monitoring.

## What This Project Is

The Ninja 7 Hybrid is Kawasaki's first hybrid motorcycle. Its ECU uses the KWP2000 diagnostic protocol over CAN bus, with proprietary extensions. This project documents every CAN message and KWP2000 service we've discovered through reverse engineering — **27 passive CAN broadcast IDs fully decoded, 200+ KWP2000 PIDs probed, and drive mode encoding cracked**.

No SecurityAccess required. No dealer tools needed. Just a CAN adapter and these scripts.

## Major Findings

### Drive Mode Encoding — Fully Decoded

| Mode | 0x0054 byte[1] | 0x0280 byte[2] | Kawasaki Name |
|------|----------------|----------------|---------------|
| SPORT | 0x01 | 0x11 | SPORT-HYBRID |
| ECO | 0x02 | 0x12 | ECO-HYBRID |
| ECO+AUTO | 0x03 | 0x13 | ECO+AUTO |
| WALK | 0x06 | 0x16 | WALK mode |
| KEY-OFF | — | 0x19 | Power-off state |

- **SPORT is 0x11, ECO is 0x12** — initially decoded backwards, corrected after verification
- **EV/HYBRID toggle**: bit 6 (0x40) in 0x0054 byte[0] and 0x0280 byte[1]
  - 0x9D = HYBRID (engine ready), 0x5D = EV (electric only)
  - ⚠️ 0x0280 byte[0] = 0x64 is a CONSTANT, not the EV flag — EV flag is in byte[1]
- **"HYBRID" is NOT a separate mode** — it's part of the mode name (SPORT-HYBRID, ECO-HYBRID)
- **ALPF (auto downshift)** is NOT on the CAN bus — requires SecurityAccess
- **Run switch position** is NOT broadcast on CAN bus — it's a hardware starter interlock only

### Passive CAN Broadcast IDs — Fully Decoded

The ECU broadcasts data continuously without any request. 27+ unique CAN IDs are active with key ON.

| CAN ID | Rate | Content | Formula / Notes |
|--------|------|---------|---------|
| 0x0004 | One-shot | Key-on/session init | bytes[1,6] change between sessions |
| 0x0050 | 33 Hz | Ride mode | byte[0]: 0=ECO/OFF, 1=HYBRID, 2=SPORT |
| 0x0054 | 50 Hz | Ride mode + EV | byte[0]: EV flag (bit 6: 0x40), byte[1]: mode |
| 0x0100 | 100 Hz | Cluster/placeholder | All zeros with key ON — may activate with engine |
| 0x0111 | 50 Hz | Unknown placeholder | All zeros — may activate with engine |
| 0x0112 | 100 Hz | Unknown placeholder | All zeros — may activate with engine |
| 0x0120 | ~1 Hz | Drifting value | byte[1] drifts (0xCE→0xB2), likely temp/voltage ADC |
| 0x0121 | 100 Hz | Gear position | 00 00=Neutral, 01 00=In gear |
| 0x0125 | 10 Hz | Unknown placeholder | All zeros — may activate with engine |
| 0x0174 | 100 Hz | Motor Controller A | Needs engine running to decode |
| 0x0178 | 100 Hz | Motor Controller B | Needs engine running to decode |
| 0x017C | 100 Hz | Motor Controller C | Needs engine running to decode |
| 0x0222 | 50 Hz | Status flag | 0x0020 = key ON |
| 0x0271 | 1 Hz | ECU ID part 1 | ASCII: "ML5CXGA1" |
| 0x0272 | 1 Hz | ECU ID part 2 | ASCII: "1RDA0435" |
| 0x0273 | 1 Hz | ECU ID part 3 | Combined: ML5CXGA11RDA04358 |
| 0x0280 | 50 Hz | Full status | byte[0]=0x64(const), byte[1]=EV flag, byte[2]=mode, byte[4]=gear, byte[5]=engine state |
| 0x0281 | 4 Hz | Motor/electrical | byte[4]=0x00 always, needs engine running to decode |
| 0x0282 | 10 Hz | Battery voltage | byte[1] / 8 = volts (e.g., 100 → 12.5V) |
| 0x0283 | 100 Hz | Unknown placeholder | All zeros — may activate with engine |
| 0x0284 | ~0.5 Hz | Temperature tracking A | byte[1] drifts (cooling), bytes[4:7]=3 temps (value-40°C) |
| 0x0285 | ~4 Hz | Temperature tracking B | byte[1] drifting, similar pattern to 0x0284 |
| 0x03E3 | 20 Hz | ECU status/config | 6 bytes: 01 BB 00 00 00 C7 (STATIC) |
| 0x070C | ~1 Hz | ECU identification | Multi-frame ISO-TP, see below |
| 0x0710 | ~10 Hz | ECU configuration | 79-frame broadcast, see below |
| 0x0720 | 1 Hz | 6 temperature sensors | IAT1/2=(word)/256°C, T3-T6=byte-40°C |
| 0x0728 | ~1 Hz | Heartbeat/alive | 0x0E 00 00 00 00 00 00 00 |

### ECU Identification (0x070C)

No SecurityAccess needed — just listen. Broadcast every ~1 second via ISO-TP multi-frame.

| Frame | Content | Decoded |
|-------|---------|---------|
| 0x01 | Date bytes | Calibration date: 2024-03-21 |
| 0x02-0x04 | ASCII | SW version: `2102D11220244156` |
| 0x05 | 0x07D0 | Build number: 2000 |
| 0x06 | 0x0001 | Config version |
| 0x07-0x08 | ASCII | HW part: `26105-0001` |
| 0x09-0x0B | ASCII | ECU part: `49245-230500000` (differs from KWP2000's 49245-2655) |
| 0x0C-0x11 | Binary | **LIVE data** (changes between captures!) |
| 0xFF | End marker | All zeros |

**Verifying a dealer ECU update:** Compare 0x070C before and after. If calibration date or SW version changes, the update took effect.

### ECU Configuration Broadcast (0x0710)

79-frame broadcast at ~10 Hz. Mostly 0xFF padding. Key data frames:

| Frame | Content | Notes |
|-------|---------|-------|
| 0x00/0x10/0x20 | ASCII "2102D11220244156" | SW version (matches 0x070C) |
| 0x30 | byte[1]=battery voltage | 0x64=100→12.5V, matches 0x0282 and KWP2000 PID 0x76 |
| 0x60 | Count/version: 4 | |
| 0x70 | Config values: 6, 7 | |
| 0x80 | Build: 0x0322=802 | |
| 0x90 | Identifier: 0x3212=12818 | |
| 0xB0 | Config + CRC | |
| 0xC0 | Config values | |
| 0xCD | End marker | All zeros |

All data is STATIC except checksum bytes in frames 0x30 and 0xB0.

### Temperature Sensors (0x0720)

| Sensor | Formula | Key ON (engine off) |
|--------|---------|---------------------|
| IAT1 | (byte[0]<<8 \| byte[1]) / 256 °C | ~15°C (ambient) |
| IAT2 | (byte[2]<<8 \| byte[3]) / 256 °C | ~15°C (ambient) |
| T3 | byte[4] − 40 °C | ~38°C (motor/inverter) |
| T4 | byte[5] − 40 °C | ~37°C |
| T5 | byte[6] − 40 °C | ~37°C |
| T6 | byte[7] − 40 °C | ~37°C |

Note: T3-T6 are motor/inverter temperatures, NOT coolant (which reads 29°C via KWP2000).

### Battery Voltage (0x0282)

`byte[1] / 8 = volts` — confirmed matching KWP2000 PID 0x76 (e.g., 100 → 12.5V)

### Motor/Electrical (0x0281)

Format: `D2 [b1] [D0/D1] [b3] 00 [b5] [3B/3C] [64]`

| Byte | Value Range | Notes |
|------|-------------|-------|
| 0 | 0xD2 | Constant message type |
| 1 | 60-184 | Varies — possibly current or torque offset |
| 2 | 0xD0-0xD1 | Sub-type, rarely flickers |
| 3 | 5-243 | Varies independently of b1 — possibly inverter/HV value |
| 4 | 0x00 | Always zero |
| 5 | 10-18 | Slow counter or sub-state |
| 6-7 | 0x3B64 or 0x3C64 | Constant within session, drifts between sessions |

**Needs engine running at known RPMs to decode actual meaning.**

## KWP2000 Active Diagnostics (ECU Request Required)

### Working Services

| Service | Status | Notes |
|---------|--------|-------|
| 0x10 | ✅ | Session type **0x80 only** — type 0x81 causes lockout |
| 0x13 | ✅ | Routine 0x01 starts successfully |
| 0x18 | ✅ | Read DTCs |
| 0x1A | ✅ | ECU ID (part number, serial, calibration) |
| 0x21 | ✅ | Read data by local ID (200+ PIDs respond) |

**Not supported:** 0x11, 0x12, 0x14, 0x17, 0x22, 0x2F/0x30, 0x34, 0x3B, 0x85/0x86/0x87

### Key PIDs (Service 0x21)

| PID | Content | Formula |
|-----|---------|---------|
| 0x04 | Engine load | byte × 100/255 % |
| 0x05 | IAP | byte × 4 × 0.136 kPa |
| 0x06 | Coolant temp | value − 40 °C |
| 0x07 | IAT | value − 40 °C |
| 0x08 | Reference value | Static 0x53 (NOT oil temp) |
| 0x09 | RPM | (A<<8 \| B) / 4 |
| 0x0A | Calibration | Static ~733 (NOT motor RPM) |
| 0x76 | Battery voltage | value / 8 = V |
| 0x1B | System voltage A | (A<<8\|B) / 256 ≈ 15.3V |
| 0x1C | System voltage B | (A<<8\|B) / 256 ≈ 15.3V |
| 0x44-0x4F | Hybrid config | Static, don't change with mode |
| 0x74 | Temperature sensor | Drifts slowly (0x51-0x5B) |
| 0xB1 | Calibration constant | 0xCB (static) |

### SecurityAccess

The Ninja 7 Hybrid ECU uses **6-byte random seeds** (Service 0x27, level 0x07). This is NOT the old 5-byte hardcoded Kawasaki system from the Z1000SX. All known algorithms (XOR, rotation, addition) have failed. The seed→key algorithm is proprietary and requires KDS dealer software to reverse.

### Known Kawasaki Seed-Key Pairs (5-byte, older ECUs only)

| Seed | Key | Source |
|------|-----|--------|
| `13 52 43 64 75` | `63 27 53 67 42` | Arduino forum (Scissor), Z750r |
| `57 48 58 49 58` | `30 20 39 48 74` | Arduino forum (Scissor), Z750r |
| `58 37 48 45 95` | `58 49 57 69 84` | Arduino forum (Scissor), Z750r |

These are **5-byte fixed pairs** from older Kawasaki ECUs (Z750r, Ninja 400, etc.) and do NOT work on the Ninja 7 Hybrid, which uses **6-byte random seeds**. The `security_access_deep.py` script tests these and many algorithmic transforms automatically.

### KDS Diagnostic Hardware

| Part Number | Description | Notes |
|-------------|-------------|-------|
| 57001-1504 | KDS Signal Converter (old) | May not fit Ninja 7 Hybrid connector |
| 57001-1725 | KDS3 Adapter (current) | Current dealer hardware |
| 57001-1843 | Data Link Cable | Specific to 6-pin connector on Ninja 7 Hybrid |
| 99969-6490 | KEI Diagnostic Kit | Current dealer kit (Bluetooth + USB) |
| KDT/DiagSys | Diagnostic software | Free download at kawasaki.diagsys.com — no SecurityAccess |
| KDS3 | Dealer diagnostic software | Has SecurityAccess but dealer-restricted, not publicly available |

### Aftermarket ECU Flash Support

- **Woolich Racing**: No support for Ninja 7 Hybrid
- **FTECU**: No support for Ninja 7 Hybrid

## Key Differences from Z1000SX (kawaduino/aster94)

| Aspect | Z1000SX | Ninja 7 Hybrid |
|--------|----------|---------------|
| RPM formula | (A×255+B)/255×100 | **(A<<8\|B)/4** |
| Temp formula | (value−48)/1.6 | **value − 40** |
| IAP/IAT PIDs | 0x07=IAP, 0x05=IAT | **0x05=IAP, 0x07=IAT** (reversed) |
| SecurityAccess | 5-byte hardcoded pairs | **6-byte random seeds** |
| Drive modes | Not documented | **0x11=SPORT, 0x12=ECO, 0x13=AUTO, 0x16=WALK** |
| EV/Hybrid toggle | N/A | **bit 6 (0x40) in 0x0054/0x0280** |
| Passive broadcasts | Not documented | **27+ CAN IDs** fully decoded |

## Scripts

All scripts use `python-can` with SocketCAN. Key ON with kill switch RUN required.

| Script | Purpose |
|--------|---------|
| `kawasaki_sensor_probe.py` | Continuous KWP2000 sensor reading with logging |
| `kawasaki_can_monitor.py` | Passive CAN monitor — decodes all known broadcast IDs |
| `can_sniffer.py` | Raw CAN sniffer — captures ALL traffic to log file |
| `can_quick_test.py` | Quick connectivity test |
| `can_rapid_probe.py` | Rapid KWP2000 PID probing |
| `can_rev_capture.py` | CAN capture with mode switching |
| `can_correlate.py` | KWP2000 + CAN temperature/voltage correlation |
| `kawasaki_clutch_relearn.py` | KWP2000 session holder for service procedures |
| `kwp2000_explorer.py` | Probes all KWP2000 services and sub-functions |
| `kwp2000_deep_probe.py` | Extended PID probing (0x00-0xBF, high IDs) |
| `kwp2000_routines.py` | Probes Service 0x13 routine IDs |
| `kwp2000_routine_test.py` | Tests specific diagnostic routines |
| `kwp2000_seed_test.py` | SecurityAccess seed-key analysis |
| `security_access_deep.py` | Comprehensive SecurityAccess testing (5 phases: level probing, randomness analysis, known Kawasaki 5-byte pairs, algorithmic transforms, extended timing) |
| `kwp2000_version_info.py` | ECU identification via KWP2000 |
| `alpf_probe.py` | ALPF (auto downshift) detection probe |
| `key_on_capture.py` | Captures CAN IDs that appear at key-on |
| `run_switch_capture.py` | Tests run switch position detection |
| `motor_capture.py` | Motor controller data capture |
| `ecu_decode.py` | Decodes 0x070C ECU identification broadcast |
| `decode_0710.py` | Decodes 0x0710 ECU configuration broadcast |
| `decode_03e3.py` | Detailed analysis of 0x03E3 status message |
| `verify_0280.py` | Verifies 0x0280 format and EV flag position |
| `analyze_0281.py` | Deep analysis of 0x0281 motor/electrical data |
| `temp_correlate.py` | Correlates CAN temps with KWP2000 temps |
| `quick_decode.py` | Quick passive CAN data grab |
| `probe_zeros.py` | Probes zero-value CAN IDs |

## Setup

```bash
# Create venv
python3 -m venv venv
source venv/bin/activate
pip install python-can

# Bring up CAN interface
sudo ip link set can0 up type can bitrate 500000
```

## Connection Info

- **CAN bitrate:** 500kbps
- **ECU Request ID:** 0x764
- **ECU Response ID:** 0x746
- **Protocol:** KWP2000 over CAN (ISO 15765)
- **Session type:** 0x80 (0x81 causes ECU lockout!)
- **After failed sessions:** Key cycle required to reset ECU

## SPORT Mode ECU Update

Kawasaki offers a free ECU update (April 2026) for Ninja 7/Z7 Hybrids:
- Adds automatic shifting in SPORT mode
- Raises EV↔Hybrid switching speed
- 20-30 minutes at any authorized dealer

Verify by comparing 0x070C broadcast data before and after — calibration date and SW version will change.

## KDS Software & SecurityAccess

The Ninja 7 Hybrid's 6-byte random seed SecurityAccess cannot be cracked without the proprietary seed→key algorithm. Options:

1. **Capture seed-key pairs during a dealer visit** — sniff CAN traffic while KDS performs SecurityAccess. Even a few dozen pairs might reveal the algorithm.

2. **Reverse-engineer KDS 3.0 software** — obtain the dealer software (~$200-400 used kit on eBay) and extract the algorithm from its DLLs. The software is Windows-based and likely uses .NET or native libraries.

3. **UnlockECU** (open source) has no Kawasaki algorithms — only European automotive ECUs.

The **KDT (Kawasaki Diagnostic Tool)** app is free from kawasaki.diagsys.com/kdt but only supports M3B ECUs, likely not the Ninja 7 Hybrid's HEV ECU.

## Credits

- **kawaduino** by Tom Mitchell — Z1000SX sensor map and KWP2000 reference
- **aster94/KWP2000** — Arduino KWP2000 library with Kawasaki-specific sensor decoding
- **Scissor (Arduino forum)** — Original 5-byte Kawasaki seed-key pairs (older ECUs only)

## License

MIT — Use at your own risk. Not responsible for damage to your motorcycle.