# Test links 5,6 — Arm D→out4 (common cathode) GPIO 5,6,13
import RPi.GPIO as GPIO
import time

RED   = 5
GREEN = 6
AMBER = 13

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for p in [RED, GREEN, AMBER]:
    GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)

try:
    print("Links 5,6 — Arm D out4 test")
    print("RED...")
    GPIO.output(RED, GPIO.HIGH); GPIO.output(GREEN, GPIO.LOW); GPIO.output(AMBER, GPIO.LOW)
    time.sleep(2)
    print("GREEN...")
    GPIO.output(RED, GPIO.LOW); GPIO.output(GREEN, GPIO.HIGH); GPIO.output(AMBER, GPIO.LOW)
    time.sleep(2)
    print("AMBER...")
    GPIO.output(RED, GPIO.LOW); GPIO.output(GREEN, GPIO.LOW); GPIO.output(AMBER, GPIO.HIGH)
    time.sleep(2)
    print("OFF")
    for p in [RED, GREEN, AMBER]: GPIO.output(p, GPIO.LOW)
finally:
    GPIO.cleanup()
    print("Done.")
