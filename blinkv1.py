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
GPIO.setup(RGB_G,   GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_B,   GPIO.OUT, initial=GPIO.HIGH)

# Use PWM on red for amber mixing control
GPIO.setup(RGB_R, GPIO.OUT, initial=GPIO.HIGH)
pwm_r = GPIO.PWM(RGB_R, 1000)
pwm_r.start(0)

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

# Common anode: LOW=ON for G and B
# Red uses PWM: duty 0=OFF, 100=full ON
# Amber: red at ~30% duty + green fully ON
def rgb_off():
    pwm_r.ChangeDutyCycle(0)
    GPIO.output(RGB_G, GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.HIGH)

def rgb_red():
    pwm_r.ChangeDutyCycle(100)
    GPIO.output(RGB_G, GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.HIGH)

def rgb_green():
    pwm_r.ChangeDutyCycle(0)
    GPIO.output(RGB_G, GPIO.LOW)
    GPIO.output(RGB_B, GPIO.HIGH)

def rgb_amber():
    pwm_r.ChangeDutyCycle(30)
    GPIO.output(RGB_G, GPIO.LOW)
    GPIO.output(RGB_B, GPIO.HIGH)

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

def set_state(name, fn):
    fn()
    show_lcd("Signal: " + name, "R G A  any=next")
    print("State: " + name)

STATES = ["Red", "Amber", "Green"]
idx = 0

print("Boot sequence...")
blink()
show_lcd("Hello World!", "J1 Gaborone")
time.sleep(2)

rgb_red()
show_lcd("Signal: Red", "R G A  any=next")
print("Current: Red")
print("R=red  G=green  A=amber  any=next  q=quit")

try:
    while True:
        key = get_key()
        if key == 'q' or key == '\x03':
            print("Exiting...")
            break
        elif key == 'r' or key == 'R':
            idx = 0
            set_state("Red", rgb_red)
        elif key == 'g' or key == 'G':
            idx = 2
            set_state("Green", rgb_green)
        elif key == 'a' or key == 'A':
            idx = 1
            set_state("Amber", rgb_amber)
        else:
            idx = (idx + 1) % len(STATES)
            name = STATES[idx]
            fn = rgb_red if name == "Red" else rgb_green if name == "Green" else rgb_amber
            set_state(name, fn)

except Exception as e:
    print("Error: " + str(e))
finally:
    rgb_off()
    pwm_r.stop()
    GPIO.output(LED_PIN, GPIO.LOW)
    lcd.clear()
    GPIO.cleanup()
    print("Cleaned up.")