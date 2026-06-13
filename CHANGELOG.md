# Changelog

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