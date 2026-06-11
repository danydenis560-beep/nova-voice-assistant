"""Personal dashboard data for the Nova HUD.

Builds a snapshot the HUD renders as cards: greeting + time, weather
(Open-Meteo — no API key, location auto-detected from IP), the to-do list, a
Shopify summary if connected, and 'connect to enable' placeholders for the
sources that need accounts (calendar, YouTube). Every source is wrapped so one
failure never breaks the dashboard."""
import datetime
import json
import time

import httpx

import config
import gcal
import shopify_tools
import tasks
import youtube

_LOC_FILE = config.BASE_DIR / "nova_location.json"

# WMO weather codes (Open-Meteo) -> (description, emoji).
_WMO = {
    0: ("Clear", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"), 45: ("Fog", "🌫️"), 48: ("Freezing fog", "🌫️"),
    51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌧️"),
    56: ("Freezing drizzle", "🌧️"), 57: ("Freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"), 67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"), 73: ("Snow", "🌨️"), 75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "❄️"), 80: ("Rain showers", "🌦️"), 81: ("Rain showers", "🌧️"),
    82: ("Heavy showers", "⛈️"), 85: ("Snow showers", "🌨️"), 86: ("Snow showers", "🌨️"),
    95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm", "⛈️"), 99: ("Thunderstorm", "⛈️"),
}

WEATHER_TTL = 900  # seconds (15 min)
_loc = {"data": None}
_wx = {"at": 0.0, "data": None}


def _r(x):
    return round(x) if isinstance(x, (int, float)) else None


def _greeting(now):
    h = now.hour
    if h < 12:
        return "Good morning"
    if h < 18:
        return "Good afternoon"
    return "Good evening"


def _load_loc_file():
    try:
        return json.loads(_LOC_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _save_loc_file(d):
    try:
        _LOC_FILE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _location():
    """Lat/lon for weather: config override, then disk cache, then IP lookup.

    Tries two no-key geolocation providers (http ip-api, then https ipwho.is)
    and persists the result so later launches are instant and reliable."""
    if config.WEATHER_LAT and config.WEATHER_LON:
        try:
            return {"lat": float(config.WEATHER_LAT), "lon": float(config.WEATHER_LON),
                    "city": config.WEATHER_CITY or ""}
        except ValueError:
            pass
    if _loc["data"] is not None:
        return _loc["data"]
    onfile = _load_loc_file()
    if onfile and onfile.get("lat") is not None:
        _loc["data"] = onfile
        return onfile
    for url in ("http://ip-api.com/json/?fields=status,city,regionName,lat,lon",
                "https://ipwho.is/"):
        try:
            d = httpx.get(url, timeout=6).json()
            lat = d.get("lat", d.get("latitude"))
            lon = d.get("lon", d.get("longitude"))
            ok = d.get("status") == "success" or d.get("success") is True
            if ok and lat is not None and lon is not None:
                city = (config.WEATHER_CITY or d.get("city")
                        or d.get("regionName") or d.get("region") or "")
                data = {"lat": float(lat), "lon": float(lon), "city": city}
                _loc["data"] = data
                _save_loc_file(data)
                return data
        except Exception:  # noqa: BLE001
            continue
    return None


def weather():
    if _wx["data"] is not None and (time.time() - _wx["at"]) < WEATHER_TTL:
        return _wx["data"]
    loc = _location()
    if not loc:
        return {"status": "unavailable"}
    metric = config.UNITS != "imperial"
    params = {
        "latitude": loc["lat"], "longitude": loc["lon"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "auto", "forecast_days": 1,
        "temperature_unit": "celsius" if metric else "fahrenheit",
        "wind_speed_unit": "kmh" if metric else "mph",
    }
    # Retry a couple of times — the first call on a cold process sometimes times out.
    for attempt in range(3):
        try:
            r = httpx.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=10)
            d = r.json()
            cur = d.get("current", {})
            daily = d.get("daily", {})
            code = int(cur.get("weather_code", 0) or 0)
            text, emoji = _WMO.get(code, ("", "🌡️"))
            if code in (0, 1) and not cur.get("is_day", 1):
                emoji = "🌙"
            hi = daily.get("temperature_2m_max") or [None]
            lo = daily.get("temperature_2m_min") or [None]
            out = {
                "status": "ok",
                "temp": _r(cur.get("temperature_2m")),
                "feels": _r(cur.get("apparent_temperature")),
                "humidity": _r(cur.get("relative_humidity_2m")),
                "text": text, "emoji": emoji,
                "hi": _r(hi[0]), "lo": _r(lo[0]),
                "wind": _r(cur.get("wind_speed_10m")),
                "unit": "C" if metric else "F",
                "wind_unit": "km/h" if metric else "mph",
                "city": loc.get("city", ""),
            }
            _wx["data"] = out
            _wx["at"] = time.time()
            return out
        except Exception:  # noqa: BLE001
            if attempt < 2:
                time.sleep(0.5)
    # All attempts failed: serve stale data if we have any, else mark unavailable.
    return _wx["data"] or {"status": "unavailable"}


def _tasks():
    try:
        return [{"id": i["id"], "text": i["text"], "due": i.get("due", "")}
                for i in tasks.open_tasks()]
    except Exception:  # noqa: BLE001
        return []


def _shopify():
    try:
        return shopify_tools.dashboard_summary()
    except Exception:  # noqa: BLE001
        return {"status": "error"}


def _calendar():
    try:
        return gcal.summary(days=7, limit=4)
    except Exception:  # noqa: BLE001
        return {"status": "error"}


def _youtube():
    try:
        return youtube.stats()
    except Exception:  # noqa: BLE001
        return {"status": "error"}


def _briefing(now, wx, tlist):
    bits = [_greeting(now) + "."]
    n = len(tlist)
    bits.append(f"You have {n} task{'s' if n != 1 else ''} today." if n
                else "Your task list is clear.")
    if wx.get("status") == "ok" and wx.get("temp") is not None:
        where = f" in {wx['city']}" if wx.get("city") else ""
        bits.append(f"It's {wx['temp']}°{wx['unit']} and {wx['text'].lower()}{where}.")
    return " ".join(bits)


def snapshot():
    """The full dashboard payload (safe to serialize as JSON)."""
    now = datetime.datetime.now().astimezone()
    wx = weather()
    tlist = _tasks()
    return {
        "greeting": _greeting(now),
        "date": now.strftime("%A, %B %d"),
        "time": now.strftime("%I:%M %p").lstrip("0"),
        "weather": wx,
        "tasks": tlist,
        "shopify": _shopify(),
        "calendar": _calendar(),
        "youtube": _youtube(),
        "briefing": _briefing(now, wx, tlist),
    }
