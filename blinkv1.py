import RPi.GPIO as GPIO
import time
import sys
import tty
import termios
from RPLCD.i2c import CharLCD

LED_MONO = 17
RGB_R    = 27
RGB_G    = 22
RGB_B    = 23
D_RED    = 5
D_GREEN  = 6
D_AMBER  = 13
I2C_ADDR = 0x27

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(LED_MONO, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(RGB_R,    GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_G,    GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_B,    GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(D_RED,    GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(D_GREEN,  GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(D_AMBER,  GPIO.OUT, initial=GPIO.LOW)

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

# ── RGB common anode: LOW=ON, HIGH=OFF ───────────────────────────────────────
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

def rgb_off():
    GPIO.output(RGB_R, GPIO.HIGH)
    GPIO.output(RGB_G, GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.HIGH)

# ── Arm D common cathode: HIGH=ON, LOW=OFF ────────────────────────────────────
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

def d_off():
    GPIO.output(D_RED,   GPIO.LOW)
    GPIO.output(D_GREEN, GPIO.LOW)
    GPIO.output(D_AMBER, GPIO.LOW)

# ── TLS phases ────────────────────────────────────────────────────────────────
# Ph0: rrrGGrrrrrrr  links 3,4 green   → ArmA red,   ArmD red
# Ph1: rrryyrrrrrrr  links 3,4 yellow  → ArmA red,   ArmD red
# Ph2: rGGrrrrGGrrr  links 1,2,7,8 grn → ArmA GREEN, ArmD red
# Ph3: ryyrrrryyrrr  links 1,2,7,8 yel → ArmA AMBER, ArmD red
# Ph4: GrrrrrrrrrrG  links 0,11 green  → ArmA red,   ArmD red
# Ph5: yrrrrrrrrrry  links 0,11 yellow → ArmA red,   ArmD red
# Ph6: rrrrrGGrrGGr  links 5,6,9,10   → ArmA red,   ArmD GREEN
# Ph7: rrrrryyrryyr  links 5,6,9,10 y → ArmA red,   ArmD AMBER
PHASES = [
    ("Ph0 D    36s", "ArmA:RED  ArmD:RED", rgb_red,   d_red),
    ("Ph1 Yel   4s", "ArmA:RED  ArmD:RED", rgb_red,   d_red),
    ("Ph2 AB   25s", "ArmA:GRN  ArmD:RED", rgb_green, d_red),
    ("Ph3 Yel   4s", "ArmA:AMB  ArmD:RED", rgb_amber, d_red),
    ("Ph4 BC   20s", "ArmA:RED  ArmD:RED", rgb_red,   d_red),
    ("Ph5 Yel   4s", "ArmA:RED  ArmD:RED", rgb_red,   d_red),
    ("Ph6 CD   36s", "ArmA:RED  ArmD:GRN", rgb_red,   d_green),
    ("Ph7 Yel   4s", "ArmA:RED  ArmD:AMB", rgb_red,   d_amber),
]

def apply_phase(idx):
    name, lcd2, rgb_fn, d_fn = PHASES[idx]
    rgb_fn()
    d_fn()
    show_lcd(name, lcd2)
    print("Phase " + str(idx) + ": " + name)

# ── Boot ──────────────────────────────────────────────────────────────────────
print("=== Boot ===")
blink_boot()
show_lcd("Hello World!", "J1 Gaborone")
time.sleep(2)

idx = 0
apply_phase(idx)
print("any key=next  q=quit")

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