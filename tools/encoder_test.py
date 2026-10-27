#!/usr/bin/env python3
"""Live rotary-encoder diagnostic. Stop the service first:  sudo systemctl stop plane-tracker

  python tools/encoder_test.py          # raw pin transitions (wiring check)
  python tools/encoder_test.py --steps  # what gpiozero's RotaryEncoder reports
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.config import cfg  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--steps", action="store_true")
args = ap.parse_args()
pins = cfg["encoder_pins"]
print(f"CLK=GPIO{pins['clk']}  DT=GPIO{pins['dt']}  SW=GPIO{pins['sw']}   (Ctrl+C to stop)")

if args.steps:
    from gpiozero import RotaryEncoder
    enc = RotaryEncoder(pins["clk"], pins["dt"], max_steps=0, wrap=False)
    count = {"cw": 0, "ccw": 0}

    def cw():
        count["cw"] += 1
        print("clockwise", count)

    def ccw():
        count["ccw"] += 1
        print("counter-clockwise", count)
    enc.when_rotated_clockwise, enc.when_rotated_counter_clockwise = cw, ccw
else:
    from gpiozero import DigitalInputDevice
    devs = {}
    changes = {"CLK": 0, "DT": 0, "SW": 0}
    for name, key in (("CLK", "clk"), ("DT", "dt"), ("SW", "sw")):
        d = DigitalInputDevice(pins[key], pull_up=True)
        devs[name] = d

        def make(n, dev):
            def cb():
                changes[n] += 1
                # pull_up input: is_active == pin pulled to GND
                print(f"{time.strftime('%H:%M:%S')}  {n} = {0 if dev.is_active else 1}")
            return cb
        d.when_activated = d.when_deactivated = make(name, d)
    print("Initial levels:", {n: (0 if d.is_active else 1) for n, d in devs.items()})
    print("Turn the knob slowly; CLK and DT should both change. Press the knob to test SW.")

try:
    while True:
        time.sleep(0.5)
except KeyboardInterrupt:
    if not args.steps:
        print("\nTransitions seen:", changes)
        for n, c in changes.items():
            if c == 0 and n != "SW":
                print(f"  ! {n} never changed - check that wire / pin")
