"""Let Nova post to the user's Telegram and Discord.

Telegram: a bot (from @BotFather) → TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
  (channel @username, e.g. @yourchannel — the bot must be an admin of the channel).
Discord: a BOT token + server (guild) id → access to the WHOLE server; Nova can
  post to any channel by name (DISCORD_BOT_TOKEN + DISCORD_GUILD_ID). A single
  channel webhook (DISCORD_WEBHOOK_URL) is supported as a simpler fallback.

Sends are gated through confirm_fn (the HUD's Allow/Deny) so a misheard command
can't auto-post to a public channel."""
import time

import httpx

import config

DISCORD_API = "https://discord.com/api/v10"

# Set by server.py to hud_confirm; None elsewhere (then sends proceed).
confirm_fn = None
_dc_cache = {"at": 0.0, "chans": None, "key": ""}


def _confirm(preview):
    if confirm_fn is None:
        return True
    try:
        return bool(confirm_fn(preview))
    except Exception:  # noqa: BLE001
        return True


# --- Telegram -------------------------------------------------------------
def send_telegram(text):
    text = (text or "").strip()
    if not text:
        return "What should I send?"
    token = (config.TELEGRAM_BOT_TOKEN or "").strip()
    chat = (config.TELEGRAM_CHAT_ID or "").strip()
    if not (token and chat):
        return ("Telegram isn't connected yet. Ask me how to connect it — it takes "
                "a minute with the BotFather.")
    if not _confirm(f"Send this to Telegram ({chat})?\n\n{text}"):
        return "Okay, I didn't send it."
    try:
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       data={"chat_id": chat, "text": text}, timeout=15)
    except Exception as e:  # noqa: BLE001
        return f"Couldn't reach Telegram: {e}"
    if r.status_code == 401:
        return "Telegram rejected the bot token — it looks invalid. Re-copy it from BotFather."
    if r.status_code >= 400:
        return (f"Telegram wouldn't send it ({r.status_code}). Make sure the bot is an "
                f"admin of the channel and the chat id is right.")
    return "Sent to Telegram."


# --- Discord (whole server, via bot) --------------------------------------
def _discord_channels():
    """List the server's text channels [{id,name}] (cached), or None if not set."""
    token = (config.DISCORD_BOT_TOKEN or "").strip()
    guild = (config.DISCORD_GUILD_ID or "").strip()
    if not (token and guild):
        return None
    now = time.time()
    if _dc_cache["chans"] is not None and _dc_cache["key"] == guild and (now - _dc_cache["at"]) < 300:
        return _dc_cache["chans"]
    try:
        r = httpx.get(f"{DISCORD_API}/guilds/{guild}/channels",
                      headers={"Authorization": f"Bot {token}"}, timeout=15)
        if r.status_code >= 400:
            return None
        chans = [{"id": c["id"], "name": c.get("name", "")}
                 for c in r.json() if c.get("type") in (0, 5)]  # text + announcement
        _dc_cache.update(at=now, chans=chans, key=guild)
        return chans
    except Exception:  # noqa: BLE001
        return None


def _resolve_channel(channel):
    chans = _discord_channels()
    if not chans:
        return None
    want = (channel or "").strip().lstrip("#").lower()
    if want:
        for c in chans:
            if c["name"].lower() == want:
                return c
        for c in chans:
            if want in c["name"].lower():
                return c
    default = (config.DISCORD_DEFAULT_CHANNEL or "").strip().lstrip("#").lower()
    for c in chans:
        if c["name"].lower() == default:
            return c
    return chans[0]


def list_discord_channels():
    if not ((config.DISCORD_BOT_TOKEN or "").strip() and (config.DISCORD_GUILD_ID or "").strip()):
        return "Discord server access isn't connected yet."
    chans = _discord_channels()
    if chans is None:
        return "I couldn't reach Discord — check the bot token and that the bot is in the server."
    if not chans:
        return "I don't see any channels (the bot needs the View Channels permission)."
    return "Channels I can post to: " + ", ".join("#" + c["name"] for c in chans) + "."


def send_discord(text, channel=""):
    text = (text or "").strip()
    if not text:
        return "What should I send?"
    token = (config.DISCORD_BOT_TOKEN or "").strip()
    guild = (config.DISCORD_GUILD_ID or "").strip()
    webhook = (config.DISCORD_WEBHOOK_URL or "").strip()
    if not ((token and guild) or webhook):
        return "Discord isn't connected yet. Ask me how to connect it."
    where = ("#" + channel.lstrip("#")) if channel else "Discord"
    if not _confirm(f"Post this to {where}?\n\n{text}"):
        return "Okay, I didn't post it."
    # Prefer the bot (whole-server access).
    if token and guild:
        ch = _resolve_channel(channel)
        if not ch:
            return ("I couldn't find that channel, or the bot can't see it. Make sure the "
                    "bot is in the server with the View Channels permission.")
        try:
            r = httpx.post(f"{DISCORD_API}/channels/{ch['id']}/messages",
                           headers={"Authorization": f"Bot {token}"},
                           json={"content": text[:1900]}, timeout=15)
        except Exception as e:  # noqa: BLE001
            return f"Couldn't reach Discord: {e}"
        if r.status_code in (401, 403):
            return "Discord refused — check the bot token and that it has Send Messages permission."
        if r.status_code >= 400:
            return f"Discord wouldn't post it ({r.status_code})."
        return f"Posted to #{ch['name']}."
    # Fallback: single-channel webhook.
    try:
        r = httpx.post(webhook, json={"content": text[:1900]}, timeout=15)
    except Exception as e:  # noqa: BLE001
        return f"Couldn't reach Discord: {e}"
    if r.status_code >= 400:
        return f"Discord wouldn't post it ({r.status_code}). Check the webhook URL."
    return "Posted to Discord."


TOOLS = [
    {"name": "send_telegram",
     "description": "Post a message to the user's Telegram channel/chat. Use when they ask to "
                    "send, post, or announce something on Telegram.",
     "input_schema": {"type": "object", "properties": {
         "message": {"type": "string", "description": "The message text to send."}},
         "required": ["message"]}},
    {"name": "send_discord",
     "description": "Post a message to the user's Discord server. Optionally name a channel "
                    "(e.g. 'announcements'); otherwise the default channel is used. Use when "
                    "they ask to send, post, or announce something on Discord.",
     "input_schema": {"type": "object", "properties": {
         "message": {"type": "string", "description": "The message text to post."},
         "channel": {"type": "string", "description": "Optional channel name to post to (without the #)."}},
         "required": ["message"]}},
    {"name": "list_discord_channels",
     "description": "List the Discord channels Nova can post to in the user's server. Use when "
                    "the user asks which channels are available or where Nova can post.",
     "input_schema": {"type": "object", "properties": {}}},
]

NAMES = {"send_telegram", "send_discord", "list_discord_channels"}

_DISPATCH = {
    "send_telegram": lambda i: send_telegram(i.get("message", "")),
    "send_discord": lambda i: send_discord(i.get("message", ""), i.get("channel", "")),
    "list_discord_channels": lambda i: list_discord_channels(),
}


def dispatch(name, tool_input):
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown messaging tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"Messaging tool '{name}' failed: {e}"
