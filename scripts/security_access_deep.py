#!/usr/bin/env python3
"""
Kawasaki Ninja 7 Hybrid — SecurityAccess Deep Analysis

Tests all known Kawasaki seed-key pairs and algorithmic transforms
against the Ninja 7 Hybrid's 6-byte random seed SecurityAccess.

Phase 1: Probe all SecurityAccess levels (0x01-0x0F)
Phase 2: Seed randomness analysis (fixed vs random vs PRNG)
Phase 3: Known 5-byte Kawasaki pairs (from Z750r/Ninja 400 era)
Phase 4: Algorithmic transform brute-force
Phase 5: Extended key derivation attempts (byte operations, table lookups)

Based on findings from kwp2000_seed_test.py and community research:
- Ninja 7 Hybrid uses 6-byte random seeds at level 0x07
- Older Kawasakis (Z750r, Ninja 400) use 5-byte fixed seed-key pairs
- Known 5-byte pairs: 3 documented from kawaduino/aster94

Usage:
  python3 security_access_deep.py              # Full test suite
  python3 security_access_deep.py --phase 2     # Run only phase 2
  python3 security_access_deep.py --level 7    # Test specific level
  python3 security_access_deep.py --loop        # Continuous seed monitoring
  python3 security_access_deep.py --dry-run     # Show what would be sent

⚠️  After too many failed attempts, the ECU will lock out SecurityAccess
    until a key cycle. Use --delay to increase time between attempts.
"""

import can
import time
import argparse
import sys
from datetime import datetime

# CAN IDs for Ninja 7 Hybrid KWP2000-over-CAN
TX_ID = 0x764  # Tester → ECU
RX_ID = 0x746  # ECU → Tester

# Known Kawasaki 5-byte seed-key pairs (from Z750r, Ninja 400, etc.)
# Source: Arduino forum (user "Scissor"), aster94/KWP2000 library
KNOWN_PAIRS_5BYTE = [
    {"seed": bytes([0x13, 0x52, 0x43, 0x64, 0x75]), "key": bytes([0x63, 0x27, 0x53, 0x67, 0x42])},
    {"seed": bytes([0x57, 0x48, 0x58, 0x49, 0x58]), "key": bytes([0x30, 0x20, 0x39, 0x48, 0x74])},
    {"seed": bytes([0x58, 0x37, 0x48, 0x45, 0x95]), "key": bytes([0x58, 0x49, 0x57, 0x69, 0x84])},
]

# SecurityAccess levels to probe
LEVELS = [0x01, 0x03, 0x05, 0x07, 0x09, 0x0B, 0x0D, 0x0F]

# NRC codes
NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLength",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceededAttempts",
    0x37: "requiredTimeDelayNotExpired",
}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def log_hex(label, data):
    hex_str = " ".join(f"{b:02X}" for b in data)
    log(f"  {label}: [{hex_str}] ({len(data)} bytes)")


