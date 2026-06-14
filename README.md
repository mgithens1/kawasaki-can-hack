# Kawasaki Ninja 7 Hybrid — CAN Bus Reverse Engineering

Complete documentation and tools for reverse-engineering the Kawasaki Ninja 7 Hybrid (2024+) ECU via KWP2000-over-CAN (ISO 15765) and passive CAN bus monitoring.

## What This Project Is

The Ninja 7 Hybrid is Kawasaki's first hybrid motorcycle. Its ECU uses the KWP2000 diagnostic protocol over CAN bus, with proprietary extensions. This project documents every CAN message and KWP2000 service we've discovered through reverse engineering — **27 passive CAN broadcast IDs fully decoded, 200+ KWP2000 PIDs probed, and drive mode encoding cracked**.

No SecurityAccess required for passive monitoring and basic diagnostics. No dealer tools needed — just a CAN adapter and these scripts.

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
- **Run switch position** is NOT broadcast on CAN bus — hardware starter interlock only

### Passive CAN Broadcast IDs — Fully Decoded

27+ unique CAN IDs are active with key ON, no ECU request needed.

| CAN ID | Rate | Content | Notes |
|--------|------|---------|-------|
| 0x0050 | 33 Hz | Ride mode | byte[0]: 0=ECO/OFF, 1=HYBRID, 2=SPORT |
| 0x0054 | 50 Hz | Ride mode + EV | byte[0] EV flag (bit 6: 0x40), byte[1] mode |
| 0x0100 | 100 Hz | Cluster status | Zeros with key ON, active with engine |
| 0x0111 | 50 Hz | Status flags | Zeros with key ON |
| 0x0112 | 100 Hz | Status flags | Zeros with key ON |
| 0x0120 | ~1 Hz | Config constant | 00 CE 00 00 |
| 0x0121 | 100 Hz | Gear position | 00 00=Neutral, 01 00=In gear |
| 0x0125 | 10 Hz | Status | Zeros with key ON |
| 0x0174 | 100 Hz | Motor Controller A | Rapidly changing |
| 0x0178 | 100 Hz | Motor Controller B | Rapidly changing |
| 0x017C | 100 Hz | Motor Controller C | Rapidly changing |
| 0x0222 | 50 Hz | Status flag | 0x0020 = key ON |
| 0x0271 | 1 Hz | ECU ID part 1 | ASCII: "ML5CXGA1" |
| 0x0272 | 1 Hz | ECU ID part 2 | ASCII: "1RDA0435" |
| 0x0273 | 1 Hz | ECU ID part 3 | Combined: ML5CXGA11RDA04358 |
| 0x0280 | 50 Hz | Full status | byte[0]=0x64(const), byte[1]=EV, byte[2]=mode, byte[4]=gear, byte[5]=engine |
| 0x0281 | 4 Hz | Motor/electrical | Varies with engine state |
| 0x0282 | 10 Hz | Battery voltage | byte[1] / 8 = volts |
| 0x0283 | 100 Hz | Status flags | Zeros with key ON |
| 0x0284 | ~0.5 Hz | Temperature A | Drifts, multiple temp bytes |
| 0x0285 | ~4 Hz | Temperature B | Similar to 0x0284 |
| 0x03E3 | 20 Hz | ECU config | STATIC: 01 BB 00 00 00 C7 |
| 0x070C | ~1 Hz | ECU ID broadcast | ISO-TP multi-frame, see below |
| 0x0710 | ~10 Hz | ECU config | 79-frame broadcast |
| 0x0720 | 1 Hz | 6 temperature sensors | See temp table below |
| 0x0728 | ~1 Hz | Heartbeat | 0x0E 00 00 00 00 00 00 00 |

### ECU Identification (0x070C) — No SecurityAccess Needed

Broadcast every ~1 second via ISO-TP multi-frame. Just listen.

| Frame | Content | Decoded |
|-------|---------|---------|
| 0x01 | Date bytes | Calibration date: 2024-03-21 |
| 0x02-0x04 | ASCII | SW version: `2102D11220244156` |
| 0x05 | 0x07D0 | Build number: 2000 |
| 0x06 | 0x0001 | Config version |
| 0x07-0x08 | ASCII | HW part: `26105-0001` |
| 0x09-0x0B | ASCII | ECU part: `49245-230500000` |
| 0x0C-0x11 | Binary | **LIVE data** (changes between captures) |
| 0xFF | End marker | All zeros |

**Verifying a dealer ECU update:** Compare 0x070C before and after. If calibration date or SW version changes, the update took effect.

**Current firmware:** SW `2102D11220244156`, calibrated 2024-03-15, ECU part 49245-2655

### Temperature Sensors (0x0720)

