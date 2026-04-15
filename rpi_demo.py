#!/usr/bin/env python3
"""
rpi_demo.py  —  Adaptive Traffic Signal Demo on Raspberry Pi 2
===============================================================
Drives 6 signal groups matching blinkv1.py hardware exactly.

Hardware — 6 signal groups:
  RGB  (common ANODE,  links 7,8)   Arm A->out2  Phase 2  R=27 G=22 B=23
  D2   (common cathode, links 3,4)  Arm D->out2  Phase 0  R=19 G=26 A=21
  D1   (common cathode, links 5,6)  Arm D->out4  Phase 6  R=5  G=6  A=13
  B1   (common cathode, links 1,2)  Arm B->out1  Phase 2  R=20 G=16 A=12
  B2   (common cathode, link 0)     Arm B->out4  Phase 4  R=8  G=25 A=24
  C1   (common cathode, links 9,10) Arm C->out3  Phase 6  R=7  G=9  A=11
  Mono LED: GPIO 17  |  LCD 16x2 I2C at 0x27

TLS phase -> signal group map:
  Ph0  rrrGGrrrrrrr  D2=green                rest=red
  Ph1  rrryyrrrrrrr  D2=amber                rest=red
  Ph2  rGGrrrrGGrrr  B1=green + RGB=green    rest=red
  Ph3  ryyrrrryyrrr  B1=amber + RGB=amber    rest=red
  Ph4  GrrrrrrrrrrG  B2=green                rest=red
  Ph5  yrrrrrrrrrry  B2=amber                rest=red
  Ph6  rrrrrGGrrGGr  D1=green + C1=green     rest=red
  Ph7  rrrrryyrryyr  D1=amber + C1=amber     rest=red
"""

import time, argparse, math, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent

