#!/usr/bin/env python3
"""
Mock Arduino simulator for testing GUI_Clean.py without hardware.

Creates a virtual serial port using Python's pty module (no extra dependencies).
The GUI connects to the slave path printed on startup, exactly like a real COM port.

Usage:
    python tests/mock_arduino.py          # run in one terminal
    python src/gui/GUI_Clean.py           # run in another terminal
    → paste the printed port path into the Hardware tab dropdown → Connect
"""

import os
import pty
import threading
import time
import random

# ── Create virtual serial port pair ──────────────────────────────────────────
master_fd, slave_fd = pty.openpty()
slave_path = os.ttyname(slave_fd)

print()
print("=" * 60)
print("  MOCK ARDUINO SIMULATOR")
print("=" * 60)
print(f"  Virtual port: {slave_path}")
print()
print("  Steps:")
print("    1. Open GUI_Clean.py in another terminal")
print("    2. Hardware tab → type/paste this path into the port field")
print("    3. Click Connect")
print()
print("  Behaviour:")
print("    • Sends ARDUINO_READY every 0.5 s for the first 30 s")
print("    • After connection, streams PRESSURE_READING:<float> every 500 ms")
print("    • Set Pressure  → graph rises toward target (with ±0.05 BAR noise)")
print("    • Pressure Off  → reading drops to 0")
print("    • Motor Move    → HOMED sent after 2 s delay")
print("    • Ctrl-C to stop")
print("=" * 60)
print()

# ── Shared state ─────────────────────────────────────────────────────────────
target_pressure = [0.0]   # list so threads can mutate it
running         = [True]
connected       = [False]  # flipped when we see the first command from GUI


# ── Command handler ───────────────────────────────────────────────────────────
def handle(cmd: str):
    """Parse one line received from the GUI and react accordingly."""
    print(f"[MOCK ←] {cmd}")

    if cmd.startswith("PRESSURE:"):
        try:
            val = float(cmd.split(":")[1])
            target_pressure[0] = val
            connected[0] = True
            print(f"[MOCK]   Target pressure → {val:.2f} BAR")
        except ValueError:
            pass

    elif cmd == "PRESSURE_OFF":
        target_pressure[0] = 0.0
        connected[0] = True
        print("[MOCK]   Pressure off")

    elif "DIST:" in cmd:
        # SPEED:<int>;DIST:<float>  — simulate motor run with progress + MOVEMENT_COMPLETE
        connected[0] = True
        duration = random.uniform(5.0, 15.0)
        print(f"[MOCK]   Motor move command, running for {duration:.1f} s…")
        def _run_motor():
            steps = 10
            for i in range(1, steps + 1):
                time.sleep(duration / steps)
                pct = i * 10
                try:
                    msg = f"DEBUG: Movement progress: {pct}%\n".encode()
                    os.write(master_fd, msg)
                    print(f"[MOCK →] Movement progress: {pct}%")
                except OSError:
                    return
            try:
                os.write(master_fd, b"MOVEMENT_COMPLETE\n")
                print("[MOCK →] MOVEMENT_COMPLETE")
                os.write(master_fd, b"ARDUINO_READY\n")
            except OSError:
                pass
        threading.Thread(target=_run_motor, daemon=True).start()

    elif cmd.startswith("HOME:"):
        connected[0] = True
        print("[MOCK]   Homing sequence started, sending Homing Complete! in 2 s…")
        def _send_homing_complete():
            time.sleep(2.0)
            try:
                os.write(master_fd, b"Homing Complete!\n")
                print("[MOCK →] Homing Complete!")
                os.write(master_fd, b"ARDUINO_READY\n")
            except OSError:
                pass
        threading.Thread(target=_send_homing_complete, daemon=True).start()

    elif cmd.startswith("RESET:"):
        connected[0] = True
        def _send_ready():
            time.sleep(0.5)
            try:
                os.write(master_fd, b"ARDUINO_READY\n")
                print("[MOCK →] ARDUINO_READY  (reset)")
            except OSError:
                pass
        threading.Thread(target=_send_ready, daemon=True).start()


# ── Reader thread: commands from GUI → master_fd ──────────────────────────────
def reader_thread():
    buf = b""
    while running[0]:
        try:
            chunk = os.read(master_fd, 256)
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode("utf-8", errors="replace").strip()
                if cmd:
                    handle(cmd)
        except OSError:
            break


# ── Sender thread: ARDUINO_READY then PRESSURE_READING ───────────────────────
def sender_thread():
    t0 = time.time()
    while running[0]:
        time.sleep(0.5)
        try:
            if not connected[0] and time.time() - t0 < 30:
                # Keep sending ARDUINO_READY until the GUI connects
                os.write(master_fd, b"ARDUINO_READY\n")
                print("[MOCK →] ARDUINO_READY")
            elif connected[0]:
                # Stream noisy pressure readings
                noise = random.gauss(0.0, 0.05)
                val   = max(0.0, target_pressure[0] + noise)
                msg   = f"PRESSURE_READING:{val:.3f}\n".encode()
                os.write(master_fd, msg)
                # (intentionally quiet — would spam the console)
        except OSError:
            break


# ── Start threads and block ───────────────────────────────────────────────────
threading.Thread(target=reader_thread, daemon=True).start()
threading.Thread(target=sender_thread, daemon=True).start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    running[0] = False
    print("\n[MOCK] Shutting down. Goodbye.")
