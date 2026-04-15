# Test links 3,4 — Arm D→out2 (common cathode) GPIO 19,26,21
import RPi.GPIO as GPIO
import time

RED   = 19
GREEN = 26
AMBER = 21

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for p in [RED, GREEN, AMBER]:
    GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)

try:
    print("Links 3,4 — Arm D out2 test")
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