# ═════════════════════════════════════════════════════════════════════════
# DEMAND PROFILE — averaged from all 31 SUMO route files (Oct 1-31, 2025)
# (seconds_into_day, A_vph, B_vph, C_vph, D_vph)
# ═════════════════════════════════════════════════════════════════════════
DEMAND = [
    (    0, 120.6, 118.6, 118.6, 119.5),
    (  900, 119.9, 118.1, 118.1, 118.2),
    ( 1800, 111.5, 110.1, 110.1, 110.1),
    ( 2700,  99.9,  98.0,  98.0,  97.9),
    ( 3600,  91.8,  90.5,  90.5,  90.6),
    ( 4500,  80.9,  79.1,  79.1,  79.6),
    ( 5400,  71.1,  71.3,  71.3,  72.3),
    ( 6300,  61.0,  58.9,  58.9,  59.5),
    ( 7200,  59.4,  57.1,  57.1,  59.4),
    ( 8100,  54.9,  52.3,  52.3,  54.4),
    ( 9000,  48.0,  45.5,  45.5,  47.3),
    ( 9900,  50.4,  47.8,  47.8,  49.8),
    (10800,  48.5,  45.6,  45.6,  49.3),
    (11700,  52.7,  50.6,  50.6,  51.5),
    (12600,  53.3,  51.1,  51.1,  51.9),
    (13500,  53.0,  50.2,  50.2,  52.9),
    (14400,  59.9,  57.9,  57.9,  58.4),
    (15300,  68.3,  66.4,  66.4,  66.5),
    (16200,  82.9,  81.0,  81.0,  81.4),
    (17100, 109.0, 106.8, 106.8, 107.1),
    (18000, 128.0, 126.2, 126.2, 126.7),
    (18900, 172.9, 170.9, 170.9, 171.8),
    (19800, 253.2, 251.7, 251.7, 252.3),
    (20700, 360.4, 359.2, 359.2, 359.9),
    (21600, 547.3, 545.9, 545.9, 546.4),
    (22500, 727.8, 726.8, 726.8, 727.2),
    (23400, 869.8, 868.6, 868.6, 869.1),
    (24300, 958.5, 957.4, 957.4, 958.0),
    (25200, 984.1, 983.2, 983.2, 983.5),  # AM peak
    (26100, 974.1, 973.4, 973.4, 973.9),
    (27000, 953.5, 953.0, 953.0, 953.4),
    (27900, 915.9, 915.5, 915.5, 915.7),
    (28800, 865.6, 865.2, 865.2, 865.6),
    (29700, 828.3, 828.0, 828.0, 828.2),
    (30600, 786.5, 786.1, 786.1, 786.3),
    (31500, 780.4, 780.1, 780.1, 780.4),
    (32400, 780.0, 779.9, 779.9, 780.0),
    (33300, 778.2, 778.1, 778.1, 778.2),
    (34200, 775.0, 775.0, 775.0, 775.0),
    (35100, 802.7, 802.5, 802.5, 802.6),
    (36000, 812.8, 812.7, 812.7, 812.7),
    (36900, 803.5, 803.3, 803.3, 803.5),
    (37800, 801.4, 801.1, 801.1, 801.4),
    (38700, 840.9, 840.8, 840.8, 840.9),
    (39600, 816.8, 816.7, 816.7, 816.8),
    (40500, 832.2, 832.0, 832.0, 832.2),
    (41400, 847.9, 847.7, 847.7, 847.9),
    (42300, 845.2, 845.0, 845.0, 845.1),
    (43200, 853.5, 853.2, 853.2, 853.4),
    (44100, 870.2, 870.0, 870.0, 870.1),
    (45000, 889.1, 889.0, 889.0, 889.1),
    (45900, 885.6, 885.6, 885.6, 885.6),
    (46800, 867.8, 867.6, 867.6, 867.6),
    (47700, 888.7, 888.5, 888.5, 888.5),
    (48600, 907.2, 906.9, 906.9, 907.2),
    (49500, 904.6, 904.5, 904.5, 904.5),
    (50400, 899.6, 899.4, 899.4, 899.3),
    (51300, 894.7, 894.4, 894.4, 894.6),
    (52200, 894.9, 894.7, 894.7, 894.9),
    (53100, 889.2, 889.0, 889.0, 889.2),
    (54000, 874.8, 874.6, 874.6, 874.8),
    (54900, 885.9, 885.7, 885.7, 885.9),
    (55800, 874.7, 874.6, 874.6, 874.5),
    (56700, 882.6, 882.3, 882.3, 882.4),
    (57600, 872.8, 872.7, 872.7, 872.8),
    (58500, 859.8, 859.7, 859.7, 859.8),
    (59400, 883.3, 883.2, 883.2, 883.1),
    (60300, 893.6, 893.3, 893.3, 893.3),
    (61200, 897.9, 897.8, 897.8, 897.8),
    (62100, 908.0, 907.9, 907.9, 907.9),  # PM peak
    (63000, 906.8, 906.7, 906.7, 906.7),
    (63900, 876.3, 876.0, 876.0, 876.2),
    (64800, 814.3, 813.8, 813.8, 814.0),
    (65700, 776.0, 775.2, 775.2, 775.7),
    (66600, 713.6, 712.9, 712.9, 713.4),
    (67500, 664.6, 664.0, 664.0, 664.5),
    (68400, 630.4, 629.9, 629.9, 630.1),
    (69300, 613.2, 612.8, 612.8, 613.1),
    (70200, 567.3, 566.6, 566.6, 566.9),
    (71100, 528.7, 528.2, 528.2, 528.5),
    (72000, 476.3, 475.9, 475.9, 476.1),
    (72900, 435.4, 434.6, 434.6, 435.2),
    (73800, 404.0, 403.3, 403.3, 403.7),
    (74700, 364.4, 363.7, 363.7, 363.8),
    (75600, 337.0, 336.5, 336.5, 336.6),
    (76500, 303.5, 302.7, 302.7, 303.3),
    (77400, 288.3, 287.7, 287.7, 287.7),
    (78300, 257.4, 256.3, 256.3, 256.7),
    (79200, 239.6, 238.4, 238.4, 238.3),
    (80100, 216.4, 214.9, 214.9, 215.6),
    (81000, 183.9, 182.6, 182.6, 182.7),
    (81900, 164.3, 162.6, 162.6, 163.5),
    (82800, 148.5, 147.1, 147.1, 147.4),
    (83700, 136.5, 135.0, 135.0, 135.5),
    (84600, 111.3, 109.7, 109.7, 110.1),
    (85500,  97.8,  96.2,  96.2,  96.7),
]

# ═════════════════════════════════════════════════════════════════════════
# TLS PHASE DEFINITIONS
# ═════════════════════════════════════════════════════════════════════════
PHASE_GREEN = [0, 2, 4, 6]
PHASE_LABEL = {0: "Ph0 D ", 2: "Ph2 AB", 4: "Ph4 BC", 6: "Ph6 CD"}

