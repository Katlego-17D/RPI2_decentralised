"""
rpi_demo.py  —  J1 Gaborone Hardware Demo
==========================================
Raspberry Pi 2 — inference only, no SUMO, no TraCI.

Reads j1_demand_15min.csv row by row, runs Max Pressure
or hybrid DRL to select a TLS phase, drives LEDs + LCD.

Files needed (same folder):
    j1_demand_15min.csv
    j1_dqn_weights.npz      (copy from laptop after training)

Usage:
    python3 rpi_demo.py                        # hybrid_drl, full day, 10x speed
    python3 rpi_demo.py --mode mp              # Max Pressure only
    python3 rpi_demo.py --mode fixed           # Fixed time baseline
    python3 rpi_demo.py --speed 1              # real time (15min per step)
    python3 rpi_demo.py --begin 25200          # start at 07:00
    python3 rpi_demo.py --no-hardware          # test on laptop without GPIO
"""

import csv, time, argparse, sys, math
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent

# =============================================================================
#  GPIO + LCD  (gracefully disabled if not on RPi)
# =============================================================================
NO_HW = False
try:
    import RPi.GPIO as GPIO
    from RPLCD.i2c import CharLCD
except ImportError:
    NO_HW = True
    print("[INFO] RPi libraries not found — running in console-only mode")

# ── Pin definitions (confirmed wiring) ───────────────────────────────────────
LED_MONO = 17

# RGB LED common anode — links 7,8 (Arm A, Phase 2)
RGB_R = 27
RGB_G = 22
RGB_B = 23

# Common cathode groups — HIGH=ON
D1_R, D1_G, D1_A = 5,  6,  13   # links 5,6  Arm D→out4  Phase 6
D2_R, D2_G, D2_A = 19, 26, 21   # links 3,4  Arm D→out2  Phase 0
B1_R, B1_G, B1_A = 20, 16, 12   # links 1,2  Arm B→out1  Phase 2
B2_R, B2_G, B2_A = 8,  25, 24   # link  0    Arm B→out4  Phase 4
C1_R, C1_G, C1_A = 7,  9,  11   # links 9,10 Arm C→out3  Phase 6

I2C_ADDR = 0x27

ALL_CATHODE = [
    D1_R, D1_G, D1_A,
    D2_R, D2_G, D2_A,
    B1_R, B1_G, B1_A,
    B2_R, B2_G, B2_A,
    C1_R, C1_G, C1_A,
]

