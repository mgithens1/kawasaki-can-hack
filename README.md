# Kawasaki Ninja 7 Hybrid — CAN Bus Diagnostic Tools

Tools for reverse-engineering and reading live data from the Kawasaki Ninja 7 Hybrid (2024+) ECU via KWP2000-over-CAN (ISO 15765).

## What This Does

These Python scripts communicate with the Ninja 7 Hybrid's ECU through a CAN adapter (SocketCAN) to:
- Read live sensor data (RPM, temperatures, pressure, speed, gear, etc.)
- Read ECU identification and calibration data
- **Passively monitor 27 CAN broadcast IDs** (no ECU requests needed)
- Decode ECU firmware version, part number, and calibration date from broadcast
- Start diagnostic routines
- Probe KWP2000 services and local identifiers

## Confirmed Sensor Map (KWP2000 Service 0x21)

| PID | Sensor | Formula | Notes |
|-----|--------|---------|-------|
| 0x04 | Engine Load | byte × 100/255 % | Confirmed with throttle |
| 0x05 | Intake Air Pressure | byte × 4 × 0.136 kPa | Swings with revs |
| 0x06 | Coolant Temp | byte − 40 °C | Matches dash reading |
| 0x07 | Intake Air Temp | byte − 40 °C | Stable at ambient |
| 0x08 | Reference Value | Static 0x53 | NOT a live sensor |
| 0x09 | Engine RPM | (A<<8\|B) / 4 | **Not** the Z1000SX formula |
| 0x0A | Calibration Value | Static ~733 | NOT motor RPM |
| 0x0B | Gear Position | byte (0=neutral) | From kawaduino |
| 0x0C | Vehicle Speed | byte km/h | Single byte, not 2-byte |
| 0x0D | Vehicle Speed (2-byte) | (A<<8\|B) / 2 kph | Active only with engine on |
| 0x76 | Battery Voltage | byte / 8 ≈ V | ~12.5V at rest |
| 0xB4 | Secondary MAP | byte | Tracks throttle pressure |
| 0x1B | System Voltage | 2-byte ~3915 | ~15.3V with DC-DC |
| 0x1C | Voltage Reference 2 | 2-byte ~3919 | Second voltage ref |
| 0x1D/0x1E | Unknown | byte 0x6E | — |

## Passive CAN Broadcast IDs

The ECU broadcasts data continuously without any request. 27 unique CAN IDs are active with key ON, 27 with engine running (including new 0x0008 startup transient).

| CAN ID | Rate | Label | Notes |
|--------|------|-------|-------|
| 0x0008 | — | Startup Transient | Only 2 msgs at key-on |
| 0x0100 | 100 Hz | Cluster Status | Changes with engine state |
| 0x0111 | 50 Hz | Status Flags | — |
| 0x0112 | 100 Hz | Status Flags | — |
| 0x0120 | 5 Hz | Config Constant | 00 CE 00 00 |
| 0x0121 | 100 Hz | Status Flags | — |
| 0x0125 | 10 Hz | Status | — |
| 0x0174 | 100 Hz | Motor Controller A | Counter in byte[4] |
| 0x0178 | 100 Hz | Motor Controller B | Counter in byte[4] |
| 0x017C | 100 Hz | Motor Controller C | Counter in byte[4] |
| 0x0222 | 50 Hz | Status Flag | 00 20 |
| 0x0271 | 1 Hz | ECU ID Part 1 | ASCII: "ML5CXGA1" |
| 0x0272 | 1 Hz | ECU ID Part 2 | ASCII: "1RDA0435" |
| 0x0273 | 1 Hz | ECU ID Part 3 | ASCII: "8" |
| 0x0280 | 50 Hz | Controller Data | 64 9D 11 00 45 04 |
| 0x0281 | 4 Hz | Motor/Electrical | Fluctuates with engine |
| 0x0282 | 10 Hz | System Voltage | 00 58/59 00 00 |
| 0x0283 | 100 Hz | Status Flags | — |
| 0x0284 | 1 Hz | Temp/Voltage A | Byte[1] decreases with warmup |
| 0x0285 | 4 Hz | Temp/Voltage B | Byte[1] decreases with warmup |
| 0x0050 | 33 Hz | Status | 00 00 00 00 |
| 0x0054 | 49 Hz | Status | 9D 01 00 00 |
| 0x03E3 | 20 Hz | Status | 01 BB 00 00 00 C7 |
| 0x070C | 10 Hz | ECU Identification | ISO-TP multi-frame (see below) |
| 0x0710 | 10 Hz | ECU Data | ISO-TP multi-frame |
| 0x0720 | 10 Hz | Temperatures? | 0F 38 0F 34/35 50×4 |
| 0x0728 | 10 Hz | Controller Data | 0E 00 00 00 00 00 00 |