PHASE_DRAIN = {
    0: {"A": 0.0, "B": 0.0, "C": 0.0, "D": 1.0},
    2: {"A": 1.0, "B": 0.5, "C": 0.0, "D": 0.0},
    4: {"A": 0.0, "B": 0.5, "C": 0.5, "D": 0.0},
    6: {"A": 0.0, "B": 0.0, "C": 1.0, "D": 0.5},
}

PHASE_UPSTREAM = {
    0: ["D"],
    2: ["A", "B"],
    4: ["B", "C"],
    6: ["C", "D"],
}

FIXED_GREEN_S = 30
YELLOW_S      = 4
SERVICE_RATE  = 1800

# ═════════════════════════════════════════════════════════════════════════
# GPIO PIN MAP — matches blinkv1.py exactly
# ═════════════════════════════════════════════════════════════════════════
RGB_R, RGB_G, RGB_B = 27, 22, 23          # common ANODE
D2_PINS = (19, 26, 21)                    # links 3,4
D1_PINS = ( 5,  6, 13)                    # links 5,6
B1_PINS = (20, 16, 12)                    # links 1,2
B2_PINS = ( 8, 25, 24)                    # link 0
C1_PINS = ( 7,  9, 11)                    # links 9,10
LED_MONO = 17
ALL_CATHODE = [D2_PINS, D1_PINS, B1_PINS, B2_PINS, C1_PINS]

# Phase -> (RGB, D2, D1, B1, B2, C1)  states: r/g/a
PHASE_SIGNALS = {
    0: ('r','g','r','r','r','r'),   # D2 green
    1: ('r','a','r','r','r','r'),   # D2 amber
    2: ('g','r','r','g','r','r'),   # RGB+B1 green
    3: ('a','r','r','a','r','r'),   # RGB+B1 amber
    4: ('r','r','r','r','g','r'),   # B2 green
    5: ('r','r','r','r','a','r'),   # B2 amber
    6: ('r','r','g','r','r','g'),   # D1+C1 green
    7: ('r','r','a','r','r','a'),   # D1+C1 amber
}

# ═════════════════════════════════════════════════════════════════════════
# DQN AGENT — inference only, auto-detects weight keys
# ═════════════════════════════════════════════════════════════════════════
class DQNInference:
    def __init__(self, weights_path):
        data = np.load(weights_path)
        keys = sorted(data.files)
        print(f"DQN loaded: {weights_path}")
        print(f"  keys: {keys}")

        if "W1" in keys:
            self.layers = [(data["W1"],data["b1"]),(data["W2"],data["b2"]),
                           (data["W3"],data["b3"]),(data["W4"],data["b4"])]
        elif "fc1.weight" in keys:
            self.layers = [(data["fc1.weight"],data["fc1.bias"]),
                           (data["fc2.weight"],data["fc2.bias"]),
                           (data["fc3.weight"],data["fc3.bias"]),
                           (data["fc4.weight"],data["fc4.bias"])]
        else:
            # positional: arr_0/arr_1/... — alternating W, b
            arrs = [data[k] for k in keys]
            self.layers = []
            for i in range(0, len(arrs), 2):
                W, b = arrs[i], arrs[i+1]
                if W.ndim == 1 and b.ndim == 2:
                    W, b = b, W
                self.layers.append((W, b))
            print(f"  auto-detected {len(self.layers)} layers")

        for i,(W,b) in enumerate(self.layers):
            print(f"  L{i}: W{list(W.shape)} b{list(b.shape)}")

    def predict(self, state):
        x = np.array(state, dtype=np.float32)
        for i,(W,b) in enumerate(self.layers):
            x = W @ x + b
            if i < len(self.layers) - 1:
                x = np.maximum(0, x)
        return x

    def act(self, state):
        return int(np.argmax(self.predict(state)))

