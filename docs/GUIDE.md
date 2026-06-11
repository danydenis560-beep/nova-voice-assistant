# Build Your Own AI Assistant — The Beginner's Guide

This is the friendly, step-by-step guide to getting **Nova** running on your PC. You don't
need to understand the code: you copy a folder, install a couple of free things, paste in one
key, and double-click to start.

---

## 1. What you're about to build

By the end you'll have your own AI assistant — Nova — running on your PC. You speak; she
listens, thinks with real AI, and answers out loud. Nova can hold a conversation, think with a
top AI brain (Claude) and search the web, control your PC (open apps, files, and sites and run
tasks, asking permission first), see your screen / documents / PDFs / images, remember what
matters, keep your to-do list, show a live dashboard, and answer from your phone.

## 2. What you'll need

A Windows 10/11 PC, a microphone (a cheap headset is best), an internet connection, a Claude
(Anthropic) account with a little billing added (the only cost), and ~30–60 minutes for first
setup. Everything else — the voice, speech recognition, dashboard, weather — is free.

## 3. The honest cost

Only the AI brain (Claude) costs money: pay-as-you-go. Add ~$5 of credit; each request costs a
fraction of a cent to a few cents. Light personal use is often a few dollars a month. When the
credit runs out it simply stops until you top up. Everything else is **$0**.

## 4. Step 1 — Install Python (free)

Go to [python.org/downloads](https://www.python.org/downloads/), download **Python 3.12**, run
the installer, and — importantly — tick **"Add python.exe to PATH"**, then Install. Verify in
PowerShell:

```powershell
python --version
```

## 5. Step 2 — Get the files

Put the project folder somewhere simple (e.g. Documents). Open the folder, click the address
bar, type `powershell`, and press Enter to open a terminal already inside the folder.

## 6. Step 3 — Install the packages (free)

In that terminal:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # you'll see (.venv) appear
pip install -r requirements.txt
```

It downloads the brain connector, voice, and speech models — give it a few minutes. The first
launch also downloads the speech model once (then it's cached).

## 7. Step 4 — Get your Claude API key

At [console.anthropic.com](https://console.anthropic.com): sign up, add a little credit
(**Billing → Add credits**), then **API Keys → Create Key** → copy it (starts with `sk-ant-…`).
Copy `.env.example` to a new file named `.env`, open it in Notepad, and replace
`PASTE_YOUR_KEY_HERE` with your key. **Keep `.env` private — never share it.**

## 8. Step 5 — Launch

Double-click `launch_nova.pyw`. The glowing window opens. Tap the orb (or 🎤) and talk, or type
in the bottom bar. Try: *"what time is it?"*, *"open Notepad"*, *"what's the weather?"*,
*"add milk to my to-do list"*, *"take a screenshot and tell me what you see."* Make a desktop
shortcut for one-click launching.

## 9. Step 6 — Go hands-free

Open the side panel → **"Train my voice"** (talk for ~15s). Then click **START LISTENING** —
Nova listens continuously and answers only your voice. If it ever ignores you, set
`NOVA_VOICE_THRESHOLD=0.10` in `.env`.

## 10. Make Nova yours

Change the voice via `NOVA_TTS_EDGE_VOICE` in `.env` (e.g. `en-GB-RyanNeural`,
`en-US-AriaNeural`). Rename the assistant by replacing "Nova" / "N.O.V.A" in `brain.py`,
`static/index.html`, `static/login.html`, and `launch_nova.pyw`.

## 11. Optional superpowers (add-ons)

All optional, off until you add a key (in `.env`):

- **Weather** — already on, no key.
- **Google Calendar** — read-only iCal link.
- **YouTube stats** — free Data API key.
- **Daily briefing** — set `NOVA_BRIEFING_TIME`.
- **Telegram + Discord posting** — bot tokens.
- **Outlook email** — a Microsoft app registration.
- **Shopify** — store credentials.

If a key is missing, that feature simply stays off.

## 12. Control Nova from your phone

Add `NOVA_ACCESS_PASSWORD=…` to `.env` and relaunch (your PC window never needs it). Test on
the same Wi-Fi: find your PC's IP (`ipconfig` → IPv4), then on your phone open
`http://YOUR-PC-IP:8765` and enter the password. For anywhere (cellular too), install
[Tailscale](https://tailscale.com) on the PC and phone (same account) and use the PC's `100.x`
address. Your PC must stay on with Nova open.

## 13. Troubleshooting

- **Won't start** → confirm "Add to PATH" and that you ran the pip install inside the activated
  venv; check `nova_hud.log`.
- **Mishears you** → use a headset, set `NOVA_WHISPER_MODEL=small`.
- **No voice** → needs internet (falls back to the Windows voice offline).
- **Phone can't load** → same Wi-Fi or Tailscale on; allow the Windows Firewall prompt the
  first time.

## 14. Safety & privacy

Nova asks before running anything risky (Allow / Deny). Your keys live only in your `.env` on
your PC — keep it private. The phone password is what stands between the internet and your PC —
make it strong.

## 15. Going further

Add a wake word, wire up more integrations, tweak the personality in `brain.py`, or restyle the
window in `static/index.html`.