def hw_setup():
    if NO_HW: return None
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(LED_MONO, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(RGB_R, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.setup(RGB_G, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.setup(RGB_B, GPIO.OUT, initial=GPIO.HIGH)
    for p in ALL_CATHODE:
        GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
    lcd = CharLCD(
        i2c_expander='PCF8574', address=I2C_ADDR,
        port=1, cols=16, rows=2, dotsize=8,
        charmap='A02', auto_linebreaks=True, backlight_enabled=True,
    )
    return lcd

def hw_cleanup(lcd):
    if NO_HW: return
    if lcd:
        lcd.clear()
    for p in ALL_CATHODE:
        GPIO.output(p, GPIO.LOW)
    GPIO.output(RGB_R, GPIO.HIGH)
    GPIO.output(RGB_G, GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.HIGH)
    GPIO.output(LED_MONO, GPIO.LOW)
    GPIO.cleanup()

# =============================================================================
#  LED SIGNAL FUNCTIONS
# =============================================================================
RED_S   = 0
GREEN_S = 1
AMBER_S = 2

def rgb_set(r, g, b):
    if NO_HW: return
    GPIO.output(RGB_R, GPIO.LOW  if r else GPIO.HIGH)
    GPIO.output(RGB_G, GPIO.LOW  if g else GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.LOW  if b else GPIO.HIGH)

def cat_set(r_pin, g_pin, a_pin, state):
    if NO_HW: return
    GPIO.output(r_pin, GPIO.HIGH if state == RED_S   else GPIO.LOW)
    GPIO.output(g_pin, GPIO.HIGH if state == GREEN_S  else GPIO.LOW)
    GPIO.output(a_pin, GPIO.HIGH if state == AMBER_S  else GPIO.LOW)

def apply_phase_leds(tls_phase):
    """
    Drive all LEDs to match the TLS phase state.
    TLS states (12 links):
    Ph0: rrrGGrrrrrrr  links 3,4  green
    Ph1: rrryyrrrrrrr  links 3,4  amber
    Ph2: rGGrrrrGGrrr  links 1,2,7,8 green
    Ph3: ryyrrrryyrrr  links 1,2,7,8 amber
    Ph4: GrrrrrrrrrrG  links 0,11 green
    Ph5: yrrrrrrrrrry  links 0,11 amber
    Ph6: rrrrrGGrrGGr  links 5,6,9,10 green
    Ph7: rrrrryyrryyr  links 5,6,9,10 amber
    """
    if tls_phase == 0:
        rgb_set(1,0,0)
        cat_set(D2_R, D2_G, D2_A, GREEN_S)
        cat_set(D1_R, D1_G, D1_A, RED_S)
        cat_set(B1_R, B1_G, B1_A, RED_S)
        cat_set(B2_R, B2_G, B2_A, RED_S)
        cat_set(C1_R, C1_G, C1_A, RED_S)
    elif tls_phase == 1:
        rgb_set(1,0,0)
        cat_set(D2_R, D2_G, D2_A, AMBER_S)
        cat_set(D1_R, D1_G, D1_A, RED_S)
        cat_set(B1_R, B1_G, B1_A, RED_S)
        cat_set(B2_R, B2_G, B2_A, RED_S)
        cat_set(C1_R, C1_G, C1_A, RED_S)
    elif tls_phase == 2:
        rgb_set(0,1,0)
        cat_set(D2_R, D2_G, D2_A, RED_S)
        cat_set(D1_R, D1_G, D1_A, RED_S)
        cat_set(B1_R, B1_G, B1_A, GREEN_S)
        cat_set(B2_R, B2_G, B2_A, RED_S)
        cat_set(C1_R, C1_G, C1_A, RED_S)
    elif tls_phase == 3:
        rgb_set(1,1,0)
        cat_set(D2_R, D2_G, D2_A, RED_S)
        cat_set(D1_R, D1_G, D1_A, RED_S)
        cat_set(B1_R, B1_G, B1_A, AMBER_S)
        cat_set(B2_R, B2_G, B2_A, RED_S)
        cat_set(C1_R, C1_G, C1_A, RED_S)
    elif tls_phase == 4:
        rgb_set(1,0,0)
        cat_set(D2_R, D2_G, D2_A, RED_S)
        cat_set(D1_R, D1_G, D1_A, RED_S)
        cat_set(B1_R, B1_G, B1_A, RED_S)
        cat_set(B2_R, B2_G, B2_A, GREEN_S)
        cat_set(C1_R, C1_G, C1_A, RED_S)
    elif tls_phase == 5:
        rgb_set(1,0,0)
        cat_set(D2_R, D2_G, D2_A, RED_S)
        cat_set(D1_R, D1_G, D1_A, RED_S)
        cat_set(B1_R, B1_G, B1_A, RED_S)
        cat_set(B2_R, B2_G, B2_A, AMBER_S)
        cat_set(C1_R, C1_G, C1_A, RED_S)
    elif tls_phase == 6:
        rgb_set(1,0,0)
        cat_set(D2_R, D2_G, D2_A, RED_S)
        cat_set(D1_R, D1_G, D1_A, GREEN_S)
        cat_set(B1_R, B1_G, B1_A, RED_S)
        cat_set(B2_R, B2_G, B2_A, RED_S)
        cat_set(C1_R, C1_G, C1_A, GREEN_S)
    elif tls_phase == 7:
        rgb_set(1,0,0)
        cat_set(D2_R, D2_G, D2_A, RED_S)
        cat_set(D1_R, D1_G, D1_A, AMBER_S)
        cat_set(B1_R, B1_G, B1_A, RED_S)
        cat_set(B2_R, B2_G, B2_A, RED_S)
        cat_set(C1_R, C1_G, C1_A, AMBER_S)

def show_lcd(lcd, line1, line2=""):
    if NO_HW or not lcd: return
    lcd.clear()
    time.sleep(0.05)
    lcd.cursor_pos = (0, 0)
    lcd.write_string(line1[:16])
    if line2:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])

def blink_boot(times=3):
    if NO_HW: return
    for i in range(times):
        GPIO.output(LED_MONO, GPIO.HIGH)
        time.sleep(0.5)
        GPIO.output(LED_MONO, GPIO.LOW)
        time.sleep(0.5)

# =============================================================================
#  AVID DATA LOADER
# =============================================================================
def load_avid(csv_path, begin_s=0):
    """
    Load j1_demand_15min.csv.
    Columns: time_slot, E_approach, N_approach, S_approach, hour
    Returns list of dicts with arm queues A/B/C/D.

    Arm mapping (J1 geometry):
        E_approach → Arm B (A1 Western Bypass east)
        N_approach → Arm D (Airport Road north)
        S_approach → Arm C (Airport Road south)
        Arm A      → estimated as avg of others (west, no AVID camera)
    """
    rows = []
    with open(csv_path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            slot  = int(float(row['time_slot']))
            hour  = int(float(row['hour']))
            sim_t = slot * 900          # 15 min = 900 seconds
            if sim_t < begin_s:
                continue
            e = float(row['E_approach'])
            n = float(row['N_approach'])
            s = float(row['S_approach'])
            a = (e + n + s) / 3.0      # Arm A estimated

            # Convert veh/15min to queue estimate
            # ~50% of arrivals queued during peak (AVID counts are per 15min)
            q_b = round(e * 0.50, 1)
            q_d = round(n * 0.50, 1)
            q_c = round(s * 0.50, 1)
            q_a = round(a * 0.50, 1)

            # Speed estimate: inverse of occupancy
            occ   = min((q_b + q_d + q_c + q_a) / 80.0, 1.0)
            speed = max(2.0, 13.89 * (1 - occ))

            rows.append({
                'slot':     slot,
                'hour':     hour,
                'sim_time': sim_t,
                'hhmm':     f"{hour:02d}:{(slot % 4) * 15:02d}",
                'A': {'queue': q_a, 'occ': occ*100, 'speed': speed},
                'B': {'queue': q_b, 'occ': occ*100, 'speed': speed},
                'C': {'queue': q_c, 'occ': occ*100, 'speed': speed},
                'D': {'queue': q_d, 'occ': occ*100, 'speed': speed},
                'out1': {'queue': q_b * 0.3},
                'out2': {'queue': q_a * 0.3},
                'out3': {'queue': q_c * 0.3},
                'out4': {'queue': q_d * 0.3},
            })
    return rows

# =============================================================================
#  MAX PRESSURE  (self-contained, no SUMO import)
# =============================================================================
PHASES_CYCLE  = [0, 2, 4, 6]
MIN_GREEN_STEPS = 1   # in 15-min CSV steps (1 step = 15 min)
MAX_GREEN_STEPS = 3
SWITCHING_LOSS  = 0.5  # lowered for AVID queue scale

PHASE_MOVEMENTS = {
    0: [("D","out2",0.25), ("D","out2",0.25)],
    2: [("B","out1",0.33), ("B","out1",0.33), ("A","out2",0.5), ("A","out2",0.5)],
    4: [("B","out4",0.33), ("C","out2",0.33)],
    6: [("D","out4",0.25), ("D","out4",0.25), ("C","out3",0.33), ("C","out3",0.33)],
}

def compute_pressures(data):
    pressures = {}
    for ph, movements in PHASE_MOVEMENTS.items():
        p = sum(
            max(0.0, data[a]['queue'] - f * data.get(ex, {'queue':0})['queue'])
            for a, ex, f in movements if a in data
        )
        pressures[ph] = round(p, 3)
    return pressures

def mp_select(data, current, elapsed):
    if elapsed < MIN_GREEN_STEPS:
        return current
    pressures = compute_pressures(data)
    best = max(pressures, key=pressures.get)
    if best == current:
        return current
    if pressures[best] - pressures.get(current, 0) < SWITCHING_LOSS:
        return current
    return best

# =============================================================================
#  DQN  (inference only — forward pass, load weights from .npz)
# =============================================================================
STATE_DIM    = 27
ACTION_DIM   = 4
DQN_HIDDEN   = [256, 128, 64]
STARVATION_SOFT = 60
STARVATION_HARD = 180
DQN_CONF_THRESHOLD = 1.0

def relu(x):
    return np.maximum(0.0, x)

class TinyDQN:
    """Inference-only forward pass. Loads weights from .npz file."""
    def __init__(self, path):
        self.loaded = False
        try:
            d = np.load(str(path))
            self.layers = []
            i = 0
            while f"W_{i}" in d:
                self.layers.append((d[f"W_{i}"].astype(np.float32),
                                    d[f"b_{i}"].astype(np.float32)))
                i += 1
            self.loaded = True
            print("DQN weights loaded: " + str(len(self.layers)) + " layers")
        except Exception as e:
            print("DQN weights not found: " + str(e))
            print("Running MP only — copy j1_dqn_weights.npz to this folder")

    def predict(self, state):
        if not self.loaded:
            return np.zeros(ACTION_DIM, dtype=np.float32)
        x = state.astype(np.float32)
        for i, (W, b) in enumerate(self.layers):
            x = x @ W + b
            if i < len(self.layers) - 1:
                x = relu(x)
        return x

def build_state(data, current_phase, elapsed, sim_time, waits):
    arms = ["A","B","C","D"]
    outs = ["out1","out2","out3","out4"]
    QN   = 50.0
    SN   = 15.0

    q   = [data[a]['queue'] / QN         for a in arms]
    occ = [min(data[a]['occ'] / 100, 1)  for a in arms]
    spd = [max(data[a]['speed'], 0) / SN for a in arms]
    ds  = [data.get(o, {'queue':0})['queue'] / QN for o in outs]

    ph_oh = [1.0 if PHASES_CYCLE[i] == current_phase else 0.0
             for i in range(4)]
    el    = min(elapsed / MAX_GREEN_STEPS, 1.0)
    hour  = (sim_time // 3600) % 24
    sin_h = math.sin(2 * math.pi * hour / 24)
    cos_h = math.cos(2 * math.pi * hour / 24)
    wait_arr = [min(waits.get(ph, 0) / STARVATION_HARD, 2.0)
                for ph in PHASES_CYCLE]

    state = np.array(q + occ + spd + ds + ph_oh +
                     [el, sin_h, cos_h] + wait_arr, dtype=np.float32)
    return state

# =============================================================================
#  PHASE MANAGER
# =============================================================================
class PhaseManager:
    def __init__(self):
        self.current = PHASES_CYCLE[0]
        self.elapsed = 0
        self.waits   = {ph: 0 for ph in PHASES_CYCLE}
        self.yellow_pending = False
        self.next_phase     = None

    def step(self, requested):
        switched = False
        for ph in PHASES_CYCLE:
            if ph != self.current:
                self.waits[ph] += 1

        want   = (requested != self.current and
                  self.elapsed >= MIN_GREEN_STEPS)
        force  = (self.elapsed >= MAX_GREEN_STEPS)  # force cycle after 3 steps

        if want or force:
            if force and not want:
                idx = PHASES_CYCLE.index(self.current)
                requested = PHASES_CYCLE[(idx+1) % 4]
            self.current = requested
            self.elapsed = 0
            self.waits[self.current] = 0
            switched = True
        else:
            self.elapsed += 1

        return switched

    def tls_phase(self):
        """Return SUMO-style phase index (green phases only for now)."""
        return self.current

# =============================================================================
#  MAIN LOOP
# =============================================================================
PHASE_LABELS = {0:"Ph0 D    36s", 2:"Ph2 AB   25s",
                4:"Ph4 BC   20s", 6:"Ph6 CD   36s"}

def run(mode, speed, csv_path, begin_s, no_hardware):
    global NO_HW
    if no_hardware:
        NO_HW = True

    lcd = hw_setup()

    print("=== J1 Gaborone Hardware Demo ===")
    print("Mode : " + mode.upper())
    print("Speed: " + str(speed) + "x")
    print("=================================")

    # Boot sequence
    blink_boot(3)
    show_lcd(lcd, "J1 Gaborone", mode.upper() + " mode")
    time.sleep(2)

    # Load data
    rows = load_avid(csv_path, begin_s)
    if not rows:
        print("No data loaded — check CSV path and --begin value")
        hw_cleanup(lcd)
        return
    print("Loaded " + str(len(rows)) + " steps from AVID dataset")

    # Load DQN (inference only)
    dqn = None
    if mode == 'hybrid_drl':
        weights_path = HERE / 'j1_dqn_weights.npz'
        dqn = TinyDQN(weights_path)
        if not dqn.loaded:
            print("WARNING: no weights found, falling back to MP")
            mode = 'mp'

    ph  = PhaseManager()
    step_secs   = 900.0 / speed   # 15 min per step / speed
    total_q     = 0
    switches    = 0
    prev_data   = None

    # ── Metrics output ────────────────────────────────────────────────────────
    out_dir = HERE / 'output'
    out_dir.mkdir(exist_ok=True)
    metrics_path = out_dir / ('j1_v2_metrics_' + mode + '.json')
    if metrics_path.exists():
        metrics_path.unlink()
    records  = []
    _since   = 0

    try:
        for row in rows:
            data     = row
            sim_time = row['sim_time']
            hhmm     = row['hhmm']

            # ── Phase decision ────────────────────────────────────────────────
            if mode == 'fixed':
                # Fixed: cycle through phases every 3 steps
                idx = (row['slot'] // 3) % 4
                requested = PHASES_CYCLE[idx]

            elif mode == 'mp':
                requested = mp_select(data, ph.current, ph.elapsed)

            elif mode == 'hybrid_drl':
                # Pure MP recommendation
                mp_phase = mp_select(data, ph.current, ph.elapsed)
                # DQN recommendation
                state = build_state(data, ph.current, ph.elapsed,
                                    sim_time, ph.waits)
                q_vals = dqn.predict(state)
                drl_idx = int(np.argmax(q_vals))
                drl_phase = PHASES_CYCLE[drl_idx]
                sorted_q  = np.sort(q_vals)[::-1]
                confidence = float(sorted_q[0] - sorted_q[1])
                # Hybrid: DQN leads when confident
                if confidence >= DQN_CONF_THRESHOLD and ph.elapsed >= MIN_GREEN_STEPS:
                    requested = drl_phase
                else:
                    requested = mp_phase
            else:
                requested = ph.current

            switched = ph.step(requested)
            if switched:
                switches += 1

            # ── Drive LEDs ────────────────────────────────────────────────────
            tls_ph = ph.tls_phase()
            apply_phase_leds(tls_ph)

            # ── LCD update ────────────────────────────────────────────────────
            qA = data['A']['queue']
            qB = data['B']['queue']
            qC = data['C']['queue']
            qD = data['D']['queue']
            label = PHASE_LABELS.get(tls_ph, "Ph?")
            line1 = hhmm + " " + label[:8]
            line2 = "A" + str(int(qA)) + "B" + str(int(qB)) + \
                    "C" + str(int(qC)) + "D" + str(int(qD))
            show_lcd(lcd, line1, line2)

            # ── Console ───────────────────────────────────────────────────────
            total_q_now = qA + qB + qC + qD
            total_q += total_q_now
            print(hhmm + " Ph" + str(tls_ph) +
                  " A=" + str(int(qA)) +
                  " B=" + str(int(qB)) +
                  " C=" + str(int(qC)) +
                  " D=" + str(int(qD)) +
                  " Q=" + str(int(total_q_now)) +
                  (" [SWITCH]" if switched else ""))

            # ── Log metrics ──────────────────────────────────────────────────
            records.append({
                't':      sim_time,
                'hhmm':   hhmm,
                'phase':  tls_ph,
                'sw':     int(switched),
                'q_A':    round(qA, 1),
                'q_B':    round(qB, 1),
                'q_C':    round(qC, 1),
                'q_D':    round(qD, 1),
                'occ_A':  round(data['A']['occ'], 1),
                'occ_B':  round(data['B']['occ'], 1),
                'occ_C':  round(data['C']['occ'], 1),
                'occ_D':  round(data['D']['occ'], 1),
                'spd_A':  round(data['A']['speed'], 2),
                'spd_B':  round(data['B']['speed'], 2),
                'spd_C':  round(data['C']['speed'], 2),
                'spd_D':  round(data['D']['speed'], 2),
                'reward': 0.0,
            })
            # Flush every 5 steps so dashboard sees live updates
            if len(records) - _since >= 5:
                import json
                with open(metrics_path, 'w') as mf:
                    json.dump(records, mf)
                _since = len(records)

            prev_data = data
            time.sleep(step_secs)

    except KeyboardInterrupt:
        print("\nStopped by user.")

    finally:
        n = max(len(rows), 1)
        print("\n=== Summary ===")
        print("Steps    : " + str(n))
        print("Avg queue: " + str(round(total_q / n, 1)) + " veh")
        print("Switches : " + str(switches))

        show_lcd(lcd, "Done " + mode[:6],
                 "Q:" + str(round(total_q/n,1)) + " sw:" + str(switches))
        time.sleep(3)
        hw_cleanup(lcd)
        print("Cleaned up.")

# =============================================================================
#  ENTRY POINT
# =============================================================================
if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mode',        default='hybrid_drl',
                   choices=['fixed', 'mp', 'hybrid_drl'])
    p.add_argument('--speed',       default=10, type=float,
                   help='Playback speed (10=fast demo, 1=real time)')
    p.add_argument('--begin',       default=0, type=int,
                   help='Start time in seconds (0=midnight, 25200=07:00)')
    p.add_argument('--csv',         default=str(HERE/'j1_demand_15min.csv'))
    p.add_argument('--no-hardware', action='store_true',
                   help='Console-only mode (no GPIO/LCD)')
    args = p.parse_args()

    run(args.mode, args.speed, args.csv, args.begin, args.no_hardware)