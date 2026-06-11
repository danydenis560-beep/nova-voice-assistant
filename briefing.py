"""Nova daily CEO briefing.

Composes a warm, spoken morning summary from everything the dashboard knows
(weather, to-do list, calendar, YouTube, Shopify) and owns the schedule for
speaking it automatically once a day. The user can also trigger it any time by
voice ("brief me") and change the time by voice ("brief me at 7:30" / "turn off
my morning briefing").

The schedule lives in nova_briefing.json so it survives restarts; server.py's
scheduler polls due() and the engine speaks compose()."""
import datetime
import json
import re

import config
import dashboard

_FILE = config.BASE_DIR / "nova_briefing.json"
CATCHUP_HOURS = 3  # if Nova launches within this long after the time, still brief


def _load():
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(data):
    try:
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _h12(hhmm):
    try:
        h, m = (int(x) for x in hhmm.split(":"))
        ap = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {ap}"
    except Exception:  # noqa: BLE001
        return hhmm


# --- schedule -------------------------------------------------------------
def get_time():
    """Configured briefing time as 'HH:MM', or None if off."""
    data = _load()
    if "time" in data:
        return data["time"] or None
    return (config.BRIEFING_TIME or "").strip() or None


def set_time(spec):
    s = (spec or "").strip().lower()
    data = _load()
    if s in ("off", "none", "disable", "disabled", "stop", "no", ""):
        data["time"] = ""
        _save(data)
        return "Okay, I've turned off your daily briefing."
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if not m:
        return "Tell me a time like 7:30 — I take a 24-hour or am/pm time."
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return "That time doesn't look right — try something like 7:30 in the morning."
    val = f"{hh:02d}:{mm:02d}"
    data["time"] = val
    data.pop("last_fired", None)  # let it fire today if the time still applies
    _save(data)
    return f"Done — I'll give you your briefing every day at {_h12(val)}."


def due(now=None):
    """True (once) when it's time to speak today's briefing; marks it fired."""
    t = get_time()
    if not t:
        return False
    now = now or datetime.datetime.now()
    today = now.date().isoformat()
    data = _load()
    if data.get("last_fired") == today:
        return False
    try:
        hh, mm = (int(x) for x in t.split(":"))
    except Exception:  # noqa: BLE001
        return False
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < target:
        return False
    # We're past today's time and haven't briefed yet.
    data["last_fired"] = today  # mark first so we never double-fire
    _save(data)
    return (now - target).total_seconds() <= CATCHUP_HOURS * 3600


# --- compose --------------------------------------------------------------
def _n(x):
    try:
        return f"{int(x):,}"
    except (TypeError, ValueError):
        return None


def compose(snap=None):
    """Build the full spoken briefing text (plain prose, TTS-friendly)."""
    try:
        snap = snap or dashboard.snapshot()
    except Exception:  # noqa: BLE001
        return "Good day. I couldn't pull your briefing together right now."
    now = datetime.datetime.now().astimezone()
    parts = [snap.get("greeting", "Hello") + f". It's {now.strftime('%A, %B')} {now.day}."]

    w = snap.get("weather", {})
    if w.get("status") == "ok" and w.get("temp") is not None:
        s = f"Right now it's {w['temp']} degrees and {(w.get('text') or '').lower()}".rstrip()
        if w.get("city"):
            s += f" in {w['city']}"
        if w.get("hi") is not None and w.get("lo") is not None:
            s += f", with a high of {w['hi']} and a low of {w['lo']}"
        parts.append(s + ".")

    t = snap.get("tasks", [])
    if t:
        names = "; ".join(x["text"] for x in t[:5])
        more = f", plus {len(t) - 5} more" if len(t) > 5 else ""
        parts.append(f"You have {len(t)} task{'s' if len(t) != 1 else ''} on your list: {names}{more}.")
    else:
        parts.append("Your task list is clear.")

    cal = snap.get("calendar", {})
    if cal.get("status") == "connected":
        evs = cal.get("events", [])
        if evs:
            parts.append("On your calendar: "
                         + "; ".join(f"{e['when']}, {e['title']}" for e in evs[:4]) + ".")
        else:
            parts.append("Nothing on your calendar coming up.")

    yt = snap.get("youtube", {})
    if yt.get("status") == "connected":
        subs = ("a hidden number of" if yt.get("subscribers_hidden")
                else _n(yt.get("subscribers")))
        views = _n(yt.get("views"))
        if subs and views:
            name = yt.get("title") or "Your channel"
            parts.append(f"On YouTube, {name} has {subs} subscribers and {views} total views.")

    sh = snap.get("shopify", {})
    if sh.get("status") == "connected":
        cur = sh.get("currency", "")
        parts.append(f"On Shopify today, {sh.get('orders_today', 0)} "
                     f"order{'s' if sh.get('orders_today') != 1 else ''} "
                     f"for {cur} {sh.get('sales_today', 0)}.".replace("  ", " "))

    try:
        import outlook
        if outlook.is_configured():
            n = outlook.unread_count()
            if n is not None:
                parts.append(f"You have {n} unread email{'s' if n != 1 else ''}.")
    except Exception:  # noqa: BLE001
        pass

    parts.append("That's your briefing. Have a great day.")
    return " ".join(p for p in parts if p)


# --- tools ----------------------------------------------------------------
TOOLS = [
    {"name": "daily_briefing",
     "description": "Give the user their spoken daily briefing right now — a summary of the "
                    "day with weather, their tasks, calendar, and channel stats. Use when they "
                    "ask to be briefed, want their morning summary, or say 'brief me' / "
                    "'what's my day look like'. Read the result out loud in full.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "set_briefing_schedule",
     "description": "Set or turn off the time Nova automatically gives the daily briefing each "
                    "day. Use when the user asks to be briefed at a certain time, or to stop the "
                    "automatic briefing.",
     "input_schema": {"type": "object", "properties": {
         "time": {"type": "string",
                  "description": "24-hour time as HH:MM (e.g. '07:30'), or 'off' to disable."}},
         "required": ["time"]}},
]

NAMES = {"daily_briefing", "set_briefing_schedule"}

_DISPATCH = {
    "daily_briefing": lambda i: compose(),
    "set_briefing_schedule": lambda i: set_time(i.get("time", "")),
}


def dispatch(name, tool_input):
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown briefing tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"Briefing tool '{name}' failed: {e}"
