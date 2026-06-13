# Kawasaki Ninja 7 Hybrid — CAN Bus Decoded IDs

## Passive CAN Broadcasts (No ECU Request Needed)

### Drive Mode & Status

| CAN ID | Rate | Content | Formula |
|--------|------|---------|---------|
| 0x0050 | 33 Hz | Ride mode | byte[0]: 0=ECO/OFF, 1=HYBRID, 2=SPORT |
| 0x0054 | 50 Hz | Ride mode + EV | byte[0]: EV flag (bit 6: 0x40), byte[1]: mode (1=SPORT, 2=ECO, 3=ECO+AUTO, 6=WALK) |
| 0x0280 | 50 Hz | Full status | byte[0]=0x64(constant), byte[1]: EV flag (bit 6: 0x40 from 0x0054), byte[2]: mode (0x11=SPORT, 0x12=ECO, 0x13=ECO+AUTO, 0x16=WALK, 0x19=KEY-OFF), byte[4]: gear (0x45=N, 0x55=in gear), byte[5]: 0x04=engine/HEV, 0x00=EV/startup |
| 0x0121 | 100 Hz | Gear position | byte[0:1]: 00 00=Neutral, 01 00=In gear |
| 0x0222 | 50 Hz | Status flag | 0x0020 = key ON |
| 0x0120 | ~1 Hz | Drifting value | byte[1] drifts between sessions (0xCE→0xB4→0xB2), likely temperature/voltage ADC |
| 0x0100 | 100 Hz | Cluster/placeholder | All zeros with key ON/engine off — may come alive with engine running |
| 0x0111 | 50 Hz | Unknown placeholder | All zeros — may come alive with engine running |
| 0x0112 | 100 Hz | Unknown placeholder | All zeros — may come alive with engine running |
| 0x0125 | 10 Hz | Unknown placeholder | All zeros — may come alive with engine running |

### EV/Hybrid Toggle Encoding
- 0x0054 byte[0] and 0x0280 byte[1] contain the EV flag
- 0x9D = HEV (engine ready), 0x5D = EV (electric only)
- 0x95/0x55 = transient during mode switch
- 0x0280 byte[0] = 0x64 (constant, NOT the EV flag — EV flag is in byte[1])
- 0x1D = startup state

### Run Switch Position
- **NOT broadcast on CAN bus**
- Tested both ON and OFF with key ON — all IDs identical
- Run switch is a hardware starter interlock only, not CAN-reported

### Temperature Sensors

| CAN ID | Rate | Content | Formula |
|--------|------|---------|---------|
| 0x0720 | 1 Hz | 6 temperature sensors | IAT1=(b0b1)/256°C, IAT2=(b2b3)/256°C, T3=b4-40°C, T4=b5-40°C, T5=b6-40°C, T6=b7-40°C |
| 0x0284 | ~0.5 Hz | Temp tracking A | byte[1]: slowly drifting (cooling?), bytes[4:7]: 3 temps using value-40°C formula |
| 0x0285 | ~4 Hz | Temp tracking B | byte[1]: drifting (0xEE-0xF2 range), byte[2]=0x00 |

- 0x0720 IAT values (~15°C) match ambient, T3-T6 (~38°C) likely motor/inverter temps
- 0x0284 byte[1] has been observed drifting from 0xF9→0xE9 over multiple sessions (cooling?)

### Voltage

| CAN ID | Rate | Content | Formula |
|--------|------|---------|---------|
| 0x0282 | 10 Hz | Battery voltage | byte[1] = KWP2000 PID 0x76 raw value; voltage = byte[1] / 8 (e.g., 100 → 12.5V) |

### ECU Identification (0x070C, multi-frame ISO-TP)

Broadcast every ~1 second, 23+ unique frames:

