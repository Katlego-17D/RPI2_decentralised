# Test links 7,8 — RGB LED (common anode) GPIO 27,22,23
import RPi.GPIO as GPIO
import time

RGB_R = 27
RGB_G = 22
RGB_B = 23

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(RGB_R, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_G, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(RGB_B, GPIO.OUT, initial=GPIO.HIGH)

def rgb(r, g, b):
    GPIO.output(RGB_R, GPIO.LOW if r else GPIO.HIGH)
    GPIO.output(RGB_G, GPIO.LOW if g else GPIO.HIGH)
    GPIO.output(RGB_B, GPIO.LOW if b else GPIO.HIGH)

try:
    print("Links 7,8 — RGB LED test")
    print("RED...")
    rgb(1,0,0)
    time.sleep(2)
    print("GREEN...")
    rgb(0,1,0)
    time.sleep(2)
    print("AMBER...")
    rgb(1,1,0)
    time.sleep(2)
    print("OFF")
    rgb(0,0,0)
finally:
    GPIO.cleanup()
    print("Done.")