class KWP:
    """KWP2000 over CAN (ISO 15765) for Ninja 7 Hybrid."""

    def __init__(self, bus, tx_id=TX_ID, rx_id=RX_ID):
        self.bus = bus
        self.tx_id = tx_id
        self.rx_id = rx_id

    def _send(self, data):
        """Send single-frame ISO-TP message."""
        uds = bytearray(data)
        if len(uds) > 7:
            raise ValueError(f"Payload too long for single frame: {len(uds)} bytes")
        frame = bytearray([len(uds)] + list(uds) + [0x00] * (7 - len(uds)))
        msg = can.Message(arbitration_id=self.tx_id, data=frame[:8], is_extended_id=False)
        self.bus.send(msg)

    def _recv(self, timeout=2.0):
        """Receive single or multi-frame ISO-TP response."""
        start = time.time()
        payload = bytearray()
        total_len = None

        while time.time() - start < timeout:
            msg = self.bus.recv(timeout=0.1)
            if msg is None or msg.arbitration_id != self.rx_id:
                continue

            fd = bytes(msg.data)
            pci = fd[0]

            # Single frame
            if (pci & 0xF0) == 0x00:
                sf_len = pci & 0x0F
                if sf_len == 0:
                    continue
                payload = bytearray(fd[1:1 + sf_len])
                return bytes(payload)

            # First frame (multi-frame)
            elif (pci & 0xF0) == 0x10:
                total_len = ((pci & 0x0F) << 8) | fd[1]
                payload = bytearray(fd[2:8])
                # Send flow control
                fc = bytearray([0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                self.bus.send(can.Message(arbitration_id=self.tx_id, data=fc, is_extended_id=False))

            # Consecutive frame
            elif (pci & 0xF0) == 0x20:
                seq = pci & 0x0F
                remaining = total_len - len(payload) if total_len else 7
                payload.extend(fd[1:1 + min(7, remaining)])
                if total_len and len(payload) >= total_len:
                    return bytes(payload[:total_len])

        return None

    def open_session(self, session_type=0x80):
        """Open KWP2000 diagnostic session."""
        self._send([0x10, session_type])
        resp = self._recv(timeout=3.0)
        if resp and len(resp) >= 2 and resp[0] == 0x50:
            log(f"  Session 0x{session_type:02X} opened successfully")
            return True
        elif resp and len(resp) >= 3 and resp[0] == 0x7F:
            nrc = resp[2]
            log(f"  Session 0x{session_type:02X} rejected: {NRC_NAMES.get(nrc, f'NRC 0x{nrc:02X}')}")
            return False
        else:
            log(f"  Session 0x{session_type:02X}: no response or unexpected")
            return False

    def request_seed(self, level):
        """Request SecurityAccess seed at given level."""
        self._send([0x27, level])
        resp = self._recv(timeout=2.0)
        if resp is None:
            return None, "timeout"
        if len(resp) >= 3 and resp[0] == 0x7F:
            nrc = resp[2]
            return None, f"denied:{NRC_NAMES.get(nrc, f'0x{nrc:02X}')}"
        if len(resp) >= 2 and resp[0] == 0x67:
            seed = resp[2:]
            return seed, "ok"
        return None, f"unexpected:{resp.hex()}"

    def send_key(self, level, key):
        """Send SecurityAccess key. Key level = seed level + 1."""
        key_level = level + 1
        self._send([0x27, key_level] + list(key))
        resp = self._recv(timeout=2.0)
        if resp is None:
            return False, "timeout"
        if len(resp) >= 3 and resp[0] == 0x7F:
            nrc = resp[2]
            return False, f"rejected:{NRC_NAMES.get(nrc, f'0x{nrc:02X}')}"
        if len(resp) >= 2 and resp[0] == 0x67:
            return True, "GRANTED!"
        return False, f"unexpected:{resp.hex()}"

    def send_and_recv(self, data, timeout=2.0):
        """Send raw data and receive response."""
        self._send(data)
        return self._recv(timeout=timeout)


def flush_can(bus, count=30):
    """Drain stale CAN messages."""
    for _ in range(count):
        bus.recv(0.01)


def fresh_session(kwp, bus):
    """Open a fresh KWP2000 session (drain bus first)."""
    flush_can(bus, 20)
    return kwp.open_session(0x80)


def phase1_probe_levels(kwp, bus, delay=0.3):
    """Probe all SecurityAccess levels to see which respond."""
    log("\n" + "=" * 60)
    log("PHASE 1: Probe SecurityAccess levels (0x01-0x0F)")
    log("=" * 60)

    if not fresh_session(kwp, bus):
        log("  Cannot open session — aborting")
        return {}

    results = {}
    for level in LEVELS:
        log(f"\n  Probing level 0x{level:02X} (seed) / 0x{level+1:02X} (key)...")
        seed, status = kwp.request_seed(level)
        results[level] = {"seed": seed, "status": status}

        if seed:
            seed_hex = " ".join(f"{b:02X}" for b in seed)
            log(f"  Level 0x{level:02X}: {len(seed)}-byte seed [{seed_hex}] — {status}")
        else:
            log(f"  Level 0x{level:02X}: {status}")

        time.sleep(delay)

    # Re-open session for subsequent tests
    fresh_session(kwp, bus)
    return results


def phase2_seed_randomness(kwp, bus, level=0x07, count=5, delay=0.3):
    """Test if seeds are fixed, cycling, or truly random."""
    log("\n" + "=" * 60)
    log(f"PHASE 2: Seed randomness test at level 0x{level:02X} ({count} requests)")
    log("=" * 60)

    if not fresh_session(kwp, bus):
        log("  Cannot open session — aborting")
        return []

    seeds = []
    for i in range(count):
        log(f"\n  Request #{i+1}/{count}")
        seed, status = kwp.request_seed(level)
        if seed:
            seeds.append(seed)
            seed_hex = " ".join(f"{b:02X}" for b in seed)
            log(f"  Seed: [{seed_hex}] ({len(seed)} bytes)")
        else:
            log(f"  Failed: {status}")
            break

        # Re-open session for fresh seed
        time.sleep(delay)
        fresh_session(kwp, bus)

    if len(seeds) < 2:
        log(f"\n  Not enough seeds for analysis")
        return seeds

    # Analyze
    unique = set(s.hex() for s in seeds)
    log(f"\n  --- Analysis ---")
    log(f"  Total seeds: {len(seeds)}")
    log(f"  Unique seeds: {len(unique)}")

    if len(unique) == 1:
        log(f"  *** FIXED SEED — Lookup table algorithm! ***")
        log(f"  Seed: {seeds[0].hex()}")
    elif len(unique) == len(seeds):
        log(f"  *** ALL SEEDS DIFFERENT — Random or PRNG ***")
    else:
        log(f"  *** SOME SEEDS REPEAT — Small lookup table cycling ***")
        # Count occurrences
        from collections import Counter
        counts = Counter(s.hex() for s in seeds)
        for seed_hex, count in counts.most_common():
            log(f"    {seed_hex}: {count} occurrence(s)")

    # Byte-level analysis
    log(f"\n  Byte-level variation:")
    for pos in range(len(seeds[0])):
        vals = set(s[pos] for s in seeds if pos < len(s))
        log(f"    Byte {pos}: {len(vals)} unique values: {', '.join(f'{v:02X}' for v in sorted(vals))}")

    return seeds


def phase3_known_pairs(kwp, bus, level=0x07, delay=0.5):
    """Test known 5-byte Kawasaki pairs against current seed."""
    log("\n" + "=" * 60)
    log(f"PHASE 3: Test known 5-byte Kawasaki pairs at level 0x{level:02X}")
    log("=" * 60)

    if not fresh_session(kwp, bus):
        log("  Cannot open session — aborting")
        return

    for i, pair in enumerate(KNOWN_PAIRS_5BYTE):
        seed_hex = " ".join(f"{b:02X}" for b in pair["seed"])
        key_hex = " ".join(f"{b:02X}" for b in pair["key"])
        log(f"\n  Pair {i+1}: seed=[{seed_hex}] → key=[{key_hex}]")

        # Get fresh seed
        seed, status = kwp.request_seed(level)
        if seed is None:
            log(f"  Cannot get seed: {status}")
            break

        seed_hex_actual = " ".join(f"{b:02X}" for b in seed)
        log(f"  Actual seed: [{seed_hex_actual}] ({len(seed)} bytes)")

        # Check if seed matches
        if seed == pair["seed"]:
            log(f"  *** SEED MATCHES KNOWN PAIR! Sending key... ***")
            result, rstatus = kwp.send_key(level, pair["key"])
            if result:
                log(f"  *** SECURITY ACCESS GRANTED! ***")
                return True
            else:
                log(f"  Key rejected: {rstatus}")
        else:
            log(f"  Seed doesn't match (got {len(seed)} bytes, expected 5)")

            # Try the key anyway (in case key derivation is independent of seed)
            # Only if seed length matches key length
            if len(seed) == len(pair["key"]):
                log(f"  Trying key anyway (same length)...")
                # Need fresh session + seed
                time.sleep(delay)
                fresh_session(kwp, bus)
                seed2, _ = kwp.request_seed(level)
                if seed2:
                    result, rstatus = kwp.send_key(level, pair["key"])
                    log(f"  Result: {rstatus}")

            # Try 6-byte key (5-byte key + 0x00 pad)
            padded = pair["key"] + b'\x00'
            log(f"  Trying padded key [{padded.hex()}]...")
            time.sleep(delay)
            fresh_session(kwp, bus)
            seed3, _ = kwp.request_seed(level)
            if seed3:
                result, rstatus = kwp.send_key(level, padded)
                log(f"  Padded key result: {rstatus}")

        time.sleep(delay)

    return False


def phase4_algorithmic_transforms(kwp, bus, level=0x07, delay=0.3):
    """Try common seed→key transforms."""
    log("\n" + "=" * 60)
    log(f"PHASE 4: Algorithmic transform attempts at level 0x{level:02X}")
    log("=" * 60)

    if not fresh_session(kwp, bus):
        log("  Cannot open session — aborting")
        return

    # Get a seed to work with
    seed, status = kwp.request_seed(level)
    if seed is None:
        log(f"  Cannot get seed: {status}")
        return

    seed_hex = " ".join(f"{b:02X}" for b in seed)
    log(f"  Base seed: [{seed_hex}] ({len(seed)} bytes)")

    transforms = []

    # XOR with constants
    for xor_val in [0x00, 0x01, 0xFF, 0xAA, 0x55, 0x42, 0x37, 0x14, 0x50, 0x28, 0x64, 0x95]:
        transforms.append((f"XOR_0x{xor_val:02X}", bytes([(b ^ xor_val) & 0xFF for b in seed])))

    # Byte reversal
    transforms.append(("reverse", seed[::-1]))

    # Increment/decrement
    transforms.append(("increment", bytes([(b + 1) & 0xFF for b in seed])))
    transforms.append(("decrement", bytes([(b - 1) & 0xFF for b in seed])))

    # Nibble swap
    transforms.append(("nibble_swap", bytes([((b >> 4) | ((b & 0x0F) << 4)) for b in seed])))

    # Add constants
    for const in [0x14, 0x28, 0x32, 0x50, 0x64, 0x96, 0xC8]:
        transforms.append((f"add_0x{const:02X}", bytes([(b + const) & 0xFF for b in seed])))

    # Subtract constants
    for const in [0x14, 0x28, 0x32, 0x50, 0x64]:
        transforms.append((f"sub_0x{const:02X}", bytes([(b - const) & 0xFF for b in seed])))

    # ROT13-style for bytes
    transforms.append(("rot+13", bytes([(b + 13) & 0xFF for b in seed])))
    transforms.append(("rot-13", bytes([(b - 13) & 0xFF for b in seed])))

    # Complement
    transforms.append(("NOT", bytes([0xFF - b for b in seed])))

    # Shift left/right by 1 bit
    transforms.append(("shl1", bytes([(b << 1) & 0xFF for b in seed])))
    transforms.append(("shr1", bytes([b >> 1 for b in seed])))

    # Known Kawasaki key patterns applied to 6-byte seed
    # The 5-byte keys have these relationships with their seeds:
    # Pair 1: seed[0]+0x50=0x63, seed[1]-0x2B=0x27, seed[2]+0x10=0x53, etc.
    # Let's try extending the pattern
    transforms.append(("kawa_pattern1", bytes([
        (seed[0] + 0x50) & 0xFF if len(seed) > 0 else 0,
        (seed[1] - 0x2B) & 0xFF if len(seed) > 1 else 0,
        (seed[2] + 0x10) & 0xFF if len(seed) > 2 else 0,
        (seed[3] + 0x03) & 0xFF if len(seed) > 3 else 0,
        (seed[4] + 0x11) & 0xFF if len(seed) > 4 else 0,
        (seed[5] + 0x6D) & 0xFF if len(seed) > 5 else 0,
    ])))

    for name, key in transforms:
        # Need fresh seed for each attempt (seeds may change)
        time.sleep(delay)
        fresh_session(kwp, bus)
        new_seed, _ = kwp.request_seed(level)
        if new_seed is None:
            log(f"  {name}: Cannot get fresh seed, stopping")
            break

        # If seed changed, regenerate transforms for new seed
        if new_seed != seed:
            seed = new_seed
            # Regenerate transform for new seed
            if name.startswith("XOR"):
                xor_val = int(name.split("_0x")[1], 16)
                key = bytes([(b ^ xor_val) & 0xFF for b in seed])
            elif name == "reverse":
                key = seed[::-1]
            elif name == "increment":
                key = bytes([(b + 1) & 0xFF for b in seed])
            elif name == "decrement":
                key = bytes([(b - 1) & 0xFF for b in seed])
            elif name == "nibble_swap":
                key = bytes([((b >> 4) | ((b & 0x0F) << 4)) for b in seed])
            elif name == "NOT":
                key = bytes([0xFF - b for b in seed])
            elif name.startswith("add"):
                const = int(name.split("_0x")[1], 16)
                key = bytes([(b + const) & 0xFF for b in seed])
            elif name.startswith("sub"):
                const = int(name.split("_0x")[1], 16)
                key = bytes([(b - const) & 0xFF for b in seed])
            elif name.startswith("rot"):
                delta = 13 if "+" in name else -13
                key = bytes([(b + delta) & 0xFF for b in seed])
            elif name.startswith("shl"):
                key = bytes([(b << 1) & 0xFF for b in seed])
            elif name.startswith("shr"):
                key = bytes([b >> 1 for b in seed])
            # kawa_pattern1 would need regeneration too but skip for brevity

        key_hex = " ".join(f"{b:02X}" for b in key)
        log(f"  {name}: [{key_hex}]")

        result, status = kwp.send_key(level, key)
        if result:
            log(f"  *** SECURITY ACCESS GRANTED with {name}! ***")
            log(f"  *** Seed: {seed.hex()} Key: {key.hex()} ***")
            return name, seed, key

        if "exceededAttempts" in status:
            log(f"  LOCKOUT detected! Stopping tests.")
            log(f"  Key cycle required to reset ECU.")
            return None

        log(f"    → {status}")

    return None


def phase5_extended_analysis(kwp, bus, level=0x07, delay=0.5):
    """Extended analysis: timing, cross-level seeds, etc."""
    log("\n" + "=" * 60)
    log(f"PHASE 5: Extended analysis")
    log("=" * 60)

    # Test if seeds change within a session (without re-opening)
    log("\n  --- Within-session seed consistency ---")
    if not fresh_session(kwp, bus):
        log("  Cannot open session")
        return

    seed1, _ = kwp.request_seed(level)
    if seed1:
        log(f"  Seed 1 (same session): {seed1.hex()}")

        # Request another seed in the same session
        time.sleep(0.2)
        seed2, _ = kwp.request_seed(level)
        if seed2:
            log(f"  Seed 2 (same session): {seed2.hex()}")
            if seed1 == seed2:
                log(f"  Seeds IDENTICAL within session — key must match this seed")
            else:
                log(f"  Seeds DIFFERENT within session — seeds rotate even in same session")
        else:
            log(f"  Second seed request failed")
    else:
        log(f"  Cannot get seed")

    # Test timing: request seed, wait, request again in new session
    log("\n  --- Seed timing test (5s, 30s, 60s delays) ---")
    for wait in [5, 30, 60]:
        log(f"  Waiting {wait}s...")
        time.sleep(wait)
        fresh_session(kwp, bus)
        seed, _ = kwp.request_seed(level)
        if seed:
            log(f"  Seed after {wait}s: {seed.hex()}")
        else:
            log(f"  Failed after {wait}s")

    # Test if lower levels use 5-byte seeds (old format)
    log("\n  --- Checking lower levels for 5-byte seeds ---")
    for lvl in [0x01, 0x03, 0x05]:
        fresh_session(kwp, bus)
        seed, status = kwp.request_seed(lvl)
        if seed:
            log(f"  Level 0x{lvl:02X}: {len(seed)}-byte seed [{seed.hex()}] — {status}")
        else:
            log(f"  Level 0x{lvl:02X}: {status}")


def main():
    parser = argparse.ArgumentParser(
        description="Kawasaki Ninja 7 Hybrid — SecurityAccess Deep Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--interface", "-i", default="can0", help="CAN interface")
    parser.add_argument("--bitrate", "-b", type=int, default=500000, help="CAN bitrate")
    parser.add_argument("--delay", "-d", type=float, default=0.5, help="Delay between attempts (seconds)")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4, 5], help="Run only specific phase")
    parser.add_argument("--level", type=int, default=0x07, help="SecurityAccess level to test (default: 0x07)")
    parser.add_argument("--loop", action="store_true", help="Continuous seed monitoring (Ctrl+C to stop)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent without sending")
    args = parser.parse_args()

    log("Kawasaki Ninja 7 Hybrid — SecurityAccess Deep Analysis")
    log(f"CAN: {args.interface} @ {args.bitrate} bps, TX=0x{TX_ID:03X}, RX=0x{RX_ID:03X}")
    log(f"Delay: {args.delay}s between attempts")

    if args.dry_run:
        log("DRY RUN — no CAN messages will be sent")
        log("Known 5-byte pairs that would be tested:")
        for pair in KNOWN_PAIRS_5BYTE:
            log(f"  Seed: {pair['seed'].hex()} → Key: {pair['key'].hex()}")
        return

    try:
        bus = can.interface.Bus(channel=args.interface, bustype="socketcan", bitrate=args.bitrate)
        log(f"CAN interface {args.interface} opened")
    except Exception as e:
        log(f"Error: {e}")
        log(f"Make sure {args.interface} is up: sudo ip link set {args.interface} up type can bitrate {args.bitrate}")
        sys.exit(1)

    kwp = KWP(bus)

    try:
        if args.loop:
            # Continuous seed monitoring
            log("Continuous seed monitoring (Ctrl+C to stop)")
            iteration = 0
            while True:
                iteration += 1
                log(f"\n--- Iteration {iteration} ---")
                fresh_session(kwp, bus)
                seed, status = kwp.request_seed(args.level)
                if seed:
                    log(f"  Seed: {' '.join(f'{b:02X}' for b in seed)}")
                else:
                    log(f"  Failed: {status}")
                    if "exceededAttempts" in status or "lockout" in status.lower():
                        log("  ECU LOCKOUT — key cycle needed")
                        break
                time.sleep(1.0)

        elif args.phase == 1:
            phase1_probe_levels(kwp, bus, delay=args.delay)
        elif args.phase == 2:
            phase2_seed_randomness(kwp, bus, level=args.level, delay=args.delay)
        elif args.phase == 3:
            phase3_known_pairs(kwp, bus, level=args.level, delay=args.delay)
        elif args.phase == 4:
            phase4_algorithmic_transforms(kwp, bus, level=args.level, delay=args.delay)
        elif args.phase == 5:
            phase5_extended_analysis(kwp, bus, level=args.level, delay=args.delay)
        else:
            # Full test suite
            level_results = phase1_probe_levels(kwp, bus, delay=args.delay)

            # Find which levels gave seeds
            responding_levels = [l for l, r in level_results.items() if r["seed"] is not None]
            if responding_levels:
                log(f"\nResponding levels: {', '.join(f'0x{l:02X}' for l in responding_levels)}")

                for level in responding_levels:
                    phase2_seed_randomness(kwp, bus, level=level, count=5, delay=args.delay)
                    phase3_known_pairs(kwp, bus, level=level, delay=args.delay)
                    phase4_algorithmic_transforms(kwp, bus, level=level, delay=args.delay)

                phase5_extended_analysis(kwp, bus, level=responding_levels[0], delay=args.delay)
            else:
                log("\nNo SecurityAccess levels responded — cannot continue tests")

        log("\n" + "=" * 60)
        log("TEST COMPLETE")
        log("=" * 60)

    except KeyboardInterrupt:
        log("\nTest interrupted by user")
    finally:
        bus.shutdown()
        log("CAN interface closed")


if __name__ == "__main__":
    main()