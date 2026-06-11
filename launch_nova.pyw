"""Launch Nova as its own desktop window (no Edge browser).

Single-instance + self-contained: cleanly kills any previous instance (window,
engine, and its WebView child processes) before starting, so two can never
clash and orphans don't pile up. Shows the HUD in a native Windows WebView2
window with the Nova icon. Run with pythonw.exe (no console)."""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

# pythonw has no console; send stdout/stderr to a log file.
try:
    _log = open(BASE / "nova_hud.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = _log
    sys.stderr = _log
except Exception:
    pass

import socket        # noqa: E402
import subprocess    # noqa: E402
import threading     # noqa: E402
import time          # noqa: E402
import traceback     # noqa: E402

PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"
ICON = str(BASE / "nova.ico")
PIDFILE = BASE / "nova.pid"
CREATE_NO_WINDOW = 0x08000000


def errlog(msg):
    try:
        with open(BASE / "launch_error.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def port_open():
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect(("127.0.0.1", PORT))
        return True
    except Exception:
        return False
    finally:
        s.close()


def kill_previous():
    """Terminate the previous instance and its child processes (by saved PID),
    then free the port as a backstop."""
    try:
        if PIDFILE.exists():
            old = PIDFILE.read_text(encoding="utf-8").strip()
            if old.isdigit() and int(old) != os.getpid():
                subprocess.run(["taskkill", "/PID", old, "/T", "/F"],
                               creationflags=CREATE_NO_WINDOW, timeout=10,
                               capture_output=True)
                time.sleep(0.8)
    except Exception:
        pass
    if port_open():
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-NetTCPConnection -LocalPort {PORT} -State Listen "
                 "-ErrorAction SilentlyContinue | ForEach-Object "
                 "{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                creationflags=CREATE_NO_WINDOW, timeout=8, capture_output=True)
            time.sleep(0.6)
        except Exception:
            pass


def run_server():
    try:
        import uvicorn
        import server
        import config
        host = config.HOST  # 127.0.0.1 (this PC only) unless a remote password is set
        if host != "127.0.0.1":
            errlog(f"remote access ON — listening on {host}:{PORT} (password-gated)")
        uvicorn.run(server.app, host=host, port=PORT,
                    log_level="warning", log_config=None)
    except Exception:
        errlog("SERVER CRASH: " + traceback.format_exc())


def _force_taskbar_icon():
    """Make the taskbar + titlebar use nova.ico. WebView2 windows don't reliably
    pick up pywebview's icon= param, so we set it directly via WM_SETICON once the
    window appears. Runs in a daemon thread; harmless if anything fails."""
    try:
        import win32api
        import win32con
        import win32gui
        hwnd = 0
        for _ in range(40):  # wait up to ~10s for the "Nova" window
            hwnd = win32gui.FindWindow(None, "Nova")
            if hwnd:
                break
            time.sleep(0.25)
        if not hwnd:
            return
        big = win32gui.LoadImage(0, ICON, win32con.IMAGE_ICON, 0, 0,
                                 win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
        small = win32gui.LoadImage(0, ICON, win32con.IMAGE_ICON,
                                   win32api.GetSystemMetrics(win32con.SM_CXSMICON),
                                   win32api.GetSystemMetrics(win32con.SM_CYSMICON),
                                   win32con.LR_LOADFROMFILE)
        win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, big)
        win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, small)
        errlog("taskbar icon set")
    except Exception:
        errlog("set icon failed: " + traceback.format_exc())


def main():
    errlog("launcher starting")
    try:  # group the taskbar button under our own identity so it shows our icon
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Nova.Assistant")
    except Exception:
        pass
    kill_previous()
    try:
        PIDFILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    threading.Thread(target=run_server, daemon=True).start()
    for _ in range(160):
        if port_open():
            break
        time.sleep(0.25)
    if not port_open():
        errlog("server did not come up in time")
    import webview
    errlog("opening Nova window")
    webview.create_window("Nova", URL, width=1040, height=720,
                          background_color="#04070d")
    threading.Thread(target=_force_taskbar_icon, daemon=True).start()
    try:
        webview.start(icon=ICON, storage_path=str(BASE / ".webview"))
    except TypeError:
        webview.start()
    errlog("window closed; exiting")
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        errlog("CRASH: " + traceback.format_exc())