| Sensor | Formula | Key ON (engine off) |
|--------|---------|---------------------|
| IAT1 | (byte[0]<<8 \| byte[1]) / 256 °C | ~15°C (ambient) |
| IAT2 | (byte[2]<<8 \| byte[3]) / 256 °C | ~15°C (ambient) |
| T3 | byte[4] − 40 °C | ~38°C (motor/inverter) |
| T4 | byte[5] − 40 °C | ~37°C |
| T5 | byte[6] − 40 °C | ~37°C |
| T6 | byte[7] − 40 °C | ~37°C |

### Battery Voltage (0x0282)

`byte[1] / 8 = volts` — confirmed matching KWP2000 PID 0x76 (100 → 12.5V)

## KWP2000 Active Diagnostics

### Working Services (No SecurityAccess Required)

| Service | Description | Notes |
|---------|-------------|-------|
| 0x10 | Session control | Type 0x80 only — 0x81 causes lockout |
| 0x13 | Routine control | Routine 0x01 starts successfully |
| 0x18 | Read DTCs | Confirmed zero DTCs |
| 0x1A | ECU identification | Part number, serial, calibration |
| 0x21 | Read data by local ID | 200+ PIDs respond |
| 0x3E | Tester present | Keeps session alive |

**Not supported:** 0x11, 0x12, 0x14, 0x17, 0x22 (UDS), 0x2F/0x30, 0x34, 0x3B, 0x85/0x86/0x87

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
| 0x0B | Gear position | 0=neutral, else in gear |
| 0x0C | Vehicle speed | byte km/h |
| 0x0D | Vehicle speed | (A<<8\|B)/2 kph (2-byte) |
| 0x76 | Battery voltage | value / 8 = V |
| 0x1B | System voltage A | (A<<8\|B) / 256 ≈ 15.3V |
| 0x1C | System voltage B | (A<<8\|B) / 256 ≈ 15.3V |
| 0xB4 | Secondary MAP | Tracks throttle |
| 0x44-0x4F | Hybrid config | Static values (don't change with mode) |
| 0x74 | Temperature sensor | Drifts slowly (0x51-0x5B) |
| 0xB1 | Calibration constant | 0xCB (static) |

### SecurityAccess — Exhaustively Tested (70 Attempts)

**All 70 key attempts returned NRC 0x33 (accessDenied).**

| Detail | Value |
|--------|-------|
| Seed request | `0x27 0x07` → 6-byte seed |
| Key send | `0x27 0x06` (NOT 0x08 — returns NRC 0x12) |
| Seed format | 5 random bytes + fixed `0x34` suffix |
| Attempts per key cycle | 1 (lockout after wrong key) |
| Lockout reset | Key cycle required |

| Phase | Attempts | Algorithms Tested |
|-------|----------|-------------------|
| 1 | 23 | Known Kawasaki 5-byte pairs (padded), identity, XOR (0xFF/0xAA/0x55/0x34), NOT, reverse, inc, dec, add/sub, nibble swap, shift |
| 2 | 27 | Swap pairs, byte rotations, cumulative XOR, chain XOR, carry/borrow, Kawasaki pair offsets, XOR with byte5, multiply, 5-byte variants |
| 3 | 19 | CRC-16/CCITT, CRC-16/ARC, CRC-8, CRC-32, VW-style, AES S-box, S-box variants, LCG, checksum, double XOR pass |

**Conclusion:** The algorithm is proprietary. With 2^48 possible keys and one test per key cycle, brute force is infeasible. Requires KDS dealer software, ECU firmware dump, or dealer CAN capture.

### Known Kawasaki Seed-Key Pairs (5-byte, older ECUs only)

| Seed | Key | Source |
|------|-----|--------|
| `13 52 43 64 75` | `63 27 53 67 42` | Arduino forum, Z750r |
| `57 48 58 49 58` | `30 20 39 48 74` | Arduino forum, Z750r |
| `58 37 48 45 95` | `58 49 57 69 84` | Arduino forum, Z750r |

These are 5-byte **fixed** pairs from older Kawasaki ECUs (Z750r, Ninja 400). The Ninja 7 Hybrid uses **6-byte random seeds** — these pairs don't work.

## Scripts

### Main Tools (in `scripts/`)

| Script | Purpose |
|--------|---------|
| `kawasaki_clutch_relearn.py` | Open diagnostic session, read ECU ID + DTCs, hold session for clutch relearn |
| `kawasaki_sensor_probe.py` | Continuous KWP2000 sensor reading with logging |
| `kawasaki_can_monitor.py` | Passive CAN monitor — decodes all known broadcast IDs in real-time |
| `can_sniffer.py` | Raw CAN sniffer — captures ALL traffic to log file |

### Research Scripts (in `scripts/research/`)

One-off tools used during reverse engineering. May need key cycles between runs due to ECU lockout behavior.

| Script | Purpose |
|--------|---------|
| `try_key_06.py` | SecurityAccess key attempt (sub-function 0x06) |
| `try_key_phase2.py` | Phase 2: multi-byte transforms |
| `try_key_phase3.py` | Phase 3: CRC, S-box, LCG, VW-style |
| `security_access_deep.py` | 5-phase SecurityAccess analysis |
| `one_seed.py` | Single seed request (one per key cycle) |
| `minimal_seed_test.py` | Minimal seed request, no key attempts |
| `seed_behavior_test.py` | Seed behavior analysis |
| `seed_fresh_session.py` | Test if seeds change between sessions |
| `test_multi_attempt.py` | Test multiple key attempts per session |
| `test_subfunctions.py` | Probe SecurityAccess sub-functions |
| `kwp2000_explorer.py` | Probe all KWP2000 services and sub-functions |
| `kwp2000_deep_probe.py` | Extended PID probing |
| `kwp2000_routines.py` | Probe Service 0x13 routine IDs |
| `kwp2000_routine_test.py` | Test specific diagnostic routines |
| `kwp2000_seed_test.py` | Seed-key analysis |
| `kwp2000_version_info.py` | ECU identification via KWP2000 |
| `can_quick_test.py` | Quick connectivity test |
| `can_rapid_probe.py` | Rapid KWP2000 PID probing |
| `can_rev_capture.py` | CAN capture with mode switching |
| `can_correlate.py` | KWP2000 + CAN correlation |
| `alpf_probe.py` | ALPF/auto-downshift probe |
| `key_on_capture.py` | Capture CAN IDs at key-on |
| `run_switch_capture.py` | Test run switch position |
| `motor_capture.py` | Motor controller data capture |
| `ecu_decode.py` | Decode 0x070C ECU broadcast |
| `decode_0710.py` | Decode 0x0710 config broadcast |
| `decode_03e3.py` | Detailed 0x03E3 analysis |
| `verify_0280.py` | Verify 0x0280 format and EV flag |
| `analyze_0281.py` | Deep 0x0281 analysis |
| `temp_correlate.py` | CAN/KWP2000 temp correlation |
| `quick_decode.py` | Quick passive CAN data grab |
| `probe_zeros.py` | Probe zero-value CAN IDs |

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
- Verify by comparing 0x070C broadcast before and after

## Paths Forward for SecurityAccess

| Option | Difficulty | Notes |
|--------|-----------|-------|
| KDS3 software reverse engineering | Medium | Find/buy dealer software, extract algorithm from DLLs |
| ECU firmware dump | High | Requires hardware tools, disassembly expertise |
| Dealer CAN capture | Medium | Sniff seed-key pairs during dealer visit |
| UnlockECU | N/A | No Kawasaki algorithms, European ECUs only |
| Woolich Racing / FTECU | N/A | No Ninja 7 Hybrid support |

## KDS Diagnostic Hardware

| Part Number | Description | Notes |
|-------------|-------------|-------|
| 57001-1725 | KDS3 Adapter | Current dealer hardware |
| 57001-1843 | Data Link Cable | Ninja 7 Hybrid 6-pin connector |
| 99969-6490 | KEI Diagnostic Kit | Current dealer kit (Bluetooth + USB) |
| KDT/DiagSys | Free diagnostic software | No SecurityAccess, M3B ECUs only |

## Key Differences from Z1000SX (kawaduino/aster94)

| Aspect | Z1000SX | Ninja 7 Hybrid |
|--------|----------|---------------|
| RPM formula | (A×255+B)/255×100 | **(A<<8\|B)/4** |
| Temp formula | (value−48)/1.6 | **value − 40** |
| IAP/IAT PIDs | 0x07=IAP, 0x05=IAT | **0x05=IAP, 0x07=IAT** (reversed) |
| SecurityAccess | 5-byte hardcoded pairs | **6-byte random seeds** |
| Drive modes | Not documented | **0x11=SPORT, 0x12=ECO, 0x13=AUTO, 0x16=WALK** |
| EV/Hybrid toggle | N/A | **bit 6 (0x40) in 0x0054/0x0280** |

## Credits

- **kawaduino** by Tom Mitchell — Z1000SX sensor map and KWP2000 reference
- **aster94/KWP2000** — Arduino KWP2000 library with Kawasaki-specific sensor decoding
- **Scissor (Arduino forum)** — Original 5-byte Kawasaki seed-key pairs (older ECUs only)

## License

MIT — Use at your own risk. Not responsible for damage to your motorcycle.