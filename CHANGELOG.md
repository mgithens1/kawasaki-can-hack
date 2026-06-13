# Changelog

## [2026-06-13] Major Update — Full CAN Bus Decode

### Drive Mode Encoding — Fully Decoded
- **SPORT = 0x11** (boot default), **ECO = 0x12**, **ECO+AUTO = 0x13**, **WALK = 0x16**
- **EV/Hybrid toggle**: bit 6 (0x40) in 0x0054 byte[0] and 0x0280 byte[1]
- 0x9D = HYBRID (engine ready), 0x5D = EV (electric only)
- **CRITICAL FIX**: 0x0280 byte[0] = 0x64 is a CONSTANT, NOT the EV flag — EV flag is in byte[1]
- **"HYBRID" is NOT a separate mode** — it's part of the mode name (SPORT-HYBRID, ECO-HYBRID)
- **ALPF (auto downshift)** NOT on CAN bus — requires SecurityAccess
- **Run switch position** NOT on CAN bus — hardware starter interlock only

### Passive CAN Bus — 27+ IDs Fully Documented
- **0x070C**: ECU identification broadcast (SW version, HW part, build date, calibration) — no SecurityAccess needed
- **0x0710**: 79-frame ECU configuration broadcast (SW version, battery voltage, build number)
- **0x0720**: 6 temperature sensors (IAT1, IAT2, T3-T6 using value-40°C formula)
- **0x0282**: Battery voltage (byte[1]/8 = volts, matches KWP2000 PID 0x76 exactly)
- **0x0280**: Full ride mode + EV + gear + engine state
- **0x0281**: Motor/electrical data (needs engine running to decode)
- **0x0284/0x0285**: Temperature tracking (drifts as bike cools)
- **0x03E3**: ECU status/config (STATIC, 6 bytes: 01 BB 00 00 00 C7)
- **0x0271/0272/0273**: ECU ID fragments (ML5CXGA11RDA04358)
- **0x0728**: Heartbeat/alive (0x0E 00 00 00 00 00 00)
- **0x0004**: Key-on/session init (values change between sessions)
- **0x0120**: Drifting value (byte[1] changes as bike cools)
- **0x0174/0178/017C**: Motor controllers at 100 Hz (need engine to decode)
- **0x0100, 0x0111, 0x0112, 0x0125, 0x0283**: All zeros with engine off — may activate with engine

### KWP2000 Correlations Confirmed
- CAN 0x0282 byte[1] = KWP2000 PID 0x76 raw value (both give 100 → 12.5V)
- CAN 0x0720 T3-T6 = motor/inverter temps (37-38°C), NOT coolant (29°C via KWP2000)
- CAN 0x0284 bytes[4:7] = additional temps using value-40 formula (41°C, 48°C, 40°C)
- KWP2000 session type 0x80 works, 0x81 causes lockout (needs key cycle to reset)

### ECU Part Number Discrepancy
- 0x070C broadcast shows part 49245-230500000
- KWP2000 Service 0x1A shows part 49245-2655
- Likely different part number formats (calibration vs hardware)

### Scripts Added
- `ecu_decode.py`, `decode_0710.py`, `decode_03e3.py`, `verify_0280.py`
- `analyze_0281.py`, `temp_correlate.py`, `quick_decode.py`, `probe_zeros.py`
- `can_correlate.py`, `motor_capture.py`, `key_on_capture.py`, `run_switch_capture.py`
- `alpf_probe.py`, `kwp2000_version_info.py`

### KDS Software & SecurityAccess Research
- Ninja 7 Hybrid uses 6-byte random seeds — cannot crack without dealer software
- KDS 3.0 kit: ~$200-400 used on eBay (signal converter + cables)
- KDT app (free from kawasaki.diagsys.com) only supports M3B ECUs
- UnlockECU has zero Kawasaki algorithms
- Best path: capture seed-key pairs during dealer SPORT mode ECU update

## [2026-06-13] Initial Release

### Discovered & Documented for Kawasaki Ninja 7 Hybrid
- **Confirmed sensor PID map** with live data: RPM, coolant temp, IAT, IAP, engine load, gear position, vehicle speed, battery voltage
- **Corrected formulas** from Z1000SX reference: RPM uses (A<<8|B)/4 (not kawaduino or aster94 formulas), coolant temp uses value−40 (not (value−48)/1.6)
- **Identified new PIDs**: 0x76 (battery voltage), 0x1B/0x1C (system voltage), 0xB4 (secondary MAP)
- **Debunked old PID labels**: 0x08 is NOT oil temp (static 0x53), 0x0A is NOT motor RPM (static ~733)
- **ECU identification**: Part number 49245-2655, calibration checksums, 55-byte calibration tables
- **KWP2000 service mapping**: Documented all supported/rejected services
- **SecurityAccess analysis**: Confirmed 6-byte random seeds (not old 5-byte hardcoded Kawasaki pairs), documented all access levels
- **Diagnostic routine 0x01**: Confirmed working (StartDiagnosticRoutine)
- **ISO-TP multi-frame support**: Fixed original script's lack of flow control frames
- **Comprehensive scripts**: Sensor probe, clutch relearn, KWP2000 service explorer, routine tester, seed-key tester