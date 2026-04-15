#!/usr/bin/env python3
"""
rpi_demo.py  —  Adaptive Traffic Signal Demo on Raspberry Pi 2
===============================================================
Reads vehicle demand derived from 31 AVID Oct-2025 route files,
simulates queue build-up per arm, runs Max-Pressure + DQN
inference (no training), and drives 4 signal-head LED sets
via GPIO.

Hardware (all LEDs common-cathode, HIGH = ON):
  Phase 0  Arm D→out2  (links 3,4)   R=GPIO19  G=GPIO26  Y=GPIO21
  Phase 2  Arm B→out1  (links 1,2)   R=GPIO20  G=GPIO16  Y=GPIO12
  Phase 4  Arm B→out4  (link 0)      R=GPIO8   G=GPIO25  Y=GPIO24
  Phase 6  Arm C→out3  (links 9,10)  R=GPIO7   G=GPIO9   Y=GPIO11
  LCD 16×2 I²C at 0x27

Modes:
  fixed       — 30 s green each phase, round-robin
  mp          — Max Pressure, picks highest-pressure phase
  hybrid_drl  — DQN selects phase from queue state (inference only)

Usage:
  python3 rpi_demo.py                        # hybrid_drl, 10× speed
  python3 rpi_demo.py --mode fixed           # fixed baseline
  python3 rpi_demo.py --mode mp              # max pressure only
  python3 rpi_demo.py --speed 1              # real-time (slow)
  python3 rpi_demo.py --no-hardware          # laptop/console test
"""

import time, argparse, math, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent

