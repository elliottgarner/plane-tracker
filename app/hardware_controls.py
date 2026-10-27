"""Abstracted physical-control handler.

Config `hardware_mode`:
  encoder - KY-040 style rotary encoder + push button (CLK/DT/SW)
  toggle  - 3-position switch (Mode1/Mode2/Mode3, each wired to GND when selected)
  touch   - no GPIO controls; the on-screen buttons / touch are used

Whatever the hardware, everything funnels into `dispatch(action, **kwargs)` with a small, fixed
vocabulary so the rest of the app never knows which hardware is attached:

  zoom_in | zoom_out | next | prev | toggle_lock | toggle_view | set_view(view=tracker|stats)
  set_filter(filter=all|interesting) | position(n=1..3)
"""
import logging
import threading
import time

from .config import cfg

log = logging.getLogger("controls")


class HardwareControls:
    def __init__(self, dispatch, on_activity=None):
        self.dispatch = dispatch
        self.on_activity = on_activity or (lambda why: None)
        self._devices = []
        self._stop = threading.Event()
        self._thread = None
        self.active_mode = "touch"
        self.error = ""

    # ---- lifecycle -------------------------------------------------------------
    def start(self):
        self.stop()
        mode = cfg["hardware_mode"]
        self.error = ""
        self.active_mode = "touch"
        if mode == "touch":
            return
        try:
            if mode == "encoder":
                self._start_encoder()
            elif mode == "toggle":
                self._start_toggle()
            self.active_mode = mode
            log.info("Hardware controls: %s", mode)
        except Exception as e:
            self.error = f"{e.__class__.__name__}: {e}"
            log.warning("Hardware controls '%s' unavailable (%s) - touch only", mode, e)
            self.stop()

    def stop(self):
        self._stop.set()
        for d in self._devices:
            try:
                d.close()
            except Exception:
                pass
        self._devices = []
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    reload = start

    def _fire(self, action, **kw):
        self.on_activity(action)
        try:
            self.dispatch(action, **kw)
        except Exception:
            log.exception("dispatch(%s) failed", action)

    # ---- Option A: rotary encoder -------------------------------------------------
    def _start_encoder(self):
        from gpiozero import Button, RotaryEncoder
        pins = cfg["encoder_pins"]
        divider = max(1, cfg["encoder_step_divider"])
        mode = cfg["encoder_rotate_action"]
        # zoom:   turn = zoom,         click = lock/unlock
        # cycle:  turn = change plane, click = lock/unlock
        # hybrid: turn = zoom,         click = next plane
        rotate_cw, rotate_ccw = (("next", "prev") if mode == "cycle" else ("zoom_in", "zoom_out"))
        click_action = "next" if mode == "hybrid" else "toggle_lock"
        state = {"acc": 0, "last": 0.0}

        def step(direction):
            now = time.monotonic()
            if now - state["last"] > 0.5:       # new gesture: drop stale partial steps
                state["acc"] = 0
            state["last"] = now
            state["acc"] += direction
            if abs(state["acc"]) >= divider:
                state["acc"] = 0
                self._fire(rotate_cw if direction > 0 else rotate_ccw)

        enc = RotaryEncoder(pins["clk"], pins["dt"], max_steps=0, wrap=False)
        enc.when_rotated_clockwise = lambda: step(+1)
        enc.when_rotated_counter_clockwise = lambda: step(-1)

        btn = Button(pins["sw"], pull_up=True, bounce_time=0.05, hold_time=cfg["long_press_seconds"])
        held = {"v": False}

        def on_held():
            held["v"] = True
            self._fire("toggle_view")

        def on_release():
            if not held["v"]:
                self._fire(click_action)
            held["v"] = False

        btn.when_held = on_held
        btn.when_released = on_release
        self._devices += [enc, btn]

    # ---- Option B: 3-position selector ------------------------------------------------
    def _start_toggle(self):
        from gpiozero import DigitalInputDevice
        pins = cfg["toggle_pins"]
        inputs = [DigitalInputDevice(pins[k], pull_up=True) for k in ("mode1", "mode2", "mode3")]
        self._devices += inputs
        self._stop = threading.Event()
        stop = self._stop

        def read_position():
            # pull_up=True: a closed contact reads 0 => device.value == 0 ... gpiozero reports
            # `is_active` as True when pulled to ground for pull_up inputs.
            for i, d in enumerate(inputs, 1):
                if d.is_active:
                    return i
            return 2  # centre-off toggles connect only the outer two poles

        def poll():
            last, candidate, since = None, None, 0.0
            while not stop.wait(0.05):
                pos = read_position()
                if pos != candidate:
                    candidate, since = pos, time.monotonic()
                elif pos != last and time.monotonic() - since > 0.12:   # debounce
                    last = pos
                    self._fire("position", n=pos)

        self._thread = threading.Thread(target=poll, name="toggle-poll", daemon=True)
        self._thread.start()
