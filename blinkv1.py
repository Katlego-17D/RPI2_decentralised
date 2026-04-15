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

# Links 5,6 — Arm D→out4, Phase 6
D1_RED   = 5
D1_GREEN = 6
D1_AMBER = 13

# Links 3,4 — Arm D→out2, Phase 0
D2_RED   = 19
D2_GREEN = 26
D2_AMBER = 21

# Links 1,2 — Arm B→out1, Phase 2
B1_RED   = 20
B1_GREEN = 16
B1_AMBER = 12

# Link 0 — Arm B→out4, Phase 4
B2_RED   = 24
B2_GREEN = 25
B2_AMBER = 8

# Links 9,10 — Arm C→out3, Phase 6
C1_RED   = 7
C1_GREEN = 11
C1_AMBER = 9

I2C_ADDR = 0x27

# ── GPIO setup ────────────────────────────────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(LED_MONO, GPIO.OUT, initial=GPIO.LOW)

# RGB common anode — HIGH=OFF, LOW=ON
GPIO.setup(RGB_R, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_G, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_B, GPIO.OUT, initial=GPIO.HIGH)

# All cathode LEDs — HIGH=ON, LOW=OFF
CATHODE_PINS = [
    D1_RED, D1_GREEN, D1_AMBER,
    D2_RED, D2_GREEN, D2_AMBER,
    B1_RED, B1_GREEN, B1_AMBER,
    B2_RED, B2_GREEN, B2_AMBER,
    C1_RED, C1_GREEN, C1_AMBER,
]
for pin in CATHODE_PINS:
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

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

def all_off():
    GPIO.output(RGB_R, GPIO.HIGH)
    GPIO.output(RGB_G, GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.HIGH)
    for pin in CATHODE_PINS:
        GPIO.output(pin, GPIO.LOW)

# ── Signal group functions ────────────────────────────────────────────────────
# RGB common anode: LOW=ON
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

# Cathode group helper: pass pin trio + state (0=red, 1=green, 2=amber)
def cat_set(r_pin, g_pin, a_pin, state):
    GPIO.output(r_pin, GPIO.HIGH if state == 0 else GPIO.LOW)
    GPIO.output(g_pin, GPIO.HIGH if state == 1 else GPIO.LOW)
    GPIO.output(a_pin, GPIO.HIGH if state == 2 else GPIO.LOW)

RED   = 0
GREEN = 1
AMBER = 2

# ── Apply a full phase to all signal groups ───────────────────────────────────
# TLS state: rrrGGrrrrrrr (12 chars, index 0-11)
# Ph0: rrrGGrrrrrrr  → links 3,4 green
# Ph1: rrryyrrrrrrr  → links 3,4 amber
# Ph2: rGGrrrrGGrrr  → links 1,2,7,8 green
# Ph3: ryyrrrryyrrr  → links 1,2,7,8 amber
# Ph4: GrrrrrrrrrrG  → links 0,11 green (11 not wired yet)
# Ph5: yrrrrrrrrrry  → links 0,11 amber (11 not wired yet)
# Ph6: rrrrrGGrrGGr  → links 5,6,9,10 green
# Ph7: rrrrryyrryyr  → links 5,6,9,10 amber

def apply_phase(ph):
    if ph == 0:
        rgb_red()
        cat_set(D2_RED, D2_GREEN, D2_AMBER, GREEN)  # links 3,4
        cat_set(D1_RED, D1_GREEN, D1_AMBER, RED)    # links 5,6
        cat_set(B1_RED, B1_GREEN, B1_AMBER, RED)    # links 1,2
        cat_set(B2_RED, B2_GREEN, B2_AMBER, RED)    # link 0
        cat_set(C1_RED, C1_GREEN, C1_AMBER, RED)    # links 9,10

    elif ph == 1:
        rgb_red()
        cat_set(D2_RED, D2_GREEN, D2_AMBER, AMBER)  # links 3,4 yellow
        cat_set(D1_RED, D1_GREEN, D1_AMBER, RED)
        cat_set(B1_RED, B1_GREEN, B1_AMBER, RED)
        cat_set(B2_RED, B2_GREEN, B2_AMBER, RED)
        cat_set(C1_RED, C1_GREEN, C1_AMBER, RED)

    elif ph == 2:
        rgb_green()                                  # links 7,8 green
        cat_set(D2_RED, D2_GREEN, D2_AMBER, RED)
        cat_set(D1_RED, D1_GREEN, D1_AMBER, RED)
        cat_set(B1_RED, B1_GREEN, B1_AMBER, GREEN)  # links 1,2 green
        cat_set(B2_RED, B2_GREEN, B2_AMBER, RED)
        cat_set(C1_RED, C1_GREEN, C1_AMBER, RED)

    elif ph == 3:
        rgb_amber()                                  # links 7,8 amber
        cat_set(D2_RED, D2_GREEN, D2_AMBER, RED)
        cat_set(D1_RED, D1_GREEN, D1_AMBER, RED)
        cat_set(B1_RED, B1_GREEN, B1_AMBER, AMBER)  # links 1,2 amber
        cat_set(B2_RED, B2_GREEN, B2_AMBER, RED)
        cat_set(C1_RED, C1_GREEN, C1_AMBER, RED)

    elif ph == 4:
        rgb_red()
        cat_set(D2_RED, D2_GREEN, D2_AMBER, RED)
        cat_set(D1_RED, D1_GREEN, D1_AMBER, RED)
        cat_set(B1_RED, B1_GREEN, B1_AMBER, RED)
        cat_set(B2_RED, B2_GREEN, B2_AMBER, GREEN)  # link 0 green
        cat_set(C1_RED, C1_GREEN, C1_AMBER, RED)

    elif ph == 5:
        rgb_red()
        cat_set(D2_RED, D2_GREEN, D2_AMBER, RED)
        cat_set(D1_RED, D1_GREEN, D1_AMBER, RED)
        cat_set(B1_RED, B1_GREEN, B1_AMBER, RED)
        cat_set(B2_RED, B2_GREEN, B2_AMBER, AMBER)  # link 0 amber
        cat_set(C1_RED, C1_GREEN, C1_AMBER, RED)

    elif ph == 6:
        rgb_red()
        cat_set(D2_RED, D2_GREEN, D2_AMBER, RED)
        cat_set(D1_RED, D1_GREEN, D1_AMBER, GREEN)  # links 5,6 green
        cat_set(B1_RED, B1_GREEN, B1_AMBER, RED)
        cat_set(B2_RED, B2_GREEN, B2_AMBER, RED)
        cat_set(C1_RED, C1_GREEN, C1_AMBER, GREEN)  # links 9,10 green

    elif ph == 7:
        rgb_red()
        cat_set(D2_RED, D2_GREEN, D2_AMBER, RED)
        cat_set(D1_RED, D1_GREEN, D1_AMBER, AMBER)  # links 5,6 amber
        cat_set(B1_RED, B1_GREEN, B1_AMBER, RED)
        cat_set(B2_RED, B2_GREEN, B2_AMBER, RED)
        cat_set(C1_RED, C1_GREEN, C1_AMBER, AMBER)  # links 9,10 amber

PHASE_NAMES = [
    ("Ph0 D    36s", "3,4:GRN others:RED"),
    ("Ph1 Yel   4s", "3,4:AMB others:RED"),
    ("Ph2 AB   25s", "1,2,7,8:GRN  rest:RED"),
    ("Ph3 Yel   4s", "1,2,7,8:AMB  rest:RED"),
    ("Ph4 BC   20s", "0:GRN  others:RED"),
    ("Ph5 Yel   4s", "0:AMB  others:RED"),
    ("Ph6 CD   36s", "5,6,9,10:GRN rest:RED"),
    ("Ph7 Yel   4s", "5,6,9,10:AMB rest:RED"),
]

def run_phase(idx):
    apply_phase(idx)
    name, lcd2 = PHASE_NAMES[idx]
    show_lcd(name, lcd2)
    print("Phase " + str(idx) + ": " + name)

# ── Boot ──────────────────────────────────────────────────────────────────────
print("=== Boot ===")
blink_boot()
show_lcd("Hello World!", "J1 Gaborone")
time.sleep(2)

idx = 0
run_phase(idx)
print("any key=next  q=quit")

# ── Main loop ─────────────────────────────────────────────────────────────────
try:
    while True:
        key = get_key()
        if key == 'q' or key == '\x03':
            print("Exiting...")
            break
        idx = (idx + 1) % 8
        run_phase(idx)

except Exception as e:
    print("Error: " + str(e))

finally:
    all_off()
    GPIO.output(LED_MONO, GPIO.LOW)
    lcd.clear()
    GPIO.cleanup()
    print("Cleaned up.")