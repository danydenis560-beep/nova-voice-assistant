"""Nova configuration. Tweak anything here, or override via the .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --- Claude (the brain) ---------------------------------------------------
# Default is the most capable model. For a snappier voice experience you can
# switch to a faster one by setting NOVA_MODEL in .env:
#   claude-opus-4-8     -> most capable (default)
#   claude-sonnet-4-6   -> faster, still very smart  (great for voice)
#   claude-haiku-4-5    -> fastest/cheapest (web research is weaker here)
MODEL = os.getenv("NOVA_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# --- Speech-to-text (Whisper, runs locally and free) ----------------------
# Multilingual: tiny / base / small. (Use base.en / tiny.en for English-only.)
WHISPER_MODEL = os.getenv("NOVA_WHISPER_MODEL", "base")
# Transcription language: blank = auto-detect (English + French), or lock to
# "en" / "fr".
LANGUAGE = os.getenv("NOVA_LANGUAGE", "")

# --- Voice / interaction --------------------------------------------------
PUSH_TO_TALK_KEY = os.getenv("NOVA_KEY", "f9")      # hold this key to talk
TTS_RATE = int(os.getenv("NOVA_TTS_RATE", "185"))   # speaking speed (wpm)
# Part of a Windows voice name to prefer, e.g. "Zira", "David", "Mark".
# Leave blank to use the system default voice.
TTS_VOICE = os.getenv("NOVA_TTS_VOICE", "")

# Text-to-speech engine: "edge" = free neural voices (online, very human),
# "sapi" = offline Windows voices (used automatically as a fallback). edge-tts
# voice ideas: en-GB-RyanNeural (British male, Nova-like), en-GB-SoniaNeural,
# en-US-AriaNeural, en-US-GuyNeural, fr-FR-HenriNeural, fr-FR-DeniseNeural.
TTS_ENGINE = os.getenv("NOVA_TTS_ENGINE", "edge").lower()
TTS_EDGE_VOICE = os.getenv("NOVA_TTS_EDGE_VOICE", "en-GB-RyanNeural")
TTS_EDGE_VOICE_FR = os.getenv("NOVA_TTS_EDGE_VOICE_FR", "fr-FR-HenriNeural")
TTS_EDGE_RATE = os.getenv("NOVA_TTS_EDGE_RATE", "")  # e.g. "+10%" faster; blank = natural

# Microphone to record from. Blank = auto-pick a real mic (skips virtual
# cables like VB-Audio). Or set part of a device name (e.g. "Microphone
# Array") or a device number to force a specific one.
INPUT_DEVICE = os.getenv("NOVA_MIC", "")

# --- Safety ---------------------------------------------------------------
# Ask you to confirm in the console before any PowerShell command runs.
CONFIRM_SHELL = os.getenv("NOVA_CONFIRM_SHELL", "true").lower() == "true"

# --- Remote access (control Nova from your phone) -----------------------
# A password your phone (or any other device) must enter once to reach Nova.
# Your own PC window NEVER needs it. BLANK = remote access is OFF and Nova
# listens on this PC only (the safest default — nothing changes until you opt in
# by setting a password). Nova can run shell commands, so it must never be
# exposed to the network without this gate.
ACCESS_PASSWORD = os.getenv("NOVA_ACCESS_PASSWORD", "").strip()
# Which network address the server listens on. Blank = automatic: "127.0.0.1"
# (this PC only) when no password is set, "0.0.0.0" (reachable from your phone
# over Tailscale/your home Wi-Fi) once you set one. Only override if you know why.
HOST = os.getenv("NOVA_HOST", "").strip() or (
    "0.0.0.0" if ACCESS_PASSWORD else "127.0.0.1")

# --- Voice ID (speaker verification) --------------------------------------
# In always-listen mode, only respond to your enrolled voice. 0.0-1.0; higher
# is stricter. ~0.25 works well after a clean 15s enrollment. Lower it if it
# sometimes ignores you; raise it if other voices still get through.
VOICE_THRESHOLD = float(os.getenv("NOVA_VOICE_THRESHOLD", "0.25"))

# --- Dashboard / weather --------------------------------------------------
# Weather needs no API key (Open-Meteo). Location is auto-detected from your IP;
# override it here if that's wrong. Units: "metric" (°C, km/h) or "imperial".
WEATHER_LAT = os.getenv("NOVA_LAT", "")
WEATHER_LON = os.getenv("NOVA_LON", "")
WEATHER_CITY = os.getenv("NOVA_CITY", "")
UNITS = os.getenv("NOVA_UNITS", "metric").lower()

# --- Shopify (optional, read-only) ----------------------------------------
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "")            # yourstore.myshopify.com
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")            # legacy static Admin API token, shpat_...
# New Dev Dashboard apps: Nova exchanges Client ID + Secret for a 24h token.
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2026-01")

# --- Google Calendar (read-only, via the calendar's private iCal URL) ------
# In Google Calendar: Settings > Settings for my calendars > [your calendar] >
# "Secret address in iCal format" > copy the link here. No sign-in flow needed.
GOOGLE_CALENDAR_ICS = os.getenv("GOOGLE_CALENDAR_ICS", "")

# --- YouTube (public channel stats via Data API v3) ------------------------
# Needs a free API key (Google Cloud > APIs > YouTube Data API v3 > API key)
# and your channel handle (e.g. @mychannel) or channel ID (UC...).
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL = os.getenv("YOUTUBE_CHANNEL", "")

# --- Daily briefing -------------------------------------------------------
# Time (24-hour HH:MM) Nova speaks the daily briefing while it's running.
# Blank = off. Change it by voice ("brief me at 7:30") or here; the live value
# is stored in nova_briefing.json once set by voice.
BRIEFING_TIME = os.getenv("NOVA_BRIEFING_TIME", "08:00")

# --- Messaging (optional): post to Telegram + Discord ---------------------
# Telegram: create a bot with @BotFather → token; TELEGRAM_CHAT_ID is your
# channel (@name) or numeric chat id. Discord: a channel webhook URL.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# Discord: a bot token + server (guild) id gives access to the WHOLE server (post
# to any channel). DISCORD_WEBHOOK_URL is a simpler single-channel fallback.
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")
DISCORD_DEFAULT_CHANNEL = os.getenv("DISCORD_DEFAULT_CHANNEL", "general")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# --- Outlook / Microsoft 365 email (Microsoft Graph) ----------------------
# From an Azure app registration: Application (client) ID + Directory (tenant) ID.
# Nova signs in once via device code; the token is cached in outlook_token.json.
OUTLOOK_CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID", "")
OUTLOOK_TENANT_ID = os.getenv("OUTLOOK_TENANT_ID", "common")

# --- Audio (internal) -----------------------------------------------------
SAMPLE_RATE = 16000
