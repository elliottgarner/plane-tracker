"""Turn the panel on/off on Raspberry Pi OS Bookworm (Wayland: labwc/Wayfire, or X11)."""
import glob
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from .config import cfg

log = logging.getLogger("display")


def _run(cmd, env=None, timeout=8):
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            log.debug("%s -> rc=%s %s", cmd, p.returncode, p.stderr.strip())
        return p
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("%s failed: %s", cmd, e)
        return None


def _wayland_env():
    """Find the compositor socket even when we run as a system service without a session env."""
    env = os.environ.copy()
    if env.get("XDG_RUNTIME_DIR") and env.get("WAYLAND_DISPLAY"):
        return env
    for sock in sorted(glob.glob("/run/user/*/wayland-*")):
        if sock.endswith(".lock"):
            continue
        env["XDG_RUNTIME_DIR"] = os.path.dirname(sock)
        env["WAYLAND_DISPLAY"] = os.path.basename(sock)
        return env
    return None


def _x11_env():
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    if "XAUTHORITY" not in env:
        for cand in glob.glob("/home/*/.Xauthority"):
            env["XAUTHORITY"] = cand
            break
    return env


class DisplayPower:
    def __init__(self):
        self.is_on = True
        self._method = None
        self._lock = threading.Lock()
        self._relay = None
        self._relay_key = None
        self.reload()

    # -- optional relay / transistor that cuts the panel's own power ------------------
    def reload(self):
        """(Re)open the relay pin from config; the panel is left powered."""
        key = (cfg["panel_relay_gpio"], cfg["panel_relay_active_low"])
        if key == self._relay_key:
            return
        with self._lock:
            self._close_relay()
            self._relay_key = key
            pin, active_low = key
            if not pin or sys.platform == "win32":
                return
            try:
                from gpiozero import OutputDevice
                # "on" = panel powered; initial_value=True so it is never dark while we start up
                self._relay = OutputDevice(pin, active_high=not active_low, initial_value=True)
                self.is_on = True
                log.info("Panel power relay on GPIO%s (%s)", pin, "active-low" if active_low else "active-high")
            except Exception as e:
                self._relay = None
                log.warning("Panel relay unavailable (%s) - using software screen blanking only", e)

    def _close_relay(self):
        if self._relay:
            try:
                self._relay.on()   # never leave the panel unpowered
                self._relay.close()
            except Exception:
                pass
        self._relay = None

    # -- individual back-ends: each returns True on success ----------------------
    def _wlr_randr(self, on):
        env = _wayland_env()
        if not env or not shutil.which("wlr-randr"):
            return False
        outputs = [cfg["display_output"]] if cfg["display_output"] else []
        if not outputs:
            p = _run(["wlr-randr"], env)
            if not p:
                return False
            outputs = re.findall(r"^(\S+)", p.stdout, re.M)
        ok = bool(outputs)
        for o in outputs:
            p = _run(["wlr-randr", "--output", o, "--on" if on else "--off"], env)
            ok = ok and p is not None and p.returncode == 0
        return ok

    def _wlopm(self, on):
        env = _wayland_env()
        if not env or not shutil.which("wlopm"):
            return False
        out = cfg["display_output"] or "*"
        p = _run(["wlopm", "--on" if on else "--off", out], env)
        return p is not None and p.returncode == 0

    def _xset(self, on):
        if not shutil.which("xset"):
            return False
        env = _x11_env()
        p = _run(["xset", "dpms", "force", "on" if on else "off"], env)
        if p is not None and p.returncode == 0 and on:
            _run(["xset", "s", "reset"], env)
        return p is not None and p.returncode == 0

    def _vcgencmd(self, on):
        if not shutil.which("vcgencmd"):
            return False
        p = _run(["vcgencmd", "display_power", "1" if on else "0"])
        return p is not None and p.returncode == 0 and "display_power=" in p.stdout

    def _backlight(self, on):
        paths = glob.glob("/sys/class/backlight/*/bl_power")
        ok = False
        for path in paths:
            try:
                with open(path, "w") as f:
                    f.write("0" if on else "1")
                ok = True
            except OSError:
                pass
        return ok

    METHODS = {"wlr-randr": "_wlr_randr", "wlopm": "_wlopm", "xset": "_xset",
               "vcgencmd": "_vcgencmd", "backlight": "_backlight"}

    def _software(self, on):
        """Blank/unblank via the compositor, DPMS or backlight. True on success."""
        choice = cfg["display_method"]
        if choice == "none":
            return True
        order = [choice] if choice != "auto" else (
            [self._method] if self._method else ["wlr-randr", "wlopm", "xset", "vcgencmd", "backlight"])
        for name in order:
            if name and getattr(self, self.METHODS[name])(on):
                if self._method != name:
                    log.info("Display control via %s", name)
                self._method = name
                return True
        log.error("No working display power method (tried %s)", order)
        return False

    def set(self, on: bool) -> bool:
        with self._lock:
            if on == self.is_on and (self._method or self._relay):
                return True
            if sys.platform == "win32":
                log.info("[dev] display %s", "ON" if on else "OFF")
                self.is_on = on
                return True
            if self._relay is None:
                ok = self._software(on)
                if ok:
                    self.is_on = on
                    log.info("Display %s", "ON" if on else "OFF")
                return ok
            # Relay fitted: blank first then cut power; power up, let the panel wake, then unblank.
            if on:
                self._relay.on()
                time.sleep(cfg["panel_relay_boot_seconds"])
                self._software(True)
            else:
                self._software(False)
                self._relay.off()
            self.is_on = on
            log.info("Display %s (relay)", "ON" if on else "OFF")
            return True
