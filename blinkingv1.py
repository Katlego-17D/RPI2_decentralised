import RPi.GPIO as GPIO
import time
import sys
import tty
import termios
from RPLCD.i2c import CharLCD

LED_PIN = 17
RGB_R   = 27
RGB_G   = 22
RGB_B   = 23

I2C_ADDR = 0x27

# Common anode — long leg to 3.3V
# LOW = ON, HIGH = OFF
ON  = GPIO.LOW
OFF = GPIO.HIGH

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(RGB_R,   GPIO.OUT, initial=OFF)
GPIO.setup(RGB_G,   GPIO.OUT, initial=OFF)
GPIO.setup(RGB_B,   GPIO.OUT, initial=OFF)

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

def rgb_set(r, g, b):
    GPIO.output(RGB_R, ON if r else OFF)
    GPIO.output(RGB_G, ON if g else OFF)
    GPIO.output(RGB_B, ON if b else OFF)

def rgb_off():    rgb_set(0, 0, 0)
def rgb_red():    rgb_set(1, 0, 0)
def rgb_green():  rgb_set(0, 1, 0)
def rgb_blue():   rgb_set(0, 0, 1)
def rgb_amber():  rgb_set(1, 1, 0)
def rgb_white():  rgb_set(1, 1, 1)
def rgb_purple(): rgb_set(1, 0, 1)

def get_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    ch = sys.stdin.read(1)
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch

def blink(times=3):
    print("Blinking LED " + str(times) + " times...")
    for i in range(times):
        GPIO.output(LED_PIN, GPIO.HIGH)
        time.sleep(0.5)
        GPIO.output(LED_PIN, GPIO.LOW)
        time.sleep(0.5)
    print("Blink done.")

def show_lcd(line1, line2=""):
    lcd.clear()
    time.sleep(0.1)
    lcd.cursor_pos = (0, 0)
    lcd.write_string(line1[:16])
    if line2:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16])

COLOURS = [
    ("Red",    rgb_red),
    ("Green",  rgb_green),
    ("Blue",   rgb_blue),
    ("Amber",  rgb_amber),
    ("White",  rgb_white),
    ("Purple", rgb_purple),
]

print("=== Boot sequence ===")
blink()
show_lcd("Hello World!", "J1 Gaborone")
print("LCD ready.")
time.sleep(2)

print("")
print("=== Toggling state ===")
print("Any key = next colour   q = quit")
print("")

idx = 0
name, fn = COLOURS[idx]
fn()
show_lcd("Colour: " + name, "key=next  q=quit")
print("Current: " + name)

try:
    while True:
        key = get_key()
        if key == 'q' or key == '\x03':
            print("Exiting...")
            break
        idx = (idx + 1) % len(COLOURS)
        name, fn = COLOURS[idx]
        fn()
        show_lcd("Colour: " + name, "key=next  q=quit")
        print("Toggled to: " + name)

except Exception as e:
    print("Error: " + str(e))

finally:
    rgb_off()
    GPIO.output(LED_PIN, GPIO.LOW)
    lcd.clear()
    GPIO.cleanup()
    print("Cleaned up.")