# ═══════════════════════════════════════════════════════════════════════════════
# DEMAND PROFILE — averaged from 31 SUMO route files (Oct 1–31, 2025)
# Averaged from all 31 SUMO route files (Oct 1–31, 2025)
# Each tuple: (seconds_into_day, A_vph, B_vph, C_vph, D_vph)
# ═══════════════════════════════════════════════════════════════════════════════
DEMAND = [
    (    0, 120.6, 118.6, 118.6, 119.5),  # 00:00
    (  900, 119.9, 118.1, 118.1, 118.2),  # 00:15
    ( 1800, 111.5, 110.1, 110.1, 110.1),  # 00:30
    ( 2700,  99.9,  98.0,  98.0,  97.9),  # 00:45
    ( 3600,  91.8,  90.5,  90.5,  90.6),  # 01:00
    ( 4500,  80.9,  79.1,  79.1,  79.6),  # 01:15
    ( 5400,  71.1,  71.3,  71.3,  72.3),  # 01:30
    ( 6300,  61.0,  58.9,  58.9,  59.5),  # 01:45
    ( 7200,  59.4,  57.1,  57.1,  59.4),  # 02:00
    ( 8100,  54.9,  52.3,  52.3,  54.4),  # 02:15
    ( 9000,  48.0,  45.5,  45.5,  47.3),  # 02:30
    ( 9900,  50.4,  47.8,  47.8,  49.8),  # 02:45
    (10800,  48.5,  45.6,  45.6,  49.3),  # 03:00
    (11700,  52.7,  50.6,  50.6,  51.5),  # 03:15
    (12600,  53.3,  51.1,  51.1,  51.9),  # 03:30
    (13500,  53.0,  50.2,  50.2,  52.9),  # 03:45
    (14400,  59.9,  57.9,  57.9,  58.4),  # 04:00
    (15300,  68.3,  66.4,  66.4,  66.5),  # 04:15
    (16200,  82.9,  81.0,  81.0,  81.4),  # 04:30
    (17100, 109.0, 106.8, 106.8, 107.1),  # 04:45
    (18000, 128.0, 126.2, 126.2, 126.7),  # 05:00
    (18900, 172.9, 170.9, 170.9, 171.8),  # 05:15
    (19800, 253.2, 251.7, 251.7, 252.3),  # 05:30
    (20700, 360.4, 359.2, 359.2, 359.9),  # 05:45
    (21600, 547.3, 545.9, 545.9, 546.4),  # 06:00
    (22500, 727.8, 726.8, 726.8, 727.2),  # 06:15
    (23400, 869.8, 868.6, 868.6, 869.1),  # 06:30
    (24300, 958.5, 957.4, 957.4, 958.0),  # 06:45
    (25200, 984.1, 983.2, 983.2, 983.5),  # 07:00  ← AM peak
    (26100, 974.1, 973.4, 973.4, 973.9),  # 07:15
    (27000, 953.5, 953.0, 953.0, 953.4),  # 07:30
    (27900, 915.9, 915.5, 915.5, 915.7),  # 07:45
    (28800, 865.6, 865.2, 865.2, 865.6),  # 08:00
    (29700, 828.3, 828.0, 828.0, 828.2),  # 08:15
    (30600, 786.5, 786.1, 786.1, 786.3),  # 08:30
    (31500, 780.4, 780.1, 780.1, 780.4),  # 08:45
    (32400, 780.0, 779.9, 779.9, 780.0),  # 09:00
    (33300, 778.2, 778.1, 778.1, 778.2),  # 09:15
    (34200, 775.0, 775.0, 775.0, 775.0),  # 09:30
    (35100, 802.7, 802.5, 802.5, 802.6),  # 09:45
    (36000, 812.8, 812.7, 812.7, 812.7),  # 10:00
    (36900, 803.5, 803.3, 803.3, 803.5),  # 10:15
    (37800, 801.4, 801.1, 801.1, 801.4),  # 10:30
    (38700, 840.9, 840.8, 840.8, 840.9),  # 10:45
    (39600, 816.8, 816.7, 816.7, 816.8),  # 11:00
    (40500, 832.2, 832.0, 832.0, 832.2),  # 11:15
    (41400, 847.9, 847.7, 847.7, 847.9),  # 11:30
    (42300, 845.2, 845.0, 845.0, 845.1),  # 11:45
    (43200, 853.5, 853.2, 853.2, 853.4),  # 12:00
    (44100, 870.2, 870.0, 870.0, 870.1),  # 12:15
    (45000, 889.1, 889.0, 889.0, 889.1),  # 12:30
    (45900, 885.6, 885.6, 885.6, 885.6),  # 12:45
    (46800, 867.8, 867.6, 867.6, 867.6),  # 13:00
    (47700, 888.7, 888.5, 888.5, 888.5),  # 13:15
    (48600, 907.2, 906.9, 906.9, 907.2),  # 13:30
    (49500, 904.6, 904.5, 904.5, 904.5),  # 13:45
    (50400, 899.6, 899.4, 899.4, 899.3),  # 14:00
    (51300, 894.7, 894.4, 894.4, 894.6),  # 14:15
    (52200, 894.9, 894.7, 894.7, 894.9),  # 14:30
    (53100, 889.2, 889.0, 889.0, 889.2),  # 14:45
    (54000, 874.8, 874.6, 874.6, 874.8),  # 15:00
    (54900, 885.9, 885.7, 885.7, 885.9),  # 15:15
    (55800, 874.7, 874.6, 874.6, 874.5),  # 15:30
    (56700, 882.6, 882.3, 882.3, 882.4),  # 15:45
    (57600, 872.8, 872.7, 872.7, 872.8),  # 16:00
    (58500, 859.8, 859.7, 859.7, 859.8),  # 16:15
    (59400, 883.3, 883.2, 883.2, 883.1),  # 16:30
    (60300, 893.6, 893.3, 893.3, 893.3),  # 16:45
    (61200, 897.9, 897.8, 897.8, 897.8),  # 17:00
    (62100, 908.0, 907.9, 907.9, 907.9),  # 17:15  ← PM peak
    (63000, 906.8, 906.7, 906.7, 906.7),  # 17:30
    (63900, 876.3, 876.0, 876.0, 876.2),  # 17:45
    (64800, 814.3, 813.8, 813.8, 814.0),  # 18:00
    (65700, 776.0, 775.2, 775.2, 775.7),  # 18:15
    (66600, 713.6, 712.9, 712.9, 713.4),  # 18:30
    (67500, 664.6, 664.0, 664.0, 664.5),  # 18:45
    (68400, 630.4, 629.9, 629.9, 630.1),  # 19:00
    (69300, 613.2, 612.8, 612.8, 613.1),  # 19:15
    (70200, 567.3, 566.6, 566.6, 566.9),  # 19:30
    (71100, 528.7, 528.2, 528.2, 528.5),  # 19:45
    (72000, 476.3, 475.9, 475.9, 476.1),  # 20:00
    (72900, 435.4, 434.6, 434.6, 435.2),  # 20:15
    (73800, 404.0, 403.3, 403.3, 403.7),  # 20:30
    (74700, 364.4, 363.7, 363.7, 363.8),  # 20:45
    (75600, 337.0, 336.5, 336.5, 336.6),  # 21:00
    (76500, 303.5, 302.7, 302.7, 303.3),  # 21:15
    (77400, 288.3, 287.7, 287.7, 287.7),  # 21:30
    (78300, 257.4, 256.3, 256.3, 256.7),  # 21:45
    (79200, 239.6, 238.4, 238.4, 238.3),  # 22:00
    (80100, 216.4, 214.9, 214.9, 215.6),  # 22:15
    (81000, 183.9, 182.6, 182.6, 182.7),  # 22:30
    (81900, 164.3, 162.6, 162.6, 163.5),  # 22:45
    (82800, 148.5, 147.1, 147.1, 147.4),  # 23:00
    (83700, 136.5, 135.0, 135.0, 135.5),  # 23:15
    (84600, 111.3, 109.7, 109.7, 110.1),  # 23:30
    (85500,  97.8,  96.2,  96.2,  96.7),  # 23:45
]

