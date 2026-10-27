"""Wi-Fi management through NetworkManager (nmcli) - the default on Raspberry Pi OS Bookworm.

Joining a network from a page served over the *current* Wi-Fi can cut you off, so `connect()` keeps the
previous profile and rolls back automatically if the new network does not give us a working connection.
Passwords are passed to nmcli as arguments and never logged.
"""
import logging
import shutil
import socket
import subprocess
import sys
import threading
import time

log = logging.getLogger("wifi")
_lock = threading.Lock()
progress = {"state": "idle", "detail": "", "ssid": "", "ts": 0.0}   # idle|connecting|ok|failed


def available() -> bool:
    return sys.platform != "win32" and shutil.which("nmcli") is not None


def _nmcli(*args, timeout=20):
    return subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)


def _fields(line):
    """Split an `nmcli -t` line on unescaped ':' (fields escape ':' and '\\' with a backslash)."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _rows(*args, timeout=20):
    p = _nmcli("-t", *args, timeout=timeout)
    return [_fields(l) for l in p.stdout.splitlines() if l.strip()] if p.returncode == 0 else []


def _wifi_device():
    for dev, typ, state, conn in _rows("-f", "DEVICE,TYPE,STATE,CONNECTION", "dev"):
        if typ == "wifi":
            return dev, state, conn
    return None, "", ""


def saved():
    """[(name, active_bool)] of saved Wi-Fi profiles."""
    return [(n, bool(dev)) for n, typ, dev in _rows("-f", "NAME,TYPE,DEVICE", "con", "show") if typ == "802-11-wireless"]


def status():
    dev, state, conn = _wifi_device()
    ip = ""
    if dev:
        p = _nmcli("-g", "IP4.ADDRESS", "dev", "show", dev)
        ip = p.stdout.strip().splitlines()[0].split("/")[0] if p.returncode == 0 and p.stdout.strip() else ""
    return {"available": True, "device": dev, "state": state, "connection": conn, "ip": ip,
            "saved": [{"name": n, "active": a} for n, a in saved()], "progress": dict(progress)}


def scan(rescan=True):
    rows = _rows("-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes" if rescan else "no",
                 timeout=30)
    best = {}
    for inuse, ssid, signal, sec in (r + [""] * (4 - len(r)) for r in rows):
        if not ssid:
            continue
        sig = int(signal) if signal.isdigit() else 0
        cur = best.get(ssid)
        if cur is None or sig > cur["signal"] or inuse == "*":
            best[ssid] = {"ssid": ssid, "signal": sig, "secure": bool(sec and sec != "--"),
                          "security": sec if sec != "--" else "", "active": inuse == "*" or bool(cur and cur["active"])}
    return sorted(best.values(), key=lambda n: (-n["active"], -n["signal"]))


def _online(timeout=25):
    """True once the Pi can open an outbound TCP connection (i.e. a real, working network)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("1.1.1.1", 443), 3).close()
            return True
        except OSError:
            time.sleep(1.5)
    return False


def _set(state, detail="", ssid=""):
    with _lock:
        progress.update(state=state, detail=detail, ssid=ssid or progress["ssid"], ts=time.time())


def start_connect(ssid: str, password: str = "", hidden: bool = False):
    if not ssid or len(ssid.encode()) > 32:
        raise ValueError("SSID must be 1-32 bytes")
    if password and not (8 <= len(password) <= 63):
        raise ValueError("Wi-Fi password must be 8-63 characters")
    if progress["state"] == "connecting":
        raise RuntimeError("a connection attempt is already running")
    _set("connecting", "", ssid)
    threading.Thread(target=_connect, args=(ssid, password, hidden), name="wifi-connect", daemon=True).start()


def _connect(ssid, password, hidden):
    try:
        before = dict(saved())                       # name -> active
        prev = next((n for n, a in before.items() if a), None)
        if ssid in before:                           # existing profile: update the key, then bring it up
            if password:
                _nmcli("con", "modify", "id", ssid, "wifi-sec.psk", password)
            p = _nmcli("--wait", "30", "con", "up", "id", ssid, timeout=45)
        else:
            cmd = ["--wait", "30", "dev", "wifi", "connect", ssid]
            if password:
                cmd += ["password", password]
            if hidden:
                cmd += ["hidden", "yes"]
            p = _nmcli(*cmd, timeout=45)
        ok = p.returncode == 0
        err = (p.stderr or p.stdout).strip().splitlines()[-1:] or [""]
        if ok:
            _set("connecting", "connected, checking internet…")
            ok = _online()
            if not ok:
                err = ["connected but no internet access"]
        if ok:
            _set("ok", "Connected to " + ssid)
            return
        # ---- roll back so the display is never stranded ----
        log.warning("Wi-Fi join of %r failed (%s) - rolling back", ssid, err[0])
        if ssid not in before:
            _nmcli("con", "delete", "id", ssid)      # remove the half-made profile
        if prev:
            _nmcli("--wait", "30", "con", "up", "id", prev, timeout=45)
        _set("failed", f"{err[0] or 'could not connect'} - reverted to {prev or 'previous state'}")
    except Exception as e:
        log.exception("wifi connect")
        _set("failed", str(e))


def forget(name: str):
    names = dict(saved())
    if name not in names:
        raise ValueError("unknown network")
    if names[name]:
        raise ValueError("can't forget the network you're connected to (join another first)")
    p = _nmcli("con", "delete", "id", name)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
