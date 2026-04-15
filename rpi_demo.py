#!/usr/bin/env python3
"""
rpi_demo.py — Adaptive Traffic Signal Demo on Raspberry Pi 2
Real AVID demand (asymmetric E/N/S) · Equity forcing · 6 signal groups
"""
import time, argparse, math, sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).parent

# ═══════════════════════════════════════════════════════════════
# AVID DEMAND — real per-camera hourly data (Oct 2025, 31 days)
# (hour): (AVID_E_vph, AVID_N_vph, AVID_S_vph)
# ═══════════════════════════════════════════════════════════════
AVID_HOURLY = {
     0:( 64.1, 95.2, 67.4),  1:( 42.4, 64.0, 47.1),
     2:( 28.1, 45.7, 33.7),  3:( 25.3, 45.6, 34.2),
     4:( 35.6, 78.2, 47.3),  5:(133.2,183.1,141.5),
     6:(660.8,368.4,522.6),  7:(841.5,528.2,544.1),
     8:(630.6,506.8,493.0),  9:(534.3,513.3,520.5),
    10:(539.3,559.6,530.4), 11:(546.6,583.8,540.6),
    12:(575.1,613.1,561.0), 13:(571.1,662.0,551.0),
    14:(575.0,646.2,568.0), 15:(547.7,666.4,544.9),
    16:(530.5,726.1,498.1), 17:(553.4,776.1,465.0),
    18:(424.7,628.3,431.3), 19:(303.0,491.6,375.2),
    20:(193.8,367.0,279.3), 21:(129.9,261.0,202.3),
    22:( 82.8,182.7,136.9), 23:( 46.8,115.7, 85.4),
}

def get_demand(sim_time):
    """Map AVID cameras to arms: E→B, N→D, S→C, A≈0.7×E"""
    h = min(int(sim_time // 3600), 23)
    e, n, s = AVID_HOURLY[h]
    return {"A": e * 0.7, "B": e, "C": s, "D": n}

# ═══════════════════════════════════════════════════════════════
# TLS PHASES + CALIBRATED PARAMETERS
# ═══════════════════════════════════════════════════════════════
PHASE_GREEN = [0, 2, 4, 6]
PHASE_LABEL = {0:"Ph0 D ", 2:"Ph2 AB", 4:"Ph4 BC", 6:"Ph6 CD"}
PHASE_DRAIN = {
    0: {"A":0.0,"B":0.0,"C":0.0,"D":1.0},
    2: {"A":1.0,"B":0.5,"C":0.0,"D":0.0},
    4: {"A":0.0,"B":0.5,"C":0.5,"D":0.0},
    6: {"A":0.0,"B":0.0,"C":1.0,"D":0.5},
}
PHASE_UPSTREAM = {0:["D"], 2:["A","B"], 4:["B","C"], 6:["C","D"]}

GREEN_S      = 30
YELLOW_S     = 4
SERVICE_RATE = 2200    # calibrated to match SUMO queue scale
QUEUE_DECAY  = 0.985   # natural dissipation (vehicles reroute/leave)
EQUITY_MAX   = 90      # force phase after 90s without green

# ═══════════════════════════════════════════════════════════════
# GPIO — matches blinkv1.py exactly
# ═══════════════════════════════════════════════════════════════
RGB_R, RGB_G, RGB_B = 27, 22, 23   # common ANODE
D2_PINS = (19,26,21); D1_PINS = (5,6,13)
B1_PINS = (20,16,12); B2_PINS = (8,25,24)
C1_PINS = (7,9,11);   LED_MONO = 17
ALL_CATHODE = [D2_PINS, D1_PINS, B1_PINS, B2_PINS, C1_PINS]

PHASE_SIGNALS = {
    0:('r','g','r','r','r','r'), 1:('r','a','r','r','r','r'),
    2:('g','r','r','g','r','r'), 3:('a','r','r','a','r','r'),
    4:('r','r','r','r','g','r'), 5:('r','r','r','r','a','r'),
    6:('r','r','g','r','r','g'), 7:('r','r','a','r','r','a'),
}

# ═══════════════════════════════════════════════════════════════
# DQN INFERENCE — auto-detects weight keys
# ═══════════════════════════════════════════════════════════════
class DQNInference:
    def __init__(self, path):
        data = np.load(path); keys = sorted(data.files)
        print(f"DQN loaded: {keys}")
        if "W1" in keys:
            self.L=[(data[f"W{i}"],data[f"b{i}"]) for i in range(1,5)]
        elif "fc1.weight" in keys:
            self.L=[(data[f"fc{i}.weight"],data[f"fc{i}.bias"]) for i in range(1,5)]
        else:
            a=[data[k] for k in keys]; self.L=[]
            for i in range(0,len(a),2):
                W,b=a[i],a[i+1]
                if W.ndim==1 and b.ndim==2: W,b=b,W
                self.L.append((W,b))
        for i,(W,b) in enumerate(self.L): print(f"  L{i}: {W.shape} {b.shape}")

    def act(self, state):
        x=np.array(state,dtype=np.float32)
        for i,(W,b) in enumerate(self.L):
            x=W@x+b
            if i<len(self.L)-1: x=np.maximum(0,x)
        return int(np.argmax(x))

# ═══════════════════════════════════════════════════════════════
# QUEUE SIMULATOR
# ═══════════════════════════════════════════════════════════════
class QueueSim:
    def __init__(self):
        self.queues = {a:0.0 for a in "ABCD"}
        self.wait   = {a:0.0 for a in "ABCD"}

    def step(self, phase, sim_time):
        dem = get_demand(sim_time)
        drain = PHASE_DRAIN[phase]
        for arm in "ABCD":
            arr = dem[arm] * (GREEN_S / 3600.0)
            srv = drain[arm] * SERVICE_RATE * (GREEN_S / 3600.0)
            self.queues[arm] = max(0.0, self.queues[arm] * QUEUE_DECAY + arr - srv)
            self.wait[arm] = 0 if drain[arm] > 0 else self.wait[arm] + GREEN_S

    def total_queue(self): return sum(self.queues.values())

    def build_state(self, phase_idx, sim_time):
        dem = get_demand(sim_time); h = (sim_time % 86400) / 86400.0
        s = []
        for arm in "ABCD":
            s += [self.queues[arm]/50, self.wait[arm]/120, dem[arm]/1000]
        s += [1.0 if i==phase_idx else 0.0 for i in range(4)]
        for ph in PHASE_GREEN:
            s.append(sum(self.queues[a] for a in PHASE_UPSTREAM[ph])/100)
        s += [h, math.sin(2*math.pi*h), math.cos(2*math.pi*h)]
        s.append(max(self.wait.values())/120)
        s.append(self.total_queue()/200)
        v = list(dem.values()); s.append((max(v)-min(v))/500)
        return s

# ═══════════════════════════════════════════════════════════════
# PHASE SELECTION WITH EQUITY FORCING
# ═══════════════════════════════════════════════════════════════
def pick_fixed(ci):
    return PHASE_GREEN[ci % 4]

def pick_mp(sim):
    # Force starved phases first
    for ph in PHASE_GREEN:
        if any(sim.wait[a] >= EQUITY_MAX for a in PHASE_UPSTREAM[ph]):
            return ph
    return max(PHASE_GREEN, key=lambda p: sum(sim.queues[a] for a in PHASE_UPSTREAM[p]))

def pick_drl(sim, dqn, pi, sim_time):
    # Force starved phases first
    for ph in PHASE_GREEN:
        if any(sim.wait[a] >= EQUITY_MAX for a in PHASE_UPSTREAM[ph]):
            return ph
    if dqn:
        return PHASE_GREEN[dqn.act(sim.build_state(pi, sim_time))]
    # Fallback: pressure + equity-weighted heuristic (better than pure MP)
    return max(PHASE_GREEN, key=lambda p:
        sum(sim.queues[a] for a in PHASE_UPSTREAM[p]) +
        0.5 * max(sim.wait[a] for a in PHASE_UPSTREAM[p]))

# ═══════════════════════════════════════════════════════════════
# HARDWARE I/O
# ═══════════════════════════════════════════════════════════════
class HardwareIO:
    def __init__(self, skip=False):
        self.gpio=None; self.lcd=None
        if skip: print("[HW] Console mode"); return
        try:
            import RPi.GPIO as GPIO
            GPIO.setwarnings(False); GPIO.setmode(GPIO.BCM)
            GPIO.setup(LED_MONO,GPIO.OUT,initial=GPIO.LOW)
            for p in (RGB_R,RGB_G,RGB_B): GPIO.setup(p,GPIO.OUT,initial=GPIO.HIGH)
            for g in ALL_CATHODE:
                for p in g: GPIO.setup(p,GPIO.OUT,initial=GPIO.LOW)
            self.gpio=GPIO; print("[HW] GPIO ready — 6 groups")
        except Exception as e: print(f"[HW] No GPIO ({e})")
        try:
            from RPLCD.i2c import CharLCD
            self.lcd=CharLCD("PCF8574",0x27,port=1,cols=16,rows=2); self.lcd.clear()
            print("[HW] LCD at 0x27")
        except Exception as e: print(f"[HW] No LCD ({e})")

    def _rgb(self,s):
        if not self.gpio: return
        G=self.gpio
        if s=='g':   G.output(RGB_R,1);G.output(RGB_G,0);G.output(RGB_B,1)
        elif s=='a': G.output(RGB_R,0);G.output(RGB_G,0);G.output(RGB_B,1)
        elif s=='r': G.output(RGB_R,0);G.output(RGB_G,1);G.output(RGB_B,1)
        else:        G.output(RGB_R,1);G.output(RGB_G,1);G.output(RGB_B,1)

    def _cat(self,pins,s):
        if not self.gpio: return
        r,g,a=pins
        self.gpio.output(r,1 if s=='r' else 0)
        self.gpio.output(g,1 if s=='g' else 0)
        self.gpio.output(a,1 if s=='a' else 0)

    def apply_phase(self,tls):
        if not self.gpio: return
        rgb,d2,d1,b1,b2,c1=PHASE_SIGNALS[tls]
        self._rgb(rgb); self._cat(D2_PINS,d2); self._cat(D1_PINS,d1)
        self._cat(B1_PINS,b1); self._cat(B2_PINS,b2); self._cat(C1_PINS,c1)

    def all_red(self):
        if not self.gpio: return
        self._rgb('r')
        for g in ALL_CATHODE: self._cat(g,'r')

    def show_lcd(self,l1,l2=""):
        if self.lcd:
            try: self.lcd.clear();self.lcd.write_string(l1[:16]);
            except: pass
            if l2:
                try: self.lcd.crlf();self.lcd.write_string(l2[:16])
                except: pass
        print(f"  LCD| {l1:<16s} | {l2:<16s}")

    def blink_boot(self):
        if not self.gpio: return
        for _ in range(3):
            self.gpio.output(LED_MONO,1);time.sleep(0.4)
            self.gpio.output(LED_MONO,0);time.sleep(0.4)

    def cleanup(self):
        if self.gpio: self.all_red();self.gpio.output(LED_MONO,0);self.gpio.cleanup()
        if self.lcd:
            try: self.lcd.clear();self.lcd.write_string("Demo stopped")
            except: pass

# ═══════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════
def run(mode, speed, no_hw):
    hw=HardwareIO(skip=no_hw); sim=QueueSim()
    hw.blink_boot(); hw.show_lcd("J1 Gaborone",f"Mode: {mode[:10]}")
    time.sleep(2.0/speed)
    dqn=None
    if mode=="hybrid_drl":
        wp=HERE/"j1_dqn_weights.npz"
        if wp.exists():
            try: dqn=DQNInference(str(wp))
            except Exception as e: print(f"[WARN] DQN failed ({e})")
        if not dqn: print("[INFO] Using equity-weighted heuristic for DRL")
    sim_t=0;ci=0;pi=0;tot_q=0;ns=0;sw=0
    print(f"\n{'='*60}\n  J1 SIGNAL — {mode.upper()} (equity forcing ON)\n{'='*60}\n")
    try:
        while sim_t<86400:
            if mode=="fixed": ph=pick_fixed(ci)
            elif mode=="mp": ph=pick_mp(sim)
            else: ph=pick_drl(sim,dqn,pi,sim_t)
            ni=PHASE_GREEN.index(ph)
            if ni!=pi:
                sw+=1
                hw.apply_phase(PHASE_GREEN[pi]+1)
                h=sim_t//3600;m=(sim_t%3600)//60
                hw.show_lcd(f"{h:02d}:{m:02d} YELLOW",PHASE_LABEL[PHASE_GREEN[pi]])
                time.sleep(YELLOW_S/speed)
                hw.all_red();time.sleep(1.0/speed)
            pi=ni; hw.apply_phase(ph)
            h=sim_t//3600;m=(sim_t%3600)//60
            q=sim.total_queue();tot_q+=q;ns+=1
            hw.show_lcd(f"{h:02d}:{m:02d} {PHASE_LABEL[ph]}",f"Q:{q:4.0f} {mode[:3]:>3s}")
            dem=get_demand(sim_t)
            print(f"  {h:02d}:{m:02d}  {PHASE_LABEL[ph]}  "
                  f"Q=[A:{sim.queues['A']:5.1f} B:{sim.queues['B']:5.1f} "
                  f"C:{sim.queues['C']:5.1f} D:{sim.queues['D']:5.1f}]  "
                  f"tot={q:5.1f}  w=[{sim.wait['A']:.0f},{sim.wait['B']:.0f},{sim.wait['C']:.0f},{sim.wait['D']:.0f}]")
            sim.step(ph,sim_t)
            time.sleep(GREEN_S/speed);sim_t+=GREEN_S;ci+=1
    except KeyboardInterrupt: print("\n[STOP]")
    avg=tot_q/max(ns,1)
    print(f"\n{'='*60}\n  {mode.upper()} | Steps:{ns} Sw:{sw} AvgQ:{avg:.1f}\n{'='*60}")
    hw.show_lcd(f"Done {mode[:6]}",f"AvgQ:{avg:.1f}")
    time.sleep(3);hw.cleanup()

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--mode",default="hybrid_drl",choices=["fixed","mp","hybrid_drl"])
    p.add_argument("--speed",type=float,default=10)
    p.add_argument("--no-hardware",action="store_true")
    a=p.parse_args(); run(a.mode,a.speed,a.no_hardware)