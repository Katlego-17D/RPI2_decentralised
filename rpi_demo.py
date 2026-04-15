"""
rpi_demo.py  —  J1 Gaborone Hardware Demo
==========================================
Raspberry Pi 2 — inference only, no SUMO, no TraCI.

Reads j1_demand_15min.csv, runs Max Pressure or hybrid DRL,
drives LEDs + LCD, logs metrics JSON for dashboard.

Usage:
    python3 rpi_demo.py                        # hybrid_drl, 30x speed
    python3 rpi_demo.py --mode mp              # Max Pressure only
    python3 rpi_demo.py --mode fixed           # Fixed time baseline
    python3 rpi_demo.py --speed 60             # faster playback
    python3 rpi_demo.py --begin 25200          # start at 07:00
    python3 rpi_demo.py --no-hardware          # test without GPIO/LCD
"""

import csv, time, argparse, math
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent

# =============================================================================
#  GPIO + LCD  — imported only when hardware is available
# =============================================================================
def setup_hardware(use_hw):
    """Returns (gpio_module, lcd_object) or (None, None) if no hardware."""
    if not use_hw:
        print("[INFO] Hardware disabled — console mode")
        return None, None
    try:
        import RPi.GPIO as GPIO
        from RPLCD.i2c import CharLCD
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        pins = [17,27,22,23,5,6,13,19,26,21,20,16,12,8,25,24,7,9,11]
        GPIO.setup(17, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(27, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(22, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(23, GPIO.OUT, initial=GPIO.HIGH)
        for p in [5,6,13,19,26,21,20,16,12,8,25,24,7,9,11]:
            GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
        lcd = CharLCD(
            i2c_expander='PCF8574', address=0x27,
            port=1, cols=16, rows=2, dotsize=8,
            charmap='A02', auto_linebreaks=True, backlight_enabled=True,
        )
        return GPIO, lcd
    except Exception as e:
        print("[WARN] Hardware init failed: " + str(e) + " — console mode")
        return None, None

def cleanup_hardware(GPIO, lcd):
    if lcd:
        try: lcd.clear()
        except: pass
    if GPIO:
        try: GPIO.cleanup()
        except: pass

# =============================================================================
#  LED FUNCTIONS  — take GPIO as parameter (no global state)
# =============================================================================
RED_S=0; GREEN_S=1; AMBER_S=2

def rgb_set(GPIO, r, g, b):
    if not GPIO: return
    GPIO.output(27, GPIO.LOW  if r else GPIO.HIGH)
    GPIO.output(22, GPIO.LOW  if g else GPIO.HIGH)
    GPIO.output(23, GPIO.LOW  if b else GPIO.HIGH)

def cat_set(GPIO, r_pin, g_pin, a_pin, state):
    if not GPIO: return
    GPIO.output(r_pin, GPIO.HIGH if state==RED_S   else GPIO.LOW)
    GPIO.output(g_pin, GPIO.HIGH if state==GREEN_S else GPIO.LOW)
    GPIO.output(a_pin, GPIO.HIGH if state==AMBER_S else GPIO.LOW)

def apply_leds(GPIO, tls_phase):
    """Drive all LEDs for the given TLS green phase (0,2,4,6)."""
    if not GPIO: return
    states = {
        0: [('rgb','red'),  ('D2',GREEN_S),('D1',RED_S),  ('B1',RED_S),  ('B2',RED_S),  ('C1',RED_S)],
        2: [('rgb','green'),('D2',RED_S),  ('D1',RED_S),  ('B1',GREEN_S),('B2',RED_S),  ('C1',RED_S)],
        4: [('rgb','red'),  ('D2',RED_S),  ('D1',RED_S),  ('B1',RED_S),  ('B2',GREEN_S),('C1',RED_S)],
        6: [('rgb','red'),  ('D2',RED_S),  ('D1',GREEN_S),('B1',RED_S),  ('B2',RED_S),  ('C1',GREEN_S)],
    }
    PIN_MAP = {
        'D2':(19,26,21), 'D1':(5,6,13),
        'B1':(20,16,12), 'B2':(8,25,24), 'C1':(7,9,11),
    }
    for item in states.get(tls_phase, []):
        if item[0] == 'rgb':
            if item[1]=='red':   rgb_set(GPIO,1,0,0)
            elif item[1]=='green': rgb_set(GPIO,0,1,0)
            elif item[1]=='amber': rgb_set(GPIO,1,1,0)
        else:
            r,g,a = PIN_MAP[item[0]]
            cat_set(GPIO,r,g,a,item[1])

def all_off(GPIO):
    if not GPIO: return
    rgb_set(GPIO,0,0,0)
    for pins in [(19,26,21),(5,6,13),(20,16,12),(8,25,24),(7,9,11)]:
        for p in pins: GPIO.output(p, GPIO.LOW)
    GPIO.output(17, GPIO.LOW)

def show_lcd(lcd, line1, line2=""):
    if not lcd: return
    try:
        lcd.clear()
        time.sleep(0.05)
        lcd.cursor_pos = (0,0)
        lcd.write_string(line1[:16])
        if line2:
            lcd.cursor_pos = (1,0)
            lcd.write_string(line2[:16])
    except: pass

def blink_boot(GPIO, times=3):
    if not GPIO: return
    for _ in range(times):
        GPIO.output(17, GPIO.HIGH); time.sleep(0.4)
        GPIO.output(17, GPIO.LOW);  time.sleep(0.4)

# =============================================================================
#  AVID DATA LOADER
# =============================================================================
def load_avid(csv_path, begin_s=0):
    rows = []
    with open(csv_path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            slot  = int(float(row['time_slot']))
            hour  = int(float(row['hour']))
            sim_t = slot * 900
            if sim_t < begin_s:
                continue
            e = float(row['E_approach'])
            n = float(row['N_approach'])
            s = float(row['S_approach'])
            a = (e + n + s) / 3.0
            # 50% of 15-min arrivals estimated as queued
            q_b = round(e * 0.5, 1)
            q_d = round(n * 0.5, 1)
            q_c = round(s * 0.5, 1)
            q_a = round(a * 0.5, 1)
            occ   = min((q_b+q_d+q_c+q_a)/80.0, 1.0)
            speed = max(2.0, 13.89*(1-occ))
            rows.append({
                'slot': slot, 'hour': hour, 'sim_time': sim_t,
                'hhmm': f"{hour:02d}:{(slot%4)*15:02d}",
                'A': {'queue':q_a,'occ':occ*100,'speed':speed},
                'B': {'queue':q_b,'occ':occ*100,'speed':speed},
                'C': {'queue':q_c,'occ':occ*100,'speed':speed},
                'D': {'queue':q_d,'occ':occ*100,'speed':speed},
                'out1':{'queue':q_b*0.3}, 'out2':{'queue':q_a*0.3},
                'out3':{'queue':q_c*0.3}, 'out4':{'queue':q_d*0.3},
            })
    return rows

# =============================================================================
#  MAX PRESSURE  (no switching loss — always picks best)
# =============================================================================
PHASES_CYCLE    = [0, 2, 4, 6]
MIN_GREEN_STEPS = 1
MAX_GREEN_STEPS = 4

PHASE_MOVEMENTS = {
    0: [("D","out2",0.25),("D","out2",0.25)],
    2: [("B","out1",0.33),("B","out1",0.33),("A","out2",0.5),("A","out2",0.5)],
    4: [("B","out4",0.33),("C","out2",0.33)],
    6: [("D","out4",0.25),("D","out4",0.25),("C","out3",0.33),("C","out3",0.33)],
}

def compute_pressures(data):
    return {
        ph: round(sum(
            max(0.0, data[a]['queue'] - f*data.get(ex,{'queue':0})['queue'])
            for a,ex,f in mvs if a in data
        ), 3)
        for ph, mvs in PHASE_MOVEMENTS.items()
    }

def mp_select(data, current, elapsed):
    if elapsed < MIN_GREEN_STEPS:
        return current
    pressures = compute_pressures(data)
    return max(pressures, key=pressures.get)

# =============================================================================
#  DQN INFERENCE  (forward pass only, no training)
# =============================================================================
STATE_DIM  = 27
ACTION_DIM = 4
DQN_HIDDEN = [256,128,64]
STARVATION_HARD    = 180
DQN_CONF_THRESHOLD = 1.0

def relu(x): return np.maximum(0.0, x)

class TinyDQN:
    def __init__(self, path):
        self.layers = []
        self.loaded = False
        try:
            d = np.load(str(path))
            i = 0
            while f"W_{i}" in d:
                self.layers.append((d[f"W_{i}"].astype(np.float32),
                                    d[f"b_{i}"].astype(np.float32)))
                i += 1
            self.loaded = True
            print("DQN weights loaded: " + str(len(self.layers)) + " layers")
        except Exception as e:
            print("DQN weights not found: " + str(e))

    def predict(self, state):
        if not self.loaded:
            return np.zeros(ACTION_DIM, dtype=np.float32)
        x = state.astype(np.float32)
        for i,(W,b) in enumerate(self.layers):
            x = x @ W + b
            if i < len(self.layers)-1:
                x = relu(x)
        return x

def build_state(data, phase, elapsed, sim_time, waits):
    arms = ["A","B","C","D"]
    outs = ["out1","out2","out3","out4"]
    q   = [data[a]['queue']/50.0       for a in arms]
    occ = [min(data[a]['occ']/100,1)   for a in arms]
    spd = [max(data[a]['speed'],0)/15  for a in arms]
    ds  = [data.get(o,{'queue':0})['queue']/50 for o in outs]
    ph_oh = [1.0 if PHASES_CYCLE[i]==phase else 0.0 for i in range(4)]
    el    = min(elapsed/MAX_GREEN_STEPS, 1.0)
    hour  = (sim_time//3600)%24
    sin_h = math.sin(2*math.pi*hour/24)
    cos_h = math.cos(2*math.pi*hour/24)
    wait_arr = [min(waits.get(ph,0)/STARVATION_HARD,2.0) for ph in PHASES_CYCLE]
    state = np.array(q+occ+spd+ds+ph_oh+[el,sin_h,cos_h]+wait_arr,
                     dtype=np.float32)
    return state

# =============================================================================
#  PHASE MANAGER
# =============================================================================
class PhaseManager:
    def __init__(self):
        self.current = PHASES_CYCLE[0]
        self.elapsed = 0
        self.waits   = {ph:0 for ph in PHASES_CYCLE}

    def step(self, requested):
        for ph in PHASES_CYCLE:
            if ph != self.current:
                self.waits[ph] += 1
        want  = (requested != self.current and self.elapsed >= MIN_GREEN_STEPS)
        force = (self.elapsed >= MAX_GREEN_STEPS)
        if want or force:
            if force and not want:
                idx = PHASES_CYCLE.index(self.current)
                requested = PHASES_CYCLE[(idx+1)%4]
            self.current = requested
            self.elapsed = 0
            self.waits[self.current] = 0
            return True
        else:
            self.elapsed += 1
            return False

# =============================================================================
#  MAIN RUN FUNCTION
# =============================================================================
PHASE_LABELS = {0:"Ph0 D  36s",2:"Ph2 AB 25s",4:"Ph4 BC 20s",6:"Ph6 CD 36s"}

def run(mode='hybrid_drl', speed=30, csv_path=None, begin_s=0,
        no_hardware=False, metrics_path=None):
    """
    Main simulation loop. Called directly or from rpi_dashboard threads.
    Each parameter is explicit — no global state.
    """
    import json

    if csv_path is None:
        csv_path = str(HERE/'j1_demand_15min.csv')

    # Hardware setup — each call gets its own GPIO/LCD handle
    GPIO, lcd = setup_hardware(not no_hardware)

    # Metrics output
    out_dir = HERE/'output'
    out_dir.mkdir(exist_ok=True)
    if metrics_path is None:
        metrics_path = out_dir/('j1_v2_metrics_'+mode+'.json')
    metrics_path = Path(metrics_path)
    if metrics_path.exists():
        metrics_path.unlink()
    records = []

    print("=== J1 " + mode.upper() + " | speed=" + str(speed) + "x ===")

    rows = load_avid(csv_path, begin_s)
    if not rows:
        print("No data — check CSV path"); cleanup_hardware(GPIO,lcd); return

    # Load DQN if needed
    dqn = None
    if mode == 'hybrid_drl':
        dqn = TinyDQN(HERE/'j1_dqn_weights.npz')
        if not dqn.loaded:
            print("WARNING: no weights — falling back to MP")
            mode = 'mp'

    ph        = PhaseManager()
    step_secs = 900.0 / speed
    total_q   = 0

    # Boot sequence (hardware only)
    if GPIO:
        blink_boot(GPIO, 3)
        show_lcd(lcd, "J1 Gaborone", mode.upper()+" mode")
        time.sleep(1)

    try:
        for i, row in enumerate(rows):
            sim_time = row['sim_time']
            hhmm     = row['hhmm']
            data     = row

            # ── Phase decision ────────────────────────────────────────────────
            if mode == 'fixed':
                requested = PHASES_CYCLE[(i//3)%4]

            elif mode == 'mp':
                requested = mp_select(data, ph.current, ph.elapsed)

            elif mode == 'hybrid_drl':
                mp_phase = mp_select(data, ph.current, ph.elapsed)
                state    = build_state(data, ph.current, ph.elapsed,
                                       sim_time, ph.waits)
                q_vals      = dqn.predict(state)
                drl_idx     = int(np.argmax(q_vals))
                drl_phase   = PHASES_CYCLE[drl_idx]
                sorted_q    = np.sort(q_vals)[::-1]
                confidence  = float(sorted_q[0]-sorted_q[1])
                requested   = drl_phase if (confidence>=DQN_CONF_THRESHOLD
                              and ph.elapsed>=MIN_GREEN_STEPS) else mp_phase
            else:
                requested = ph.current

            switched = ph.step(requested)

            # ── Hardware output ───────────────────────────────────────────────
            apply_leds(GPIO, ph.current)
            qA=data['A']['queue']; qB=data['B']['queue']
            qC=data['C']['queue']; qD=data['D']['queue']
            label = PHASE_LABELS.get(ph.current,"Ph?")
            show_lcd(lcd, hhmm+" "+label[:8],
                     "A"+str(int(qA))+"B"+str(int(qB))+
                     "C"+str(int(qC))+"D"+str(int(qD)))

            # ── Metrics ───────────────────────────────────────────────────────
            records.append({
                't':sim_time,'hhmm':hhmm,'phase':ph.current,
                'sw':int(switched),
                'q_A':round(qA,1),'q_B':round(qB,1),
                'q_C':round(qC,1),'q_D':round(qD,1),
                'occ_A':round(data['A']['occ'],1),
                'occ_B':round(data['B']['occ'],1),
                'occ_C':round(data['C']['occ'],1),
                'occ_D':round(data['D']['occ'],1),
                'spd_A':round(data['A']['speed'],2),
                'spd_B':round(data['B']['speed'],2),
                'spd_C':round(data['C']['speed'],2),
                'spd_D':round(data['D']['speed'],2),
                'reward':0.0,
            })
            # Flush every step so dashboard updates immediately
            with open(metrics_path,'w') as mf:
                json.dump(records, mf)

            q_now = qA+qB+qC+qD
            total_q += q_now
            print(hhmm+" Ph"+str(ph.current)+
                  " A="+str(int(qA))+" B="+str(int(qB))+
                  " C="+str(int(qC))+" D="+str(int(qD))+
                  " Q="+str(int(q_now))+
                  (" [SW]" if switched else ""))

            time.sleep(step_secs)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        n = max(len(records),1)
        print("=== Done | avg Q="+str(round(total_q/n,1))+" | steps="+str(n)+" ===")
        with open(metrics_path,'w') as mf:
            json.dump(records, mf)
        show_lcd(lcd,"Done "+mode[:6],
                 "Q:"+str(round(total_q/n,1)))
        time.sleep(2)
        all_off(GPIO)
        cleanup_hardware(GPIO, lcd)

# =============================================================================
#  ENTRY POINT
# =============================================================================
if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mode',        default='hybrid_drl',
                   choices=['fixed','mp','hybrid_drl'])
    p.add_argument('--speed',       default=30, type=float)
    p.add_argument('--begin',       default=0,  type=int)
    p.add_argument('--csv',         default=str(HERE/'j1_demand_15min.csv'))
    p.add_argument('--no-hardware', action='store_true')
    args = p.parse_args()
    run(args.mode, args.speed, args.csv, args.begin, args.no_hardware)