| Frame | Content | Decoded |
|-------|---------|---------|
| 0x01 | `07 E8 03 15` | Date: 2024-03-21 (0x07E8=2024, 0x03=Mar, 0x15=21) |
| 0x02-0x04 | ASCII | SW version: `2102D11220244156` |
| 0x05 | `07 D0` | Build number: 2000 |
| 0x06 | `00 00 01` | Config version: 0x02 (or build sequence) |
| 0x07-0x08 | ASCII | HW part: `26105-0001` |
| 0x09-0x0B | ASCII | ECU part: `49245-230500000` (differs from KWP2000's 49245-2655) |
| 0x0C-0x11 | Binary | **LIVE data** (values change between captures!) |
| 0x12-0x14 | Mixed | More live data + ASCII fragments |
| 0x15-0x16 | Zeros | Padding/empty |
| 0xFF | Zeros | End marker |

**Note:** Frames 0x0C-0x11 change between captures — they contain live sensor data, NOT static calibration. The "calibration checksum 0xCBE8" from KWP2000 may be in a different location.

### ECU ID Frames (0x0271, 0x0272, 0x0273)

| CAN ID | Content | Decoded |
|--------|---------|---------|
| 0x0271 | `4d4c354358474131` | ASCII: `ML5CXGA1` (ECU ID part 1) |
| 0x0272 | `3152444130343335` | ASCII: `1RDA0435` (ECU ID part 2) |
| 0x0273 | `38` | ECU ID part 3 (serial suffix: `8` or value `56`) |

Combined: `ML5CXGA11RDA04358` — matches KWP2000 Service 0x1A result

### Motor/Electrical (0x0281, 4 Hz)

Format: `D2 xx D1 yy 00 zz 3B64` (changing to `3C64` in some sessions)

| Byte | Value Range | Notes |
|------|-------------|-------|
| 0 | 0xD2 (constant) | Message type ID |
| 1 | 0x61-0xB8 (97-184) | Varies widely — possibly current or torque offset |
| 2 | 0xD0-0xD1 | Mostly constant, rarely flickers to 0xD0 |
| 3 | 0x05-0xF3 (5-243) | Varies widely with byte[1] — possibly power or energy |
| 4 | 0x00 (constant) | — |
| 5 | 0x0A-0x12 (10-18) | Slow counter or sub-state |
| 6-7 | 0x3B64 or 0x3C64 | Constant within session, changes between sessions |

- bytes[6:7] changed from 0x3C64 (15460) to 0x3B64 (15204) between sessions — likely a checksum or session ID
- No clear correlation found between byte[1] and bytes[3:4] with engine OFF
- Needs engine running at known RPMs to decode

### Other Status IDs

| CAN ID | Rate | Content | Notes |
|--------|------|---------|-------|
| 0x03E3 | 20 Hz | ECU status/config | 6 bytes: `01 BB 00 00 00 C7`. b01=443 (build/config ID?), byte[5]=0xC7 (checksum?). STATIC during session |
| 0x0728 | ~1 Hz | Heartbeat/alive | 8 bytes: `0E 00 00 00 00 00 00 00`. 0x0E=14 — module ID or counter. STATIC |
| 0x0283 | 100 Hz | Unknown placeholder | All zeros — may come alive with engine running |
| 0x0004 | One-shot | Key-on/session init | `00 08 00 00 00 00 75 00` — byte[1] and byte[6] change between sessions. Appears once at key-on |
| 0x0710 | ~10 Hz | ECU configuration | 79-frame broadcast, mostly 0xFF padding. See detailed table below |

### Motor Controller (0x0174/0178/017C, 100 Hz each)

Three synchronized messages broadcasting continuously at 100 Hz. Format partially decoded:

**0x0174 format:** `XX XX XX XX XX XX YY ZZ`
- XX bytes: appear to be 16-bit signed values with high byte first
- YY: appears to be a counter/sequence
- ZZ: appears to be a checksum

**Needs engine running at known RPMs to decode.** These are the highest-value decode targets — likely RPM, torque, motor current, and/or battery voltage/current.

### ECU Configuration Broadcast (0x0710)

79-frame broadcast at ~10 Hz. Mostly 0xFF padding. Key data frames:

| Frame | Raw Data | Content | Notes |
|-------|----------|---------|-------|
| 0x00 | `00 32 31 30 32 44 31 31` | ASCII: "2102D11" | SW version part 1 |
| 0x10 | `10 32 32 30 32 34 34 31` | ASCII: "2202441" | SW version part 2 |
| 0x20 | `20 35 36 00 00 00 00 00` | ASCII: "56" + null | SW version part 3 |
| 0x30 | `30 64 00 08 00 06 XX YY` | Voltage=0x64=100(12.5V), config, checksum | XX YY is CRC/checksum |
| 0x60 | `60 00 04 00 00 00 00 00` | Count/version: 4 | |
| 0x70 | `70 00 00 00 06 07 00 00` | Config values: 6, 7 | Possibly ECU feature counts |
| 0x80 | `80 00 00 00 00 00 03 22` | Build/version: 0x0322=802 | |
| 0x90 | `90 32 12 00 00 00 00 00` | Identifier: 0x3212=12818 | Possible part number |
| 0xA0 | All zeros | Placeholder | |
| 0xB0 | `B0 00 00 22 XX YY 00 00` | Config: 0x0022=34, checksum XX YY | XX YY is CRC/checksum |
| 0xC0 | `C0 00 00 00 03 30 2F 08` | Config values | |
| 0xCD | All zeros | End marker | |

- Full SW version: "2102D11220244156" (concatenated from frames 0x00+0x10+0x20)
- Frame 0x30 byte[1] = battery voltage raw value (100 → 12.5V), matches 0x0282 and KWP2000 PID 0x76
- All other data is static configuration; only checksum bytes in 0x30 and 0xB0 change between captures
- Structure uses upper nibble of frame index as "group" (0x0_, 0x1_, etc.), lower nibble as offset

## KWP2000 Active Diagnostics (ECU Request Required)

### Working Services
- 0x10 (Session): Must use type 0x80. Type 0x81 causes lockout until key cycle.
- 0x13 (Routines): Service 0x01 starts successfully
- 0x18 (DTC): Reads diagnostic trouble codes
- 0x1A (ECU ID): Returns part number, ECU ID, calibration data
- 0x21 (Data Read): 200+ PIDs respond

### Key PIDs (Service 0x21)

| PID | Content | Formula |
|-----|---------|---------|
| 0x06 | Coolant temp | value - 40 = °C |
| 0x07 | IAT | value - 40 = °C |
| 0x09 | RPM | (byte[3]<<8 \| byte[4]) / 4 |
| 0x0A | Static calibration | ~733, not motor RPM |
| 0x76 | Battery voltage | value / 8 = V |
| 0x1B | System voltage A | (byte[3]<<8 \| byte[4]) / 256 ≈ 15.3V |
| 0x1C | System voltage B | (byte[3]<<8 \| byte[4]) / 256 ≈ 15.3V |
| 0x44-0x4F | Hybrid config | Static, don't change with mode/ALPF |
| 0x74 | Temperature sensor | Drifts slowly (0x51-0x5B), not ALPF |
| 0xB1 | Calibration constant | 0xCB (static) |

### Blocked by SecurityAccess
- VIN, SW version, ALPF state, SecurityAccess seed-key algorithm
- Need KDS dealer software or seed-key capture to unlock

## Key Differences from Z1000SX (aster94/kawaduino)
- RPM formula: (A<<8|B)/4, NOT kawaduino or aster94 formulas
- Temp formula: value − 40, NOT (value−48)/1.6
- 0x05=IAP and 0x07=IAT (reversed from aster94 labels)
- SecurityAccess uses 6-byte random seeds, not 5-byte hardcoded pairs
- Drive mode encoding: 0x11=SPORT, 0x12=ECO (NOT the other way around)


**KWP2000 readings:**
- Coolant: 29°C (raw=69, formula: raw-40)
- IAT: 31°C (raw=71, formula: raw-40)
- Battery voltage: 12.5V (raw=100, formula: raw/8)

**CAN 0x0720:**
- IAT1/IAT2: ~15°C (ambient) — (byte<<8)/256 formula
- T3-T6: 37-38°C (formula: byte-40) — motor/inverter temps, NOT coolant

**CAN 0x0284 (current):**
- byte[1] = 222 (drifted from 249→222 as bike cooled)
- bytes[4:7] = 81, 88, 80 → 41°C, 48°C, 40°C (value-40 formula)
- byte[1] formula: 255-byte[1]=33°C (close to IAT 31°C but not exact)
- byte[1] could also be raw ADC with inverted relationship to temperature
- Decreasing byte[1] = cooling bike (249→222), so higher byte = cooler

**CAN 0x0285 (current):**
- byte[1] = 229 (0xE5), similar inverted drift pattern

**CAN 0x0282:**
- byte[1] = 99-100 → matches KWP PID 0x76 raw value (100/8=12.5V)

**Key insight:** 0x0720 T3-T6 are motor/inverter temperatures (37-38°C), not coolant (29°C). The 0x0284 bytes[4:7] are additional motor temps (40-48°C). byte[1] of 0x0284/0x0285 is still unclear — possibly inverted temperature or raw ADC.