# ═══════════════════════════════════════════════════════════════════════════════
# TLS PHASE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════
# Phase → which arms get green (fraction of their queue drained per step)
#   Phase 0: D straight           → drains D
#   Phase 2: A straight + B left  → drains A fully, B partially
#   Phase 4: B straight + C left  → drains B partially, C partially
#   Phase 6: C straight + D right → drains C fully, D partially
PHASE_GREEN = [0, 2, 4, 6]
PHASE_LABEL = {0: "Ph0 D ", 2: "Ph2 AB", 4: "Ph4 BC", 6: "Ph6 CD"}

# Drain coefficients: how much of each arm's queue is served per step
PHASE_DRAIN = {
    0: {"A": 0.0, "B": 0.0, "C": 0.0, "D": 1.0},
    2: {"A": 1.0, "B": 0.5, "C": 0.0, "D": 0.0},
    4: {"A": 0.0, "B": 0.5, "C": 0.5, "D": 0.0},
    6: {"A": 0.0, "B": 0.0, "C": 1.0, "D": 0.5},
}

# Max Pressure: pressure = sum of upstream queues served by this phase
PHASE_UPSTREAM = {
    0: ["D"],
    2: ["A", "B"],
    4: ["B", "C"],
    6: ["C", "D"],
}

FIXED_GREEN_S  = 30
YELLOW_S       = 4
MIN_GREEN_S    = 15
MAX_GREEN_S    = 90
SERVICE_RATE   = 1800  # veh/hr saturation flow per arm

# ═══════════════════════════════════════════════════════════════════════════════
# GPIO PIN MAP  (all common-cathode, HIGH = ON)
# ═══════════════════════════════════════════════════════════════════════════════
PIN_MAP = {
    # phase: (red_pin, green_pin, amber_pin)
    0: (19, 26, 21),   # Arm D→out2
    2: (20, 16, 12),   # Arm B→out1
    4: ( 8, 25, 24),   # Arm B→out4
    6: ( 7,  9, 11),   # Arm C→out3
}

# ═══════════════════════════════════════════════════════════════════════════════
# LIGHTWEIGHT DQN AGENT  (inference only, numpy)
# ═══════════════════════════════════════════════════════════════════════════════
class DQNInference:
    """Forward pass through trained 27→256→128→64→4 network."""

    def __init__(self, weights_path):
        data = np.load(weights_path)
        self.W1 = data["W1"]
        self.b1 = data["b1"]
        self.W2 = data["W2"]
        self.b2 = data["b2"]
        self.W3 = data["W3"]
        self.b3 = data["b3"]
        self.W4 = data["W4"]
        self.b4 = data["b4"]
        print(f"DQN weights loaded: {weights_path}")

    def predict(self, state):
        """Return Q-values for all 4 actions."""
        x = np.array(state, dtype=np.float32)
        x = np.maximum(0, self.W1 @ x + self.b1)   # ReLU
        x = np.maximum(0, self.W2 @ x + self.b2)
        x = np.maximum(0, self.W3 @ x + self.b3)
        q = self.W4 @ x + self.b4
        return q

    def act(self, state):
        """Greedy action selection."""
        q = self.predict(state)
        return int(np.argmax(q))


# ═══════════════════════════════════════════════════════════════════════════════
# QUEUE SIMULATOR
# ═══════════════════════════════════════════════════════════════════════════════
class QueueSim:
    """Simulates queue build-up and drain per arm using demand profile."""

    def __init__(self):
        self.queues = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
        self.wait   = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
        self.demand_idx = 0

    def get_demand(self, sim_time):
        """Look up vph per arm for current sim_time."""
        idx = min(int(sim_time // 900), len(DEMAND) - 1)
        _, a, b, c, d = DEMAND[idx]
        return {"A": a, "B": b, "C": c, "D": d}

    def step(self, phase, green_s, sim_time):
        """Advance one green interval: arrivals accumulate, active phase drains."""
        demand = self.get_demand(sim_time)
        drain  = PHASE_DRAIN[phase]

        for arm in ["A", "B", "C", "D"]:
            arrivals = demand[arm] * (green_s / 3600.0)
            served   = drain[arm] * SERVICE_RATE * (green_s / 3600.0)
            self.queues[arm] = max(0.0, self.queues[arm] + arrivals - served)
            if drain[arm] > 0:
                self.wait[arm] = max(0.0, self.wait[arm] - green_s)
            else:
                self.wait[arm] += green_s

    def total_queue(self):
        return sum(self.queues.values())

    def build_state(self, current_phase_idx, sim_time):
        """Build 27-dim state vector matching DQN training format."""
        demand = self.get_demand(sim_time)
        hour = (sim_time % 86400) / 86400.0

        state = []
        for arm in ["A", "B", "C", "D"]:
            state.append(self.queues[arm] / 50.0)       # normalised queue
            state.append(self.wait[arm] / 120.0)         # normalised wait
            state.append(demand[arm] / 1000.0)           # normalised demand
        # one-hot current phase
        for i in range(4):
            state.append(1.0 if i == current_phase_idx else 0.0)
        # pressure per phase
        for ph in PHASE_GREEN:
            p = sum(self.queues[a] for a in PHASE_UPSTREAM[ph])
            state.append(p / 100.0)
        # time features
        state.append(hour)
        state.append(math.sin(2 * math.pi * hour))
        state.append(math.cos(2 * math.pi * hour))
        # equity: max wait
        state.append(max(self.wait.values()) / 120.0)
        # total queue
        state.append(self.total_queue() / 200.0)
        # demand imbalance
        vals = list(demand.values())
        state.append((max(vals) - min(vals)) / 500.0)
        return state  # length 27


# ═══════════════════════════════════════════════════════════════════════════════
# HARDWARE INTERFACE
# ═══════════════════════════════════════════════════════════════════════════════
class HardwareIO:
    """Drives 4 signal-head LEDs + LCD.  Falls back to console."""

    def __init__(self, skip_hw=False):
        self.gpio = None
        self.lcd  = None

        if skip_hw:
            print("[HW] Console-only mode (--no-hardware)")
            return

        try:
            import RPi.GPIO as GPIO
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            for phase, (r, g, y) in PIN_MAP.items():
                for pin in (r, g, y):
                    GPIO.setup(pin, GPIO.OUT)
                    GPIO.output(pin, GPIO.LOW)
            self.gpio = GPIO
            print("[HW] GPIO initialised — 12 LED pins ready")
        except Exception as e:
            print(f"[HW] No GPIO ({e})")

        try:
            from RPLCD.i2c import CharLCD
            self.lcd = CharLCD("PCF8574", 0x27, port=1, cols=16, rows=2)
            self.lcd.clear()
            print("[HW] LCD connected at 0x27")
        except Exception as e:
            print(f"[HW] No LCD ({e})")

    def set_signal(self, active_phase, state="green"):
        """Set LEDs: active_phase gets green/amber, all others red."""
        if self.gpio is None:
            return
        for phase, (r, g, y) in PIN_MAP.items():
            if phase == active_phase:
                if state == "green":
                    self.gpio.output(r, self.gpio.LOW)
                    self.gpio.output(g, self.gpio.HIGH)
                    self.gpio.output(y, self.gpio.LOW)
                elif state == "amber":
                    self.gpio.output(r, self.gpio.LOW)
                    self.gpio.output(g, self.gpio.LOW)
                    self.gpio.output(y, self.gpio.HIGH)
                else:  # red
                    self.gpio.output(r, self.gpio.HIGH)
                    self.gpio.output(g, self.gpio.LOW)
                    self.gpio.output(y, self.gpio.LOW)
            else:
                # all non-active phases show red
                self.gpio.output(r, self.gpio.HIGH)
                self.gpio.output(g, self.gpio.LOW)
                self.gpio.output(y, self.gpio.LOW)

    def all_red(self):
        """All signals red (clearance)."""
        if self.gpio is None:
            return
        for phase, (r, g, y) in PIN_MAP.items():
            self.gpio.output(r, self.gpio.HIGH)
            self.gpio.output(g, self.gpio.LOW)
            self.gpio.output(y, self.gpio.LOW)

    def show_lcd(self, line1, line2=""):
        if self.lcd:
            try:
                self.lcd.clear()
                self.lcd.write_string(line1[:16])
                if line2:
                    self.lcd.crlf()
                    self.lcd.write_string(line2[:16])
            except:
                pass
        # always echo to console
        print(f"  LCD| {line1:<16s} | {line2:<16s}")

    def cleanup(self):
        if self.gpio:
            self.all_red()
            self.gpio.cleanup()
        if self.lcd:
            try:
                self.lcd.clear()
                self.lcd.write_string("Demo stopped")
            except:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# CONTROLLER LOGIC
# ═══════════════════════════════════════════════════════════════════════════════
def pick_phase_fixed(cycle_idx):
    return PHASE_GREEN[cycle_idx % 4]


def pick_phase_mp(sim, sim_time):
    """Max Pressure: pick phase with highest upstream queue pressure."""
    best_ph = 0
    best_p  = -1
    for ph in PHASE_GREEN:
        pressure = sum(sim.queues[a] for a in PHASE_UPSTREAM[ph])
        if pressure > best_p:
            best_p  = pressure
            best_ph = ph
    return best_ph


def pick_phase_drl(sim, dqn, current_phase_idx, sim_time):
    """Hybrid DQN: uses trained network to select best phase."""
    state  = sim.build_state(current_phase_idx, sim_time)
    action = dqn.act(state)
    return PHASE_GREEN[action]


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════
def run(mode, speed, no_hw):
    hw  = HardwareIO(skip_hw=no_hw)
    sim = QueueSim()

    dqn = None
    if mode == "hybrid_drl":
        wpath = HERE / "j1_dqn_weights.npz"
        if wpath.exists():
            dqn = DQNInference(str(wpath))
        else:
            print(f"[WARN] {wpath} not found — falling back to MP")
            mode = "mp"

    hw.show_lcd("J1 Gaborone", f"Mode: {mode[:10]}")
    time.sleep(2.0 / speed)

    sim_time    = 0         # seconds into day
    cycle_idx   = 0
    phase_idx   = 0         # index into PHASE_GREEN
    total_q_sum = 0.0
    n_steps     = 0
    switches    = 0

    print(f"\n{'='*60}")
    print(f"  J1 ADAPTIVE SIGNAL DEMO — {mode.upper()}")
    print(f"  Speed: {speed}×  |  96 intervals (24 h)")
    print(f"{'='*60}\n")

    try:
        while sim_time < 86400:
            # ── decide phase ──────────────────────────────────────────
            if mode == "fixed":
                phase = pick_phase_fixed(cycle_idx)
                green_s = FIXED_GREEN_S
            elif mode == "mp":
                phase = pick_phase_mp(sim, sim_time)
                green_s = FIXED_GREEN_S
            else:
                phase = pick_phase_drl(sim, dqn, phase_idx, sim_time)
                green_s = FIXED_GREEN_S

            new_idx = PHASE_GREEN.index(phase)
            if new_idx != phase_idx:
                switches += 1

                # ── yellow transition ─────────────────────────────────
                hw.set_signal(PHASE_GREEN[phase_idx], "amber")
                h = sim_time // 3600
                m = (sim_time % 3600) // 60
                hw.show_lcd(f"{h:02d}:{m:02d} YELLOW",
                            f"{PHASE_LABEL[PHASE_GREEN[phase_idx]]}")
                time.sleep(YELLOW_S / speed)

                # ── all-red clearance ─────────────────────────────────
                hw.all_red()
                time.sleep(1.0 / speed)

            phase_idx = new_idx

            # ── green phase ───────────────────────────────────────────
            hw.set_signal(phase, "green")

            h = sim_time // 3600
            m = (sim_time % 3600) // 60
            q = sim.total_queue()
            total_q_sum += q
            n_steps += 1

            hw.show_lcd(
                f"{h:02d}:{m:02d} {PHASE_LABEL[phase]}",
                f"Q:{q:4.0f} {mode[:3]:>3s}"
            )

            demand = sim.get_demand(sim_time)
            print(f"  {h:02d}:{m:02d}  {PHASE_LABEL[phase]}  "
                  f"Q=[A:{sim.queues['A']:5.1f} B:{sim.queues['B']:5.1f} "
                  f"C:{sim.queues['C']:5.1f} D:{sim.queues['D']:5.1f}]  "
                  f"tot={q:6.1f}  dem={sum(demand.values()):6.0f}")

            # ── simulate queue dynamics ───────────────────────────────
            sim.step(phase, green_s, sim_time)

            # ── advance time ──────────────────────────────────────────
            time.sleep(green_s / speed)
            sim_time += green_s
            cycle_idx += 1

    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C")

    # ── summary ───────────────────────────────────────────────────────────
    avg_q = total_q_sum / max(n_steps, 1)
    print(f"\n{'='*60}")
    print(f"  {mode.upper()} COMPLETE")
    print(f"  Steps: {n_steps}  |  Switches: {switches}")
    print(f"  Avg queue: {avg_q:.1f} veh")
    print(f"{'='*60}")

    hw.show_lcd(f"Done {mode[:6]}", f"AvgQ:{avg_q:.1f}")
    time.sleep(3.0)
    hw.cleanup()


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="J1 Adaptive Traffic Signal Demo")
    p.add_argument("--mode", default="hybrid_drl",
                   choices=["fixed", "mp", "hybrid_drl"])
    p.add_argument("--speed", type=float, default=10,
                   help="Playback multiplier (10 = fast demo)")
    p.add_argument("--no-hardware", action="store_true",
                   help="Run without GPIO/LCD (laptop test)")
    args = p.parse_args()
    run(args.mode, args.speed, args.no_hardware)