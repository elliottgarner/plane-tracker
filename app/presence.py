"""PIR presence sensor -> display sleep/wake."""
import logging
import threading
import time

from .config import cfg
from .display_power import DisplayPower

log = logging.getLogger("presence")


class PresenceManager:
    def __init__(self, display: DisplayPower):
        self.display = display
        self.last_motion = time.time()
        self._sensor = None
        self._stop = threading.Event()
        self._thread = None
        self._pin = None
        self.sensor_ok = False

    def start(self):
        self._open_sensor()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="presence", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._close_sensor()
        self.display.set(True)

    def reload(self):
        if self._pin != cfg["pir_gpio"] or (cfg["pir_enabled"] and not self._sensor):
            self._close_sensor()
            self._open_sensor()
        if not cfg["pir_enabled"]:
            self.poke("pir disabled")

    def _open_sensor(self):
        self.sensor_ok = False
        if not cfg["pir_enabled"]:
            return
        try:
            from gpiozero import MotionSensor
            self._pin = cfg["pir_gpio"]
            self._sensor = MotionSensor(self._pin, queue_len=1, sample_rate=10)
            self._sensor.when_motion = lambda: self.poke("motion")
            self.sensor_ok = True
            log.info("PIR sensor on GPIO%s", self._pin)
        except Exception as e:  # not a Pi, no permission, pin busy ...
            self._sensor = None
            log.warning("PIR sensor unavailable (%s) - display will stay on", e)

    def _close_sensor(self):
        if self._sensor:
            try:
                self._sensor.close()
            except Exception:
                pass
        self._sensor = None

    def poke(self, why=""):
        """Any sign of life (motion, knob turn, touch) resets the timer and wakes the panel."""
        self.last_motion = time.time()
        if not self.display.is_on:
            log.info("Waking display (%s)", why)
            self.display.set(True)

    def _loop(self):
        while not self._stop.wait(1.0):
            try:
                if self._sensor is not None and self._sensor.motion_detected:
                    self.poke("motion")
                timeout = cfg["pir_timeout_min"] * 60
                idle = time.time() - self.last_motion
                if (cfg["pir_enabled"] and self._sensor is not None and timeout > 0
                        and idle > timeout and self.display.is_on):
                    log.info("No motion for %.0f min - display off", idle / 60)
                    self.display.set(False)
                elif not cfg["pir_enabled"] and not self.display.is_on:
                    self.display.set(True)
            except Exception:
                log.exception("presence loop")

    def status(self):
        return {"display_on": self.display.is_on, "sensor_ok": self.sensor_ok,
                "idle_s": int(time.time() - self.last_motion)}
