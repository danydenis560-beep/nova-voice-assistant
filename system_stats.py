"""Live PC stats for the HUD (RAM, battery, internet/ping).

Uses Windows ctypes calls + a socket probe — no extra dependencies. Cached
briefly so the HUD can poll it often without overhead."""
import ctypes
import socket
import time

_cache = {"at": 0.0, "data": None}
_TTL = 3.0  # seconds


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


def _ram_percent():
    try:
        m = _MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return int(m.dwMemoryLoad), round(m.ullTotalPhys / (1024 ** 3), 1)
    except Exception:  # noqa: BLE001
        return None, None


def _battery():
    try:
        s = _SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
            return None, None
        pct = s.BatteryLifePercent
        pct = None if pct == 255 else int(pct)  # 255 = unknown (e.g., desktop)
        charging = (s.ACLineStatus == 1)
        return pct, charging
    except Exception:  # noqa: BLE001
        return None, None


def _ping():
    """(latency_ms, online) via a quick TCP connect to a fast public host."""
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            t = time.time()
            sock = socket.create_connection((host, port), timeout=2)
            sock.close()
            return int((time.time() - t) * 1000), True
        except Exception:  # noqa: BLE001
            continue
    return None, False


def info():
    now = time.time()
    if _cache["data"] is not None and (now - _cache["at"]) < _TTL:
        return _cache["data"]
    ram, total_gb = _ram_percent()
    pct, charging = _battery()
    ms, online = _ping()
    data = {
        "ram": ram, "ram_total_gb": total_gb,
        "battery": pct, "charging": bool(charging) if charging is not None else None,
        "ping_ms": ms, "online": online,
    }
    _cache["data"] = data
    _cache["at"] = now
    return data