## ECU Identification Broadcast (CAN ID 0x070C)

The ECU broadcasts its complete identification every second via ISO-TP multi-frame messages. **No SecurityAccess needed** — just listen to the bus.

| Frame | Content | Decoded |
|-------|---------|---------|
| 0x00 | Start marker | All zeros |
| 0x01 | 07 E8 03 15 | **Calibration Date: 2024-03-15** |
| 0x02 | ASCII | SW Version P1: "2102D11" |
| 0x03 | ASCII | SW Version P2: "2202441" |
| 0x04 | ASCII | SW Version P3: "56" |
| 0x05 | 07 D0 | Build: 2000 |
| 0x06 | 00 00 01 00 | Flags: 0x01 |
| 0x07 | ASCII | HW Part: "26105-0" |
| 0x08 | ASCII | HW Part P2: "001" |
| 0x09 | ASCII | **ECU Part: "49245-2"** |
| 0x0A | ASCII | ECU Part P2: "3050000" |
| 0x0B | ASCII | ECU Part P3: "3000" |
| 0x0C-0x14 | Binary | Engine-running only: runtime data, checksums, adaptive values |
| 0x15-0x16 | Zeros | Unused/padding |
| 0xFF | End marker | All zeros |

**Full reconstructed strings:**
- Software: `2102D11220244156`
- Hardware Part: `26105-0001`
- ECU Part: `49245-2655` (matches Service 0x1A result)
- Calibration Date: **2024-03-15**

Frames 0x0C-0x14 only appear when the engine is running and contain dynamic data (runtime counters, calibration checksums, adaptive values).

**Verifying a dealer update:** Capture 0x070C before and after. If the calibration date or software string changes, the update took effect.

## ECU Identification (KWP2000 Service 0x1A)

| Sub-ID | Value |
|--------|-------|
| 0x80 | ML5CXGA11RDA04358 (ECU hardware ID) |
| 0x81 | 49245-2655 (Kawasaki part number) |
| 0x82 | 0xCBE8 (calibration checksum — per-firmware, changes with updates) |
| 0x83 | 0x02 (config/hardware version) |
| 0x84/0x85 | 55-byte calibration tables |

## How This Differs from Z1000SX / Older Kawasaki

| Aspect | Z1000SX (kawaduino) | Ninja 7 Hybrid (ours) |
|--------|---------------------|----------------------|
| RPM formula | (A×255+B)/255×100 or A×100+B | **(A<<8\|B)/4** |
| Coolant temp formula | (value−48)/1.6 | **value−40** |
| IAP/IAT PIDs | 0x07=IAP, 0x05=IAT | **0x05=IAP, 0x07=IAT** (reversed) |
| SecurityAccess | 3 hardcoded 5-byte seed-key pairs | **6-byte random seeds** (not crackable with old pairs) |
| PID 0x08 | ABS Pressure | **Static reference value** (0x53) |
| PID 0x0A | Unknown | **Static calibration value** (~733) |
| PID 0x76 | Not documented | **Battery voltage** (/8) |
| Passive broadcasts | Not documented | **27 CAN IDs** broadcasting continuously |
| ECU firmware version | Not readable without KDS | **Readable from 0x070C broadcast** |

## Supported KWP2000 Services

| Service | Status | Notes |
|---------|--------|-------|
| 0x10 | ✅ | StartDiagnosticSession (0x80 only) |
| 0x13 | ✅ | StartDiagnosticRoutine (routine 0x01 accepted) |
| 0x18 | ✅ | ReadDTCByStatus (0 DTCs found) |
| 0x1A | ✅ | ReadECUIdentification (IDs 0x80-0x85) |
| 0x21 | ✅ | ReadDataByLocalId (see sensor map) |
| 0x27 | ✅ | SecurityAccess (level 0x07 gives 6-byte random seed) |

**Not supported:** 0x11, 0x12, 0x14, 0x17, 0x1B/0x1C/0x1E, 0x22, 0x2F/0x30, 0x34, 0x3B, 0x85/0x86/0x87

## Scripts

### `kawasaki_sensor_probe.py` (v3.1)
Continuous sensor reading with logging. Reads all known PIDs in a loop and decodes values.

