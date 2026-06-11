# Roadmap

Where Nova is headed. This is a **living document and a starting point** — ideas here aren't
promises, and priorities will shift based on what people actually want. Have a suggestion?
[Open an issue](../../issues) or see [CONTRIBUTING.md](CONTRIBUTING.md).

## ✅ Shipped

The current release already does a lot:

- Hands-free voice in (local Whisper) and out (free neural edge-tts voices)
- Claude brain with a safe tool-use loop and live web search
- PC control — open apps / files / URLs, run commands behind an Allow/Deny gate
- Vision — read the screen, documents, PDFs, images (and the webcam, optionally)
- Long-term memory, a to-do list, and a live dashboard (weather, clock, system stats)
- Hands-free voice lock (answers only your enrolled voice)
- Phone access over LAN / Tailscale, password-gated
- Optional integrations: Google Calendar, YouTube, daily briefing, Telegram, Discord,
  Outlook email, Shopify
- Multilingual replies (English, French, Haitian Creole)

## 🔜 Near-term

Small, high-value polish:

- [ ] **Demo GIF** in the README (a short clip of a real conversation)
- [ ] **Wake word** ("Hey Nova") so you don't have to click or hold a key
- [ ] **One-click installer** (package with PyInstaller so non-developers skip the Python setup)
- [ ] **Tests + expanded CI** (beyond the current byte-compile check)
- [ ] A few more **voice/personality presets** out of the box

## 🧭 Exploring

Bigger ideas under consideration:

- [ ] **Cross-platform** support (macOS / Linux) — currently Windows-only
- [ ] **Local-LLM option** for a fully offline brain (privacy / zero-cost mode)
- [ ] A **plugin system** so new tools can be dropped in without editing the core
- [ ] **Persistent conversation history** across restarts
- [ ] More integrations (Spotify control, smart-home, Slack, Notion, …)
- [ ] **Multiple enrolled voices** (per-user memory and preferences)

## 🙅 Non-goals (on purpose)

To keep Nova trustworthy, some things we **don't** plan to do:

- No always-on cloud account, telemetry, or analytics
- No uploading your audio to a speech service (transcription stays local)
- No silent background recording — Nova listens only when you ask it to

## 🙋 Want to help?

Pick anything above (the unchecked boxes are great first issues), or bring your own idea.
Start with [CONTRIBUTING.md](CONTRIBUTING.md), open an issue to discuss, and send a pull request.
