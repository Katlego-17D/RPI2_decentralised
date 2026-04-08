
import RPi.GPIO as GPIO
import time
import sys
import tty
import termios
from RPLCD.i2c import CharLCD

LED_PIN  = 17
I2C_ADDR = 0x27

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)

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

print("Boot sequence...")
blink()
show_lcd("Hello World!", "J1 Gaborone")
print("Ready. r=run again  q=quit")

try:
    while True:
        key = get_key()
        if key == 'r':
            print("Reloading...")
            blink()
            show_lcd("Hello World!", "J1 Gaborone")
            print("r=run again  q=quit")
        elif key == 'q' or key == '\x03':
            print("Exiting...")
            break
except Exception as e:
    print("Error: " + str(e))
finally:
    lcd.clear()
    GPIO.cleanup()
    print("Cleaned up.")
EOF