```bash
python3 kawasaki_sensor_probe.py
```

Logs to `~/Downloads/can-logs/sensor_probe_YYYYMMDD_HHMMSS.txt`

### `kawasaki_can_monitor.py` (v1.0) — NEW
**Passive CAN bus monitor** — just listens, no ECU requests. Decodes all 27 known broadcast IDs in real-time. Automatically detects and prints ECU firmware version from 0x070C broadcast.

```bash
python3 kawasaki_can_monitor.py
```

Shows state changes (★ marker) and prints ECU identification on startup. Prints summary on exit including motor controller min/max values and message counts.

### `can_sniffer.py` — NEW
Raw CAN bus sniffer. Captures ALL traffic (including unknown IDs) to a log file for analysis.

```bash
python3 can_sniffer.py [duration_seconds] [output_file]
```

Default: 60 seconds, log to `can_sniffer_YYYYMMDD_HHMMSS.log`. Use for discovering new PIDs and analyzing broadcast patterns.

### `can_quick_test.py` / `can_rapid_probe.py` — NEW
Quick connectivity test and rapid PID probing utilities.

### `kawasaki_clutch_relearn.py` (v5.0)
Opens a KWP2000 diagnostic session and holds it. Can be used as a starting point for clutch relearn or other service procedures.

### `kwp2000_explorer.py`
Probes all KWP2000 services and sub-functions to discover what the ECU supports.

### `kwp2000_deep_probe.py`
Extended probing of ECU IDs (0x1A sub-IDs 0x00-0x9F), high local IDs (0xA0-0xBF), gap IDs (0x70-0x9F), and other services.

### `kwp2000_routines.py` / `kwp2000_routine_test.py`
Probes Service 0x13 (StartDiagnosticRoutine) with routine IDs 0x00-0xFF.

### `kwp2000_seed_test.py`
Tests SecurityAccess seed-key combinations. Documents that the Ninja 7 Hybrid uses 6-byte random seeds (not the old 5-byte hardcoded Kawasaki pairs).

## Requirements

- Python 3.8+
- `python-can` package: `pip install python-can`
- CAN adapter with SocketCAN support (e.g., CANable, PCAN-USB, or any SocketCAN-compatible adapter)
- Kawasaki Ninja 7 Hybrid with key ON and kill switch RUN

## Setup

```bash
# Create venv
python3 -m venv venv
source venv/bin/activate
pip install python-can

# Bring up CAN interface (adjust for your adapter)
sudo ip link set can0 up type can bitrate 500000
```

## Connection Info

- **CAN bitrate:** 500kbps
- **ECU Request ID:** 0x764
- **ECU Response ID:** 0x746
- **Protocol:** KWP2000 over CAN (ISO 15765)
- **Diagnostic session:** 0x80

## SecurityAccess

The Ninja 7 Hybrid ECU uses **6-byte random seeds** for SecurityAccess (Service 0x27, level 0x07), unlike older Kawasaki ECUs which used 5-byte hardcoded seed-key pairs. After requesting a seed, you get one attempt to send the correct key before the ECU locks (NRC 0x33). Key cycling resets the lock.

All known algorithms (XOR, NOT, addition, known pairs, identity) have been tried without success. Reverse engineering the KDS (Kawasaki Diagnostic System) software would be needed to extract the seed→key algorithm.

## SPORT Mode ECU Update

Kawasaki released an April 2026 ECU update for Ninja 7/Z7 Hybrids that:
- Adds automatic shifting in SPORT mode
- Raises EV↔Hybrid mode switching speed
- **Free at authorized dealers** — call with VIN, takes 20-30 minutes

To verify the update took effect:
1. Capture 0x070C broadcast data before the dealer visit
2. Get the update
3. Capture 0x070C again — if the calibration date or software string changes, the update worked
4. The calibration checksum (Service 0x1A, sub 0x82 = 0xCBE8) should also change

## Credits

- **kawaduino** by Tom Mitchell — Z1000SX sensor map and KWP2000 reference implementation
- **aster94/KWP2000** — Arduino KWP2000 library with Kawasaki-specific sensor decoding
- **Scissor (Arduino forum)** — Discovered the 3 hardcoded Kawasaki seed-key pairs (older ECUs only)

## License

MIT — Use at your own risk. Modifying ECU parameters or running diagnostic routines can affect vehicle operation. The authors are not responsible for any damage to your motorcycle.