# ═════════════════════════════════════════════════════════════════════════
# QUEUE SIMULATOR
# ═════════════════════════════════════════════════════════════════════════
class QueueSim:
    def __init__(self):
        self.queues = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
        self.wait   = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}

    def get_demand(self, sim_time):
        idx = min(int(sim_time // 900), len(DEMAND) - 1)
        _, a, b, c, d = DEMAND[idx]
        return {"A": a, "B": b, "C": c, "D": d}

    def step(self, phase, green_s, sim_time):
        demand = self.get_demand(sim_time)
        drain  = PHASE_DRAIN[phase]
        for arm in "ABCD":
            arr = demand[arm] * (green_s / 3600.0)
            srv = drain[arm] * SERVICE_RATE * (green_s / 3600.0)
            self.queues[arm] = max(0.0, self.queues[arm] + arr - srv)
            if drain[arm] > 0:
                self.wait[arm] = max(0.0, self.wait[arm] - green_s)
            else:
                self.wait[arm] += green_s

    def total_queue(self):
        return sum(self.queues.values())

    def build_state(self, current_phase_idx, sim_time):
        demand = self.get_demand(sim_time)
        hour = (sim_time % 86400) / 86400.0
        s = []
        for arm in "ABCD":
            s += [self.queues[arm]/50, self.wait[arm]/120, demand[arm]/1000]
        s += [1.0 if i == current_phase_idx else 0.0 for i in range(4)]
        for ph in PHASE_GREEN:
            s.append(sum(self.queues[a] for a in PHASE_UPSTREAM[ph]) / 100)
        s += [hour, math.sin(2*math.pi*hour), math.cos(2*math.pi*hour)]
        s.append(max(self.wait.values()) / 120)
        s.append(self.total_queue() / 200)
        vals = list(demand.values())
        s.append((max(vals) - min(vals)) / 500)
        return s  # 27-dim

# ═════════════════════════════════════════════════════════════════════════
# HARDWARE INTERFACE — all 6 signal groups + LCD
# ═════════════════════════════════════════════════════════════════════════
class HardwareIO:
    def __init__(self, skip_hw=False):
        self.gpio = None
        self.lcd  = None
        if skip_hw:
            print("[HW] Console-only mode")
            return
        try:
            import RPi.GPIO as GPIO
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(LED_MONO, GPIO.OUT, initial=GPIO.LOW)
            for pin in (RGB_R, RGB_G, RGB_B):
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)  # anode: HIGH=OFF
            for grp in ALL_CATHODE:
                for pin in grp:
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
            self.gpio = GPIO
            print("[HW] GPIO ready — 6 groups (18 pins) + mono LED")
        except Exception as e:
            print(f"[HW] No GPIO ({e})")
        try:
            from RPLCD.i2c import CharLCD
            self.lcd = CharLCD("PCF8574", 0x27, port=1, cols=16, rows=2)
            self.lcd.clear()
            print("[HW] LCD at 0x27")
        except Exception as e:
            print(f"[HW] No LCD ({e})")

    def _rgb(self, state):
        if not self.gpio: return
        G = self.gpio
        if   state == 'g': G.output(RGB_R,1); G.output(RGB_G,0); G.output(RGB_B,1)
        elif state == 'a': G.output(RGB_R,0); G.output(RGB_G,0); G.output(RGB_B,1)
        elif state == 'r': G.output(RGB_R,0); G.output(RGB_G,1); G.output(RGB_B,1)
        else:              G.output(RGB_R,1); G.output(RGB_G,1); G.output(RGB_B,1)

    def _cat(self, pins, state):
        if not self.gpio: return
        r,g,a = pins
        self.gpio.output(r, 1 if state == 'r' else 0)
        self.gpio.output(g, 1 if state == 'g' else 0)
        self.gpio.output(a, 1 if state == 'a' else 0)

    def apply_phase(self, tls_ph):
        if not self.gpio: return
        rgb_s, d2, d1, b1, b2, c1 = PHASE_SIGNALS[tls_ph]
        self._rgb(rgb_s)
        self._cat(D2_PINS, d2)
        self._cat(D1_PINS, d1)
        self._cat(B1_PINS, b1)
        self._cat(B2_PINS, b2)
        self._cat(C1_PINS, c1)

    def all_red(self):
        if not self.gpio: return
        self._rgb('r')
        for grp in ALL_CATHODE:
            self._cat(grp, 'r')

    def show_lcd(self, l1, l2=""):
        if self.lcd:
            try:
                self.lcd.clear()
                self.lcd.write_string(l1[:16])
                if l2: self.lcd.crlf(); self.lcd.write_string(l2[:16])
            except: pass
        print(f"  LCD| {l1:<16s} | {l2:<16s}")

    def blink_boot(self):
        if not self.gpio: return
        for _ in range(3):
            self.gpio.output(LED_MONO, 1); time.sleep(0.4)
            self.gpio.output(LED_MONO, 0); time.sleep(0.4)

    def cleanup(self):
        if self.gpio:
            self.all_red()
            self.gpio.output(LED_MONO, 0)
            self.gpio.cleanup()
        if self.lcd:
            try: self.lcd.clear(); self.lcd.write_string("Demo stopped")
            except: pass

# ═════════════════════════════════════════════════════════════════════════
# CONTROLLER LOGIC
# ═════════════════════════════════════════════════════════════════════════
def pick_fixed(ci):    return PHASE_GREEN[ci % 4]

def pick_mp(sim):
    return max(PHASE_GREEN, key=lambda ph: sum(sim.queues[a] for a in PHASE_UPSTREAM[ph]))

def pick_drl(sim, dqn, pi, st):
    return PHASE_GREEN[dqn.act(sim.build_state(pi, st))]

# ═════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═════════════════════════════════════════════════════════════════════════
def run(mode, speed, no_hw):
    hw  = HardwareIO(skip_hw=no_hw)
    sim = QueueSim()
    hw.blink_boot()
    hw.show_lcd("J1 Gaborone", f"Mode: {mode[:10]}")
    time.sleep(2.0 / speed)

    dqn = None
    if mode == "hybrid_drl":
        wp = HERE / "j1_dqn_weights.npz"
        if wp.exists():
            try: dqn = DQNInference(str(wp))
            except Exception as e:
                print(f"[WARN] DQN failed ({e}) -> MP"); mode = "mp"
        else:
            print(f"[WARN] {wp} not found -> MP"); mode = "mp"

    sim_t = 0; ci = 0; pi = 0; tot_q = 0.0; ns = 0; sw = 0

    print(f"\n{'='*60}\n  J1 ADAPTIVE SIGNAL — {mode.upper()}\n  Speed: {speed}x\n{'='*60}\n")

    try:
        while sim_t < 86400:
            if   mode == "fixed":      ph = pick_fixed(ci)
            elif mode == "mp":         ph = pick_mp(sim)
            else:                      ph = pick_drl(sim, dqn, pi, sim_t)

            ni = PHASE_GREEN.index(ph)
            if ni != pi:
                sw += 1
                hw.apply_phase(PHASE_GREEN[pi] + 1)  # yellow
                h = sim_t // 3600; m = (sim_t % 3600) // 60
                hw.show_lcd(f"{h:02d}:{m:02d} YELLOW", PHASE_LABEL[PHASE_GREEN[pi]])
                time.sleep(YELLOW_S / speed)
                hw.all_red()
                time.sleep(1.0 / speed)
            pi = ni

            hw.apply_phase(ph)
            h = sim_t // 3600; m = (sim_t % 3600) // 60
            q = sim.total_queue(); tot_q += q; ns += 1
            dem = sim.get_demand(sim_t)

            hw.show_lcd(f"{h:02d}:{m:02d} {PHASE_LABEL[ph]}", f"Q:{q:4.0f} {mode[:3]:>3s}")
            print(f"  {h:02d}:{m:02d}  {PHASE_LABEL[ph]}  "
                  f"Q=[A:{sim.queues['A']:5.1f} B:{sim.queues['B']:5.1f} "
                  f"C:{sim.queues['C']:5.1f} D:{sim.queues['D']:5.1f}]  "
                  f"tot={q:6.1f}  dem={sum(dem.values()):6.0f}")

            sim.step(ph, FIXED_GREEN_S, sim_t)
            time.sleep(FIXED_GREEN_S / speed)
            sim_t += FIXED_GREEN_S; ci += 1
    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C")

    avg = tot_q / max(ns, 1)
    print(f"\n{'='*60}\n  {mode.upper()} DONE | Steps:{ns} Sw:{sw} AvgQ:{avg:.1f}\n{'='*60}")
    hw.show_lcd(f"Done {mode[:6]}", f"AvgQ:{avg:.1f}")
    time.sleep(3.0); hw.cleanup()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="hybrid_drl", choices=["fixed","mp","hybrid_drl"])
    p.add_argument("--speed", type=float, default=10)
    p.add_argument("--no-hardware", action="store_true")
    a = p.parse_args()
    run(a.mode, a.speed, a.no_hardware)