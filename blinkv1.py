import RPi.GPIO as GPIO
import time
import sys
import tty
import termios
from RPLCD.i2c import CharLCD

# ── Pin definitions ───────────────────────────────────────────────────────────
LED_MONO = 17

# RGB LED — common anode (links 7,8 — Arm A, Phase 2)
RGB_R = 27
RGB_G = 22
RGB_B = 23

# R/G + standalone amber — common cathode (links 5,6 — Arm D, Phase 6)
D_RED   = 5
D_GREEN = 6
D_AMBER = 13

I2C_ADDR = 0x27

# ── GPIO setup ────────────────────────────────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(LED_MONO, GPIO.OUT, initial=GPIO.LOW)

# RGB common anode — HIGH=OFF, LOW=ON
GPIO.setup(RGB_R, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_G, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_B, GPIO.OUT, initial=GPIO.HIGH)

# Arm D common cathode — HIGH=ON, LOW=OFF
GPIO.setup(D_RED,   GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(D_GREEN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(D_AMBER, GPIO.OUT, initial=GPIO.LOW)

# ── LCD ───────────────────────────────────────────────────────────────────────
lcd = CharLCD(
    i2c_expander='PCF8574',
    address=I2C_ADDR,
    port=1,
    cols=16,
    rows=2,
    dotsize=8,
    charmap='A02',
    auto_linebreaks=True,
    backlight_enabled=True,
)

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    ch = sys.stdin.read(1)
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch

def show_lcd(line1, line2=""):
    lcd.clear()
    time.sleep(0.1)
    lcd.cursor_pos = (0, 0)
    lcd.write_string(line1[:16])
    if line2:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])

def blink_boot(times=3):
    for i in range(times):
        GPIO.output(LED_MONO, GPIO.HIGH)
        time.sleep(0.5)
        GPIO.output(LED_MONO, GPIO.LOW)
        time.sleep(0.5)

# ── RGB (common anode) signal functions ──────────────────────────────────────
def rgb_off():
    GPIO.output(RGB_R, GPIO.HIGH)
    GPIO.output(RGB_G, GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.HIGH)

def rgb_red():
    GPIO.output(RGB_R, GPIO.LOW)
    GPIO.output(RGB_G, GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.HIGH)

def rgb_green():
    GPIO.output(RGB_R, GPIO.HIGH)
    GPIO.output(RGB_G, GPIO.LOW)
    GPIO.output(RGB_B, GPIO.HIGH)

def rgb_amber():
    GPIO.output(RGB_R, GPIO.LOW)
    GPIO.output(RGB_G, GPIO.LOW)
    GPIO.output(RGB_B, GPIO.HIGH)

# ── Arm D (common cathode) signal functions ───────────────────────────────────
def d_off():
    GPIO.output(D_RED,   GPIO.LOW)
    GPIO.output(D_GREEN, GPIO.LOW)
    GPIO.output(D_AMBER, GPIO.LOW)

def d_red():
    GPIO.output(D_RED,   GPIO.HIGH)
    GPIO.output(D_GREEN, GPIO.LOW)
    GPIO.output(D_AMBER, GPIO.LOW)

def d_green():
    GPIO.output(D_RED,   GPIO.LOW)
    GPIO.output(D_GREEN, GPIO.HIGH)
    GPIO.output(D_AMBER, GPIO.LOW)

def d_amber():
    GPIO.output(D_RED,   GPIO.LOW)
    GPIO.output(D_GREEN, GPIO.LOW)
    GPIO.output(D_AMBER, GPIO.HIGH)

# ── Phase states ──────────────────────────────────────────────────────────────
# Each entry: (phase_name, lcd_line2, rgb_fn, d_fn)
# Based on actual TLS phases:
#   Phase 0 (36s): D green      → Arm A red,   Arm D red
#   Phase 1  (4s): yellow       → Arm A red,   Arm D red
#   Phase 2 (25s): A+B green    → Arm A GREEN, Arm D red
#   Phase 3  (4s): yellow       → Arm A AMBER, Arm D red
#   Phase 4 (20s): B+C green    → Arm A red,   Arm D red
#   Phase 5  (4s): yellow       → Arm A red,   Arm D red
#   Phase 6 (36s): C+D green    → Arm A red,   Arm D GREEN
#   Phase 7  (4s): yellow       → Arm A red,   Arm D AMBER

PHASES = [
    ("Ph0 D grn  36s", "ArmA:RED  ArmD:RED",   rgb_red,   d_red),
    ("Ph1 Yellow  4s", "ArmA:RED  ArmD:RED",   rgb_red,   d_red),
    ("Ph2 AB grn 25s", "ArmA:GRN  ArmD:RED",   rgb_green, d_red),
    ("Ph3 Yellow  4s", "ArmA:AMB  ArmD:RED",   rgb_amber, d_red),
    ("Ph4 BC grn 20s", "ArmA:RED  ArmD:RED",   rgb_red,   d_red),
    ("Ph5 Yellow  4s", "ArmA:RED  ArmD:RED",   rgb_red,   d_red),
    ("Ph6 CD grn 36s", "ArmA:RED  ArmD:GRN",   rgb_red,   d_green),
    ("Ph7 Yellow  4s", "ArmA:RED  ArmD:AMB",   rgb_red,   d_amber),
]

def apply_phase(idx):
    name, lcd2, rgb_fn, d_fn = PHASES[idx]
    rgb_fn()
    d_fn()
    show_lcd(name, lcd2)
    print("Phase " + str(idx) + ": " + name)

# ── Boot sequence ─────────────────────────────────────────────────────────────
print("=== Boot sequence ===")
blink_boot()
show_lcd("Hello World!", "J1 Gaborone")
time.sleep(2)

# Start at Phase 0
idx = 0
apply_phase(idx)
print("")
print("any key = next phase")
print("q       = quit")

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
    rgb_off()
    d_off()
    GPIO.output(LED_MONO, GPIO.LOW)
    lcd.clear()
    GPIO.cleanup()
    print("Cleaned up.")