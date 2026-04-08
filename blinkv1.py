import RPi.GPIO as GPIO
import time
import sys
import tty
import termios
from RPLCD.i2c import CharLCD

LED_PIN  = 17
RGB_R    = 27
RGB_G    = 22
RGB_B    = 23
I2C_ADDR = 0x27

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(RGB_R,   GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_G,   GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_B,   GPIO.OUT, initial=GPIO.HIGH)

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

def rgb(r, g, b):
    GPIO.output(RGB_R, GPIO.LOW  if r else GPIO.HIGH)
    GPIO.output(RGB_G, GPIO.LOW  if g else GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.LOW  if b else GPIO.HIGH)

def rgb_off():   rgb(0, 0, 0)
def rgb_red():   rgb(1, 0, 0)
def rgb_green(): rgb(0, 1, 0)
def rgb_amber(): rgb(1, 1, 0)

def blink(times=3):
    for i in range(times):
        GPIO.output(LED_PIN, GPIO.HIGH)
        time.sleep(0.5)
        GPIO.output(LED_PIN, GPIO.LOW)
        time.sleep(0.5)

def show_lcd(line1, line2=""):
    lcd.clear()
    time.sleep(0.1)
    lcd.cursor_pos = (0, 0)
    lcd.write_string(line1[:16])
    if line2:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])

STATES = [
    ("Red",   "Signal: RED",   rgb_red),
    ("Amber", "Signal: AMBER", rgb_amber),
    ("Green", "Signal: GREEN", rgb_green),
]

print("Boot sequence...")
blink()
show_lcd("Hello World!", "J1 Gaborone")
time.sleep(2)

idx = 0
name, lcd2, fn = STATES[idx]
fn()
show_lcd("Signal: " + name, "key=next  q=quit")
print("Current: " + name)
print("Any key = next   q = quit")

try:
    while True:
        key = get_key()
        if key == 'q' or key == '\x03':
            print("Exiting...")
            break
        idx = (idx + 1) % len(STATES)
        name, lcd2, fn = STATES[idx]
        fn()
        show_lcd("Signal: " + name, "key=next  q=quit")
        print("Toggled to: " + name)
except Exception as e:
    print("Error: " + str(e))
finally:
    rgb_off()
    GPIO.output(LED_PIN, GPIO.LOW)
    lcd.clear()
    GPIO.cleanup()
    print("Cleaned up.")