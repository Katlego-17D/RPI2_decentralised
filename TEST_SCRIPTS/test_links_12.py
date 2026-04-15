# Test links 1,2 — Arm B→out1 (common cathode) GPIO 20,16,12
import RPi.GPIO as GPIO
import time

RED   = 20
GREEN = 16
AMBER = 12

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for p in [RED, GREEN, AMBER]:
    GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)

try:
    print("Links 1,2 — Arm B out1 test")
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
