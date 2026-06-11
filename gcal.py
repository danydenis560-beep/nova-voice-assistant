"""Google Calendar (read-only) for Nova — via the calendar's private iCal URL.

No OAuth or Google Cloud project needed: the user copies their calendar's
"Secret address in iCal format" into GOOGLE_CALENDAR_ICS (config/.env). We fetch
and parse it (expanding recurring events) and surface the upcoming schedule to
the dashboard and to voice ("what's on my calendar?").

Named gcal (not 'calendar') so it doesn't shadow Python's stdlib calendar
module, which icalendar/dateutil import internally."""
import datetime
import time

import httpx

import config

WINDOW = 14          # days of events to fetch/cache
_CACHE_TTL = 600     # seconds (10 min)
_cache = {"at": 0.0, "events": None, "key": ""}


def _connected():
    return bool((config.GOOGLE_CALENDAR_ICS or "").strip())


def _local(dt):
    """Return an aware local datetime for an iCal date or datetime."""
    if isinstance(dt, datetime.datetime):
        return dt.astimezone()  # converts aware; treats naive/floating as local
    return datetime.datetime(dt.year, dt.month, dt.day).astimezone()  # all-day -> local midnight


def _parse_ics(text):
    """Parse iCal text into a sorted event list, expanding recurrences."""
    import icalendar
    import recurring_ical_events
    cal = icalendar.Calendar.from_ical(text)
    start = datetime.date.today()
    end = start + datetime.timedelta(days=WINDOW)
    out = []
    for e in recurring_ical_events.of(cal).between(start, end):
        try:
            ds = e.get("DTSTART").dt
            summary = str(e.get("SUMMARY", "") or "").strip() or "(busy)"
            location = str(e.get("LOCATION", "") or "").strip()
            out.append({
                "summary": summary,
                "start": _local(ds),
                "all_day": not isinstance(ds, datetime.datetime),
                "location": location,
            })
        except Exception:  # noqa: BLE001
            continue
    out.sort(key=lambda x: x["start"])
    return out


def _fetch_events():
    """Fetch + parse the iCal feed into a sorted event list (cached)."""
    url = (config.GOOGLE_CALENDAR_ICS or "").strip()
    if not url:
        return None
    now = time.time()
    if (_cache["events"] is not None and _cache["key"] == url
            and (now - _cache["at"]) < _CACHE_TTL):
        return _cache["events"]
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True)
        if r.status_code >= 400:
            return _cache["events"]  # serve stale on error if we have it
        out = _parse_ics(r.text)
        _cache.update(at=now, events=out, key=url)
        return out
    except Exception:  # noqa: BLE001
        return _cache["events"]


def upcoming(days=7, limit=6):
    """Upcoming events within `days`, soonest first (None if unreachable)."""
    evs = _fetch_events()
    if evs is None:
        return None
    now = datetime.datetime.now().astimezone()
    today = now.date()
    horizon = today + datetime.timedelta(days=days)
    res = []
    for e in evs:
        d = e["start"].date()
        if d > horizon:
            continue
        if e["all_day"]:
            if d < today:
                continue
        elif e["start"] < now:
            continue
        res.append(e)
    return res[:limit]


def _when(e, now):
    s = e["start"]
    today = now.date()
    d = s.date()
    if d == today:
        day = "Today"
    elif d == today + datetime.timedelta(days=1):
        day = "Tomorrow"
    elif (d - today).days < 7:
        day = s.strftime("%A")
    else:
        day = s.strftime("%a %b %d")
    if e["all_day"]:
        return day + " (all day)"
    return day + " " + s.strftime("%I:%M %p").lstrip("0")


def summary(days=7, limit=4):
    """Structured calendar payload for the dashboard card."""
    if not _connected():
        return {"status": "not_connected"}
    evs = upcoming(days, limit)
    if evs is None:
        return {"status": "error"}
    now = datetime.datetime.now().astimezone()
    return {"status": "connected",
            "events": [{"when": _when(e, now), "title": e["summary"],
                        "location": e["location"]} for e in evs]}


def check_calendar(days=2):
    """Spoken-friendly summary of what's coming up."""
    if not _connected():
        return ("Your Google Calendar isn't connected yet. Ask me how to connect "
                "it and I'll walk you through copying your calendar's private link.")
    evs = upcoming(days=days, limit=8)
    if evs is None:
        return "I couldn't reach your calendar right now."
    if not evs:
        span = "today" if days <= 1 else f"the next {days} days"
        return f"Nothing on your calendar for {span}."
    now = datetime.datetime.now().astimezone()
    parts = [f"{_when(e, now)}, {e['summary']}" for e in evs]
    return "Coming up: " + "; ".join(parts) + "."


TOOLS = [
    {"name": "check_calendar",
     "description": "Read out the user's upcoming Google Calendar events. Use when they ask "
                    "what's on their calendar, their schedule, their next meeting, or what "
                    "they have on today, tomorrow, or this week.",
     "input_schema": {"type": "object", "properties": {
         "days": {"type": "integer",
                  "description": "How many days ahead to include (1 = today/tomorrow, 7 = this week). Default 2."}}}},
]

NAMES = {"check_calendar"}

_DISPATCH = {
    "check_calendar": lambda i: check_calendar(int(i.get("days", 2) or 2)),
}


def dispatch(name, tool_input):
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown calendar tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"Calendar tool '{name}' failed: {e}"
