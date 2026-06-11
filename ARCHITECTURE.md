# Architecture

How Nova fits together — the data flow, the modules, the concurrency model, and the security
design. For setup see the [README](README.md); for a friendly walkthrough see
[docs/GUIDE.md](docs/GUIDE.md).

## The big picture

Nova is a local **FastAPI** server plus a native **WebView2** desktop window. The server owns
the microphone and the AI; the window is a thin web UI (the "HUD") that talks to the server
over a WebSocket and speaks replies with a neural voice. Everything runs on your PC except the
calls to Claude (and the free weather/voice lookups).

```
                          ┌─────────────────────── your PC ──────────────────────┐
  🎤 mic                  │                                                        │
   │                      │   vad.py            server.py            brain.py       │
   ▼                      │  ┌───────┐   speech ┌──────────┐  text  ┌──────────┐    │
 sounddevice ── frames ──►│  │Silero │ ──────► │ faster-  │ ────► │  Claude  │    │
                          │  │  VAD  │          │ whisper  │        │ tool loop│    │
                          │  └───────┘          │  (STT)   │        └────┬─────┘    │
                          │                     └──────────┘             │ tools    │
                          │   reply text                                 ▼          │
  🔊 speaker ◄── edge-tts │ ◄──────────────────────────── tools.py + ...  │
                          │                                         (open apps,     │
                          │   ┌──────────────┐   WebSocket /ws      vision, memory, │
   🖥️ HUD window ◄────────┼──►│ FastAPI app  │◄───────────────  tasks, web…    │
   (static/index.html     │   │ (server.py)  │   HTTP /api/*                        │
    in WebView2)          │   └──────────────┘                                      │
                          └────────────────────────────────────────────┘
```

## Entry points

| File | Role |
|---|---|
| `launch_nova.pyw` | The normal launcher. Kills any previous instance, starts the server in a background thread, and opens the HUD in a native WebView2 window. Run with `pythonw` (no console). |
| `nova.py` | A minimal **console** version (hold the push-to-talk key, speak, release). Also provides `resolve_input_device()`, the mic picker reused by the server. |
| `server.py` | The engine + web server (imported by the launcher). Can also be run directly with `uvicorn`. |

## The voice loop (lifecycle of one utterance)

The `Engine` class in `server.py` runs in its own worker thread:

1. **Capture** — `sounddevice` streams 16 kHz mono audio in 0.1 s blocks to the `_cb` callback,
   which keeps a short pre-roll buffer (so the first word isn't clipped).
2. **Detect speech** — a separate thread (`_vad_loop`) runs **Silero VAD** (`vad.py`) on each
   chunk. In always-listening mode, ~4 consecutive speech windows start an utterance; a tap
   (the orb / 🎤) starts one on demand.
3. **Record until silence** — capture continues until ~1.1 s of no speech (or a 14 s cap), then
   requires a minimum of real speech so stray noises are ignored.
4. **Speaker check** *(hands-free mode only)* — `voiceid.py` (SpeechBrain ECAPA) compares the
   clip to your enrolled voiceprint; non-matching voices are ignored.
5. **Transcribe** — **faster-whisper** runs locally on CPU and returns text.
6. **Think** — the text is appended to the conversation and handed to `brain.respond()`.
7. **Speak** — the reply is synthesized by **edge-tts** (neural, online) with an automatic
   fallback to Windows **SAPI** offline. Audio captured while speaking is discarded so the
   voice can't trigger itself.

Typed input (the "Type to Nova" bar) takes the same path from step 6, skipping mic/STT/voice-ID.

## The brain & tool-use loop (`brain.py`)

`respond(messages, tool_list)` runs an **agentic loop** against the Claude Messages API:

- Build the system prompt fresh each turn (date/time + long-term memory injected).
- Call the model. Then branch on `stop_reason`:
  - **`tool_use`** → run each requested tool via `tools.dispatch(...)`, append the results as a
    `tool_result`, and loop again.
  - **`pause_turn`** → a server-side tool (web search) paused; re-send to continue (capped).
  - **`end_turn`** → return the spoken text.
- **Resilience:** history is trimmed to a bounded window, old screenshots are pruned so images
  aren't re-uploaded every turn, and orphaned `tool_use`/`tool_result` blocks are sanitized so a
  single broken turn can't wedge every future request. Out-of-credit errors return a friendly
  spoken message.

## Tools (the capability system)

Each capability module exposes the same trio, so adding a tool is self-contained:

- `TOOLS` — the JSON schemas Claude sees.
- `NAMES` — the set of tool names the module handles.
- `dispatch(name, input)` — runs the tool and returns text (or, for vision, text + image blocks).

`tools.py` is the central dispatcher: it routes each call to the right module
(`memory`, `tasks`, `gcal`, `youtube`, `briefing`, `files`, `messaging`, `outlook`, `vision`,
`shopify_tools`) or to its own PC-control tools (`open_application`, `open_path`,
`run_powershell`, `show_dashboard`). Web search is a **server-side** Anthropic tool — no local
code. `run_powershell` and outbound posts (Telegram/Discord/email) are routed through a
**confirmation hook** (`confirm_fn`) so nothing risky runs without an on-screen **Allow / Deny**.
(`brain.SAFE_TOOLS` is a variant of the tool set with `run_powershell` removed entirely.)

## The HUD & its WebSocket protocol

`static/index.html` is pure HTML + CSS + canvas (no CDN, no framework). It connects to `/ws`
and renders state in real time.

**Server → HUD messages:** `state` (idle/listening/thinking/speaking/enroll), `you` / `nova`
(transcript lines), `level` (mic level for the orb), `mode` (always-listening on/off),
`voiceid` (enrolled?), `enroll` (training progress), `confirm` (the Allow/Deny prompt for a
shell command), `view` (switch dashboard/hologram), `activity` (which tool is running), `error`.

**HUD → server commands:** `talk`, `text`, `mode`, `enroll`, `confirm`.

HTTP routes serve the page and JSON for the dashboard: `/api/dashboard`, `/api/system`,
`/api/tasks/{action}`.

## Concurrency model

- **Engine thread** — the mic → STT → Claude → TTS loop (blocking work, off the event loop).
- **VAD thread** — runs Silero on incoming audio so the real-time audio callback stays light.
- **asyncio tasks** in the FastAPI app: `_drain` (pumps the thread-safe `outbox` queue out to
  WebSocket clients), `_levels` (mic level for the orb), `_watchdog` (quits the hidden server
  shortly after the window closes), and `_briefing_scheduler` (fires the daily briefing).

The worker thread and the async world communicate through a single thread-safe `queue.Queue`
(`outbox`), which `_drain` forwards to every connected client.

## Security model (`auth.py` + `server.py`)

Because Nova can run PC commands, network exposure is locked down:

- **Local window is trusted** — requests from `127.0.0.1` (loopback) never see a login.
- **Off by default** — with no `NOVA_ACCESS_PASSWORD`, the server binds to `127.0.0.1` only, so
  nothing off-PC can reach it. Setting a password switches the bind to `0.0.0.0` (reachable over
  your LAN / Tailscale) and turns on the login gate.
- **Login** — other devices must enter the password once; the session cookie is a **one-way
  hash** of the password (no secret stored), `HttpOnly`, and checked in **constant time**.
  Changing the password instantly invalidates every device. Failed logins are **rate-limited**
  per IP.
- **Command gate** — `run_powershell` and outbound messages require on-screen **Allow / Deny**.
- **Bring your own keys** — secrets live only in your local `.env` (git-ignored, never committed).

## Local state & privacy

All of these are created at runtime, stay on your PC, and are git-ignored:

| File / dir | What |
|---|---|
| `.env` | Your keys and settings |
| `nova_memory.json` | Long-term memory |
| `nova_tasks.json` | To-do list |
| `nova_briefing.json` | Daily-briefing schedule |
| `nova_location.json` | Cached weather location |
| `voiceprint.npy` | Your enrolled speaker embedding |
| `models/` | Downloaded STT / speaker models |
| `.webview/` | WebView2 profile data |
| `*.log`, `nova.pid` | Logs and the single-instance lock |

## Notable design decisions

- **Local speech-to-text** keeps your audio on-device — only the resulting text (and any image
  you ask Nova to look at) goes to Claude.
- **Heavy imports are lazy** (Whisper, SpeechBrain, Pillow, PyMuPDF, OpenCV) so `import` never
  fails and startup stays fast; a missing optional dependency degrades to a friendly message
  rather than a crash.
- **Graceful optionals** — every integration checks for its key and simply stays off if absent,
  so the app always runs with just `ANTHROPIC_API_KEY`.
- **The icon is generated** (`make_icon.py`) on first launch rather than committed as a binary.
