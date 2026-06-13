# Kawasaki Ninja 7 Hybrid — CAN Bus Diagnostic Tools

Tools for reverse-engineering and reading live data from the Kawasaki Ninja 7 Hybrid (2024+) ECU via KWP2000-over-CAN (ISO 15765).

## What This Does

These Python scripts communicate with the Ninja 7 Hybrid's ECU through a CAN adapter (SocketCAN) to:
- Read live sensor data (RPM, temperatures, pressure, speed, gear, etc.)
- Read ECU identification and calibration data
- Start diagnostic routines
- Probe KWP2000 services and local identifiers

## Confirmed Sensor Map (Ninja 7 Hybrid)

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

### How This Differs from Z1000SX / Older Kawasaki

| Aspect | Z1000SX (kawaduino) | Ninja 7 Hybrid (ours) |
|--------|---------------------|----------------------|
| RPM formula | (A×255+B)/255×100 or A×100+B | **(A<<8\|B)/4** |
| Coolant temp formula | (value−48)/1.6 | **value−40** |
| IAP/IAT PIDs | 0x07=IAP, 0x05=IAT | **0x05=IAP, 0x07=IAT** (reversed) |
| SecurityAccess | 3 hardcoded 5-byte seed-key pairs | **6-byte random seeds** (not crackable with old pairs) |
| PID 0x08 | ABS Pressure | **Static reference value** (0x53) |
| PID 0x0A | Unknown | **Static calibration value** (~733) |
| PID 0x76 | Not documented | **Battery voltage** (/8) |

## ECU Identification

| Sub-ID | Value |
|--------|-------|
| 0x80 | ML5CXGA11RDA04358 (ECU hardware ID) |
| 0x81 | 49245-2655 (Kawasaki part number) |
| 0x82 | 0xCBE8 (calibration checksum) |
| 0x83 | 0x02 (config/hardware version) |
| 0x84/0x85 | 55-byte calibration tables |

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

### `kawasaki_clutch_relearn.py` (v5.0)
Opens a KWP2000 diagnostic session and holds it. Can be used as a starting point for clutch relearn or other service procedures.

```bash
python3 kawasaki_clutch_relearn.py
```

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

## Credits

- **kawaduino** by Tom Mitchell — Z1000SX sensor map and KWP2000 reference implementation
- **aster94/KWP2000** — Arduino KWP2000 library with Kawasaki-specific sensor decoding
- **Scissor (Arduino forum)** — Discovered the 3 hardcoded Kawasaki seed-key pairs (older ECUs only)

## License

MIT — Use at your own risk. Modifying ECU parameters or running diagnostic routines can affect vehicle operation. The authors are not responsible for any damage to your motorcycle.