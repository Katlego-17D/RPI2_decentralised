"""
blink.py  —  Full TLS hardware test for J1 Gaborone
=====================================================
Cycles through all 8 TLS phases (0-7).
LCD shows: phase number + 12-char TLS state string
LEDs show: correct R/G/A for each signal group

TLS state string (12 links, index 0-11):
  r = red, G = green, y = amber/yellow

Phase map:
  Ph0 (36s): rrrGGrrrrrrr  links 3,4   green  (Arm D→out2)
  Ph1  (4s): rrryyrrrrrrr  links 3,4   amber
  Ph2 (25s): rGGrrrrGGrrr  links 1,2,7,8 green (Arm A+B)
  Ph3  (4s): ryyrrrryyrrr  links 1,2,7,8 amber
  Ph4 (20s): GrrrrrrrrrrG  links 0,11  green  (Arm B+C)
  Ph5  (4s): yrrrrrrrrrry  links 0,11  amber
  Ph6 (36s): rrrrrGGrrGGr  links 5,6,9,10 green (Arm C+D)
  Ph7  (4s): rrrrryyrryyr  links 5,6,9,10 amber

GPIO pin assignments:
  RGB  (common anode, links 7,8): R=27 G=22 B=23
  D2   (common cathode, links 3,4):   R=19 G=26 A=21
  D1   (common cathode, links 5,6):   R=5  G=6  A=13
  B1   (common cathode, links 1,2):   R=20 G=16 A=12
  B2   (common cathode, link 0):      R=8  G=25 A=24
  C1   (common cathode, links 9,10):  R=7  G=9  A=11
  Mono LED: GPIO 17

Controls:
  any key = next phase
  q       = quit
"""

import RPi.GPIO as GPIO
import time
import sys
import tty
import termios
from RPLCD.i2c import CharLCD

# ── Pin definitions ───────────────────────────────────────────────────────────
LED_MONO = 17

# RGB common anode — links 7,8 (Arm A, Phase 2)
RGB_R = 27
RGB_G = 22
RGB_B = 23

# Common cathode groups (RED, GREEN, AMBER)
D2_R, D2_G, D2_A = 19, 26, 21   # links 3,4  Arm D→out2  Phase 0
D1_R, D1_G, D1_A = 5,  6,  13   # links 5,6  Arm D→out4  Phase 6
B1_R, B1_G, B1_A = 20, 16, 12   # links 1,2  Arm B→out1  Phase 2
B2_R, B2_G, B2_A = 8,  25, 24   # link  0    Arm B→out4  Phase 4
C1_R, C1_G, C1_A = 7,  9,  11   # links 9,10 Arm C→out3  Phase 6

ALL_CATHODE = [
    D2_R,D2_G,D2_A,
    D1_R,D1_G,D1_A,
    B1_R,B1_G,B1_A,
    B2_R,B2_G,B2_A,
    C1_R,C1_G,C1_A,
]

I2C_ADDR = 0x27

# ── GPIO setup ────────────────────────────────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(LED_MONO, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(RGB_R,    GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_G,    GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_B,    GPIO.OUT, initial=GPIO.HIGH)
for p in ALL_CATHODE:
    GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)

# ── LCD ───────────────────────────────────────────────────────────────────────
lcd = CharLCD(
    i2c_expander='PCF8574',
    address=I2C_ADDR,
    port=1, cols=16, rows=2, dotsize=8,
    charmap='A02', auto_linebreaks=True, backlight_enabled=True,
)

# ── Signal constants ──────────────────────────────────────────────────────────
RED_S   = 0
GREEN_S = 1
AMBER_S = 2

# ── LED helpers ───────────────────────────────────────────────────────────────
def rgb_set(r, g, b):
    GPIO.output(RGB_R, GPIO.LOW  if r else GPIO.HIGH)
    GPIO.output(RGB_G, GPIO.LOW  if g else GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.LOW  if b else GPIO.HIGH)

def cat_set(r_pin, g_pin, a_pin, state):
    GPIO.output(r_pin, GPIO.HIGH if state == RED_S   else GPIO.LOW)
    GPIO.output(g_pin, GPIO.HIGH if state == GREEN_S else GPIO.LOW)
    GPIO.output(a_pin, GPIO.HIGH if state == AMBER_S else GPIO.LOW)

def all_off():
    rgb_set(0, 0, 0)
    for p in ALL_CATHODE:
        GPIO.output(p, GPIO.LOW)

# ── Phase definitions ─────────────────────────────────────────────────────────
# Each phase: (name, tls_state_12chars, rgb_state, D2, D1, B1, B2, C1)
# rgb_state: (r,g,b)  cathode_state: RED_S / GREEN_S / AMBER_S
PHASES = [
    (
        "Ph0  36s",
        "rrrGGrrrrrrr",
        (1,0,0),                        # RGB  → red
        GREEN_S, RED_S, RED_S, RED_S, RED_S,   # D2 green, rest red
    ),
    (
        "Ph1   4s",
        "rrryyrrrrrrr",
        (1,0,0),                        # RGB  → red
        AMBER_S, RED_S, RED_S, RED_S, RED_S,   # D2 amber, rest red
    ),
    (
        "Ph2  25s",
        "rGGrrrrGGrrr",
        (0,1,0),                        # RGB  → green (links 7,8)
        RED_S, RED_S, GREEN_S, RED_S, RED_S,   # B1 green, rest red
    ),
    (
        "Ph3   4s",
        "ryyrrrryyrrr",
        (1,1,0),                        # RGB  → amber (links 7,8)
        RED_S, RED_S, AMBER_S, RED_S, RED_S,   # B1 amber, rest red
    ),
    (
        "Ph4  20s",
        "GrrrrrrrrrrG",
        (1,0,0),                        # RGB  → red
        RED_S, RED_S, RED_S, GREEN_S, RED_S,   # B2 green (link 0)
    ),
    (
        "Ph5   4s",
        "yrrrrrrrrrry",
        (1,0,0),                        # RGB  → red
        RED_S, RED_S, RED_S, AMBER_S, RED_S,   # B2 amber (link 0)
    ),
    (
        "Ph6  36s",
        "rrrrrGGrrGGr",
        (1,0,0),                        # RGB  → red
        RED_S, GREEN_S, RED_S, RED_S, GREEN_S, # D1+C1 green
    ),
    (
        "Ph7   4s",
        "rrrrryyrryyr",
        (1,0,0),                        # RGB  → red
        RED_S, AMBER_S, RED_S, RED_S, AMBER_S, # D1+C1 amber
    ),
]

# ── Apply a phase to all hardware ─────────────────────────────────────────────
def apply_phase(idx):
    name, tls_str, rgb, d2, d1, b1, b2, c1 = PHASES[idx]
    rgb_set(*rgb)
    cat_set(D2_R, D2_G, D2_A, d2)
    cat_set(D1_R, D1_G, D1_A, d1)
    cat_set(B1_R, B1_G, B1_A, b1)
    cat_set(B2_R, B2_G, B2_A, b2)
    cat_set(C1_R, C1_G, C1_A, c1)
    # LCD line 1: phase name
    # LCD line 2: TLS state string (12 chars fits on 16-col display)
    lcd.clear()
    time.sleep(0.05)
    lcd.cursor_pos = (0, 0)
    lcd.write_string(name[:16])
    lcd.cursor_pos = (1, 0)
    lcd.write_string(tls_str[:16])
    print("Phase " + str(idx) + ": " + name + "  TLS: " + tls_str)

# ── Key reader ────────────────────────────────────────────────────────────────
def get_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    ch = sys.stdin.read(1)
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch

# ── Boot sequence ─────────────────────────────────────────────────────────────
print("=== Boot sequence ===")
for _ in range(3):
    GPIO.output(LED_MONO, GPIO.HIGH); time.sleep(0.4)
    GPIO.output(LED_MONO, GPIO.LOW);  time.sleep(0.4)

lcd.clear()
time.sleep(0.1)
lcd.cursor_pos = (0, 0)
lcd.write_string("Hello World!")
lcd.cursor_pos = (1, 0)
lcd.write_string("J1 Gaborone")
print("Boot complete.")
time.sleep(2)

# ── Start at Phase 0 ──────────────────────────────────────────────────────────
idx = 0
apply_phase(idx)
print("any key = next phase   q = quit")

# ── Main loop ─────────────────────────────────────────────────────────────────
try:
    while True:
        key = get_key()
        if key == 'q' or key == '\x03':
            print("Exiting...")
            break
        idx = (idx + 1) % len(PHASES)
        apply_phase(idx)

except Exception as e:
    print("Error: " + str(e))

finally:
    all_off()
    GPIO.output(LED_MONO, GPIO.LOW)
    lcd.clear()
    GPIO.cleanup()
    print("Cleaned up.")