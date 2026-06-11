"""YouTube channel stats for Nova via the public Data API v3.

Needs only a free API key (no OAuth): set YOUTUBE_API_KEY and YOUTUBE_CHANNEL
(an @handle or a UC... channel ID) in config/.env. Returns public counts —
subscribers, total views, video count — for the dashboard and voice. (Per-video
analytics / watch-time would need the OAuth Analytics API; not done here.)"""
import time

import httpx

import config

API = "https://www.googleapis.com/youtube/v3/channels"
_CACHE_TTL = 1800  # 30 min (be polite to the daily quota)
_cache = {"at": 0.0, "data": None, "key": ""}


def _connected():
    return bool((config.YOUTUBE_API_KEY or "").strip()
                and (config.YOUTUBE_CHANNEL or "").strip())


def _selector(channel):
    """Map the configured channel to the right Data API lookup param."""
    c = (channel or "").strip()
    if c.startswith("UC") and len(c) == 24:
        return {"id": c}
    if c.startswith("@"):
        return {"forHandle": c}
    return {"forHandle": "@" + c}


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _parse(data):
    items = data.get("items") or []
    if not items:
        return {"status": "error", "message": "channel not found — check the handle/ID"}
    it = items[0]
    st = it.get("statistics", {}) or {}
    sn = it.get("snippet", {}) or {}
    hidden = bool(st.get("hiddenSubscriberCount"))
    return {
        "status": "connected",
        "title": sn.get("title", ""),
        "subscribers": None if hidden else _int(st.get("subscriberCount")),
        "subscribers_hidden": hidden,
        "views": _int(st.get("viewCount")),
        "videos": _int(st.get("videoCount")),
    }


def stats():
    """Structured channel stats for the dashboard card."""
    if not _connected():
        return {"status": "not_connected"}
    api_key = config.YOUTUBE_API_KEY.strip()
    key = api_key + "|" + config.YOUTUBE_CHANNEL.strip()
    now = time.time()
    if _cache["data"] is not None and _cache["key"] == key and (now - _cache["at"]) < _CACHE_TTL:
        return _cache["data"]
    params = {"part": "snippet,statistics", "key": api_key}
    params.update(_selector(config.YOUTUBE_CHANNEL))
    try:
        r = httpx.get(API, params=params, timeout=8)
        if r.status_code == 403:
            return {"status": "error", "message": "API key rejected or quota exceeded"}
        if r.status_code >= 400:
            return {"status": "error", "message": f"YouTube error {r.status_code}"}
        out = _parse(r.json())
        if out.get("status") == "connected":
            _cache.update(at=now, data=out, key=key)
        return out
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}


def _fmt(n):
    return f"{n:,}" if isinstance(n, int) else "an unknown number of"


def youtube_stats():
    """Spoken-friendly channel summary."""
    s = stats()
    if s["status"] == "not_connected":
        return ("Your YouTube channel isn't connected yet. Ask me how to connect it "
                "and I'll walk you through getting a free API key.")
    if s["status"] == "error":
        return "I couldn't get your YouTube stats right now."
    subs = "a hidden number of" if s.get("subscribers_hidden") else _fmt(s.get("subscribers"))
    name = s.get("title") or "Your channel"
    return (f"{name} has {subs} subscribers, {_fmt(s.get('views'))} total views, "
            f"and {_fmt(s.get('videos'))} videos.")


TOOLS = [
    {"name": "youtube_stats",
     "description": "Report the user's YouTube channel stats — subscribers, total views, and "
                    "number of videos. Use when they ask about their channel, subscribers, "
                    "views, or YouTube growth.",
     "input_schema": {"type": "object", "properties": {}}},
]

NAMES = {"youtube_stats"}

_DISPATCH = {
    "youtube_stats": lambda i: youtube_stats(),
}


def dispatch(name, tool_input):
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown YouTube tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"YouTube tool '{name}' failed: {e}"
