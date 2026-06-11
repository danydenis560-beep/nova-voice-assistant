"""Nova HUD backend.

Owns the microphone, transcribes speech locally with Whisper, thinks with
Claude (brain.py / tools.py), and pushes live state to the glowing web UI over
a websocket. The browser renders the HUD and speaks replies in its own voice.
Launched (no console) by launch_nova.pyw.
"""
import asyncio
import collections
import itertools
import os
import queue
import subprocess
import threading
import time
import traceback
from pathlib import Path

import numpy as np
import sounddevice as sd
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import auth
import brain
import briefing
import config
import dashboard
import nova  # resolve_input_device (skips virtual cables)
import system_stats
import tasks
import tools
import vad
import voiceid

BASE = Path(__file__).resolve().parent
PORT = 8765
SAMPLE_RATE = 16000
BLOCK = 1600          # 0.1s audio frames
# Speech detection via Silero neural VAD (vad.py).
VAD_PROB = 0.5         # Silero probability above this counts as speech
START_BLOCKS = 4       # ~4 VAD windows (~0.13s) of speech to start (ignores blips)
ONSET_WAIT = 4.0       # after a tap, wait up to this long for speech to begin
SILENCE_HANG = 1.1     # seconds of no-speech that ends an utterance
MAX_UTTER = 14.0
MIN_SPEECH = 0.3       # need this many seconds of real speech to respond


def log(msg):
    try:
        with open(BASE / "nova_hud.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


_whisper = None
def whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(config.WHISPER_MODEL, device="cpu",
                                compute_type="int8")
    return _whisper


class Engine:
    """Runs in a worker thread: mic -> VAD -> Whisper -> Claude -> UI."""

    def __init__(self, outbox):
        self.outbox = outbox
        self.level = 0.0
        self.is_speech = False
        self.speech_prob = 0.0
        self._vad_q = queue.Queue()
        self._above = 0
        self._preroll = collections.deque(maxlen=8)  # ~0.8s lead-in buffer
        self.mode_always = False
        self.speaking = False
        self._speak_until = 0.0
        self.talk_request = False
        self.briefing_request = False
        self.text_request = None
        self._frames = []
        self._capturing = False
        self._lock = threading.Lock()
        self.messages = []
        self._tts = None
        self.enroll_request = False
        self.voiceprint = voiceid.load_voiceprint()
        self.device, self.device_name = nova.resolve_input_device()

    def send(self, **msg):
        self.outbox.put(msg)

    def _cb(self, indata, frames, time_info, status):
        x = indata[:, 0].copy()
        self.level = float(np.sqrt(np.mean(x ** 2)) + 1e-9)  # for the orb only
        if self._capturing:
            with self._lock:
                self._frames.append(x)
        elif not self.speaking:
            self._preroll.append(x)
        self._vad_q.put(x)  # neural speech detection happens in _vad_loop

    def _vad_loop(self):
        """Off the audio callback: pull mic chunks, run Silero VAD, and update
        the is_speech flag. Keeps the real-time audio thread light."""
        try:
            vad.warm()
        except Exception:
            log("vad warm failed: " + traceback.format_exc())
        buf = np.zeros(0, dtype=np.float32)
        while True:
            try:
                chunk = self._vad_q.get(timeout=0.5)
            except queue.Empty:
                continue
            buf = np.concatenate((buf, chunk))
            while len(buf) >= vad.WINDOW:
                win = buf[:vad.WINDOW]
                buf = buf[vad.WINDOW:]
                try:
                    p = vad.prob(win)
                except Exception:
                    p = 0.0
                self.speech_prob = p
                self.is_speech = p > VAD_PROB
                if not self._capturing and not self.speaking:
                    self._above = self._above + 1 if self.is_speech else 0

    def run(self):
        log(f"engine on device [{self.device}] {self.device_name}")
        threading.Thread(target=self._vad_loop, daemon=True).start()
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                dtype="float32", blocksize=BLOCK,
                                device=self.device, callback=self._cb):
                self.send(type="state", state="idle")
                while True:
                    now = time.time()
                    if self.speaking:
                        if now >= self._speak_until:
                            self.speaking = False
                            self.send(type="state",
                                      state="listening" if self.mode_always else "idle")
                        else:
                            time.sleep(0.05)
                        continue
                    if self.enroll_request:
                        self.enroll_request = False
                        self._enroll()
                    elif self.talk_request:
                        self.talk_request = False
                        self._utterance()
                    elif self.briefing_request:
                        self.briefing_request = False
                        self._briefing()
                    elif self.text_request is not None:
                        t = self.text_request
                        self.text_request = None
                        self._text_input(t)
                    elif self.mode_always and self._above >= START_BLOCKS:
                        self._above = 0
                        self._utterance()
                    else:
                        time.sleep(0.03)
        except Exception as e:
            log("ENGINE CRASH: " + traceback.format_exc())
            self.send(type="error", text=f"Microphone error: {e}")

    def _utterance(self):
        idle = "listening" if self.mode_always else "idle"
        with self._lock:
            self._frames = list(self._preroll)  # include the lead-in so the
            self._capturing = True              # first word isn't clipped
        self.send(type="state", state="listening")
        # 1) Wait for real speech to begin (so a tap-then-pause or a breath
        #    doesn't get sent off to "thinking").
        t0 = time.time()
        onset = None
        while onset is None:
            time.sleep(0.03)
            if self.is_speech:
                onset = time.time()
            elif time.time() - t0 > ONSET_WAIT:
                with self._lock:
                    self._capturing = False
                    self._frames = []
                self.send(type="state", state=idle)
                return
        # 2) Keep capturing until speech stops for SILENCE_HANG.
        last_voice = time.time()
        while True:
            time.sleep(0.04)
            now = time.time()
            if self.is_speech:
                last_voice = now
            if now - onset > MAX_UTTER:
                break
            if now - last_voice > SILENCE_HANG:
                break
        with self._lock:
            self._capturing = False
            frames = list(self._frames)
            self._frames = []
        audio = np.concatenate(frames) if frames else np.zeros(0, dtype="float32")
        # 3) Require enough real speech (drops stray short noises).
        if (last_voice - onset) < MIN_SPEECH:
            log(f"skipped non-speech (speech {last_voice - onset:.2f}s)")
            self.send(type="state", state=idle)
            return
        # Hands-free mode: only respond to the enrolled voice.
        if self.mode_always and self.voiceprint is not None:
            try:
                ok, sim = voiceid.verify(audio, self.voiceprint, config.VOICE_THRESHOLD)
            except Exception:
                log("voiceid error: " + traceback.format_exc())
                ok, sim = True, 1.0
            if not ok:
                log(f"ignored other voice (score {sim:.2f})")
                self.send(type="state", state="listening")
                return
            log(f"voice accepted (score {sim:.2f})")
        self.send(type="state", state="thinking")
        try:
            segs, _ = whisper().transcribe(audio, language=config.LANGUAGE or None)
            text = " ".join(s.text for s in segs).strip()
        except Exception:
            log("STT error: " + traceback.format_exc())
            self.send(type="state", state="idle")
            return
        if not text:
            self.send(type="state", state="idle")
            return
        self.send(type="you", text=text)
        try:
            self.messages.append({"role": "user", "content": text})
            reply = brain.respond(self.messages, brain.ALL_TOOLS)
        except Exception:
            log("BRAIN error: " + traceback.format_exc())
            reply = "Sorry, I hit an error."
        self.send(type="nova", text=reply)
        self.send(type="state", state="speaking")
        self.speaking = True
        self._say(reply)
        time.sleep(0.3)  # let the speaker tail fade
        # drop everything captured while speaking so the TTS tail can't trigger
        try:
            while True:
                self._vad_q.get_nowait()
        except queue.Empty:
            pass
        self.is_speech = False
        self._above = 0
        self._preroll.clear()
        self.speaking = False
        self.send(type="state", state="listening" if self.mode_always else "idle")

    def _text_input(self, text):
        """Handle a typed request: run it through the brain and reply by voice +
        transcript, exactly like a spoken utterance (just no mic/STT/voice-ID)."""
        idle = "listening" if self.mode_always else "idle"
        text = (text or "").strip()
        if not text:
            return
        self.send(type="you", text=text)
        self.send(type="state", state="thinking")
        try:
            self.messages.append({"role": "user", "content": text})
            reply = brain.respond(self.messages, brain.ALL_TOOLS)
        except Exception:
            log("BRAIN error: " + traceback.format_exc())
            reply = "Sorry, I hit an error."
        self.send(type="nova", text=reply)
        self.send(type="state", state="speaking")
        self.speaking = True
        self._say(reply)
        time.sleep(0.3)
        try:
            while True:
                self._vad_q.get_nowait()
        except queue.Empty:
            pass
        self.is_speech = False
        self._above = 0
        self._preroll.clear()
        self.speaking = False
        self.send(type="state", state=idle)

    def _briefing(self):
        """Compose and speak the daily briefing (scheduled path). Runs in the
        engine thread so SAPI TTS works, like a normal reply."""
        idle = "listening" if self.mode_always else "idle"
        self.send(type="state", state="thinking")
        try:
            text = briefing.compose()
        except Exception:
            log("briefing error: " + traceback.format_exc())
            text = "I couldn't put your briefing together right now."
        self.send(type="nova", text=text)
        self.send(type="state", state="speaking")
        self.speaking = True
        self._say(text)
        time.sleep(0.3)
        try:  # drop audio captured while speaking so the TTS tail can't self-trigger
            while True:
                self._vad_q.get_nowait()
        except queue.Empty:
            pass
        self.is_speech = False
        self._above = 0
        self._preroll.clear()
        self.speaking = False
        self.send(type="state", state=idle)

    def _enroll(self):
        secs = 15
        self.send(type="state", state="enroll")
        with self._lock:
            self._frames = []
            self._capturing = True
        t0 = time.time()
        while time.time() - t0 < secs:
            left = int(secs - (time.time() - t0)) + 1
            self.send(type="enroll", phase="record", secs=left)
            time.sleep(0.5)
        with self._lock:
            self._capturing = False
            frames = list(self._frames)
            self._frames = []
        audio = np.concatenate(frames) if frames else np.zeros(0, dtype="float32")
        if len(audio) < SAMPLE_RATE * 4:
            self.send(type="enroll", phase="failed")
            self.send(type="state", state="idle")
            return
        self.send(type="enroll", phase="learning")
        try:
            self.voiceprint = voiceid.enroll(audio, SAMPLE_RATE)
            self.send(type="enrolled")
        except Exception:
            log("enroll error: " + traceback.format_exc())
            self.send(type="enroll", phase="failed")
        self.send(type="state", state="idle")

    def _say(self, text):
        """Speak a reply. Prefers free neural edge-tts voices (much more human);
        automatically falls back to Windows SAPI if edge-tts/network/ffmpeg fail."""
        if config.TTS_ENGINE == "edge":
            try:
                self._say_edge(text)
                return
            except Exception:
                log("edge-tts failed; using SAPI fallback: " + traceback.format_exc())
        self._say_sapi(text)

    def _say_edge(self, text):
        """Microsoft edge-tts neural voice (online, free): synthesize -> decode with
        ffmpeg -> play via sounddevice. British male voice by default (Nova-like)."""
        import asyncio
        import tempfile
        import edge_tts
        voice = (config.TTS_EDGE_VOICE_FR if ((self._is_french(text) or self._is_creole(text))
                 and config.TTS_EDGE_VOICE_FR) else config.TTS_EDGE_VOICE)
        mp3 = os.path.join(tempfile.gettempdir(), f"nova_tts_{int(time.time() * 1000)}.mp3")

        async def _gen():
            kw = {"rate": config.TTS_EDGE_RATE} if config.TTS_EDGE_RATE else {}
            await asyncio.wait_for(edge_tts.Communicate(text, voice, **kw).save(mp3), timeout=15)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_gen())
        finally:
            loop.close()
        try:
            r = subprocess.run(
                ["ffmpeg", "-v", "quiet", "-i", mp3, "-f", "s16le", "-ar", "24000", "-ac", "1", "-"],
                capture_output=True, timeout=30,
            )
        finally:
            try:
                os.remove(mp3)
            except Exception:
                pass
        if r.returncode != 0 or not r.stdout:
            raise RuntimeError("ffmpeg decode failed")
        pcm = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(pcm, 24000)
        sd.wait()

    def _say_sapi(self, text):
        """Speak via Windows SAPI directly (offline fallback; reliable for repeated
        calls unlike pyttsx3). Auto-picks an English/French voice. Runs in this thread."""
        try:
            if self._tts is None:
                import pythoncom
                pythoncom.CoInitialize()
                import win32com.client
                self._tts = win32com.client.Dispatch("SAPI.SpVoice")
                self._voices = self._tts.GetVoices()
                self._voice_en = self._sapi_voice("english", config.TTS_VOICE)
                self._voice_fr = self._sapi_voice("french", "")
                self._tts.Rate = max(-10, min(10, int((config.TTS_RATE - 200) / 12)))
            token = self._voice_fr if ((self._is_french(text) or self._is_creole(text)) and self._voice_fr) else self._voice_en
            if token is not None:
                self._tts.Voice = token
            self._tts.Speak(text)
        except Exception:
            log("tts error: " + traceback.format_exc())

    def _sapi_voice(self, name_kw, prefer_name):
        try:
            voices = self._voices
            if prefer_name:
                for i in range(voices.Count):
                    v = voices.Item(i)
                    if prefer_name.lower() in v.GetDescription().lower():
                        return v
            for i in range(voices.Count):
                v = voices.Item(i)
                if name_kw in v.GetDescription().lower():
                    return v
        except Exception:
            pass
        return None

    @staticmethod
    def _is_french(text):
        t = text.lower()
        if any(c in t for c in "àâçéèêëîïôûùü"):
            return True
        words = (" le ", " la ", " les ", " est ", " vous ", " bonjour ", " merci ",
                 " oui ", " votre ", " une ", " je ", " avec ", " pour ", " pas ",
                 " bien ", " jour ")
        return sum(1 for w in words if w in f" {t} ") >= 2

    @staticmethod
    def _is_creole(text):
        # Haitian Creole — spoken with the French voice (no native Creole voice).
        t = f" {text.lower()} "
        words = (" mwen ", " ou ", " li ", " nou ", " yo ", " kijan ", " kisa ",
                 " konsa ", " kounye ", " anpil ", " bagay ", " mèsi ", " bonjou ",
                 " jodi ", " genyen ", " fè ", " vle ", " jwenn ", " tout ", " ki ",
                 " sa ", " eksperyans ", " lajan ", " kòman ", " pale ")
        return sum(1 for w in words if w in t) >= 2


app = FastAPI()
outbox = queue.Queue()
engine = Engine(outbox)
clients = set()
_meta = {"ever": False, "last": time.time()}
_tasks = []


# --- shell command confirmation (the HUD "Allow?" button) -----------------
_pending = {}
_pending_lock = threading.Lock()
_confirm_seq = itertools.count(1)


def hud_confirm(command):
    """Ask the UI to approve a shell command; block until it answers (or 90s)."""
    cid = next(_confirm_seq)
    ev = threading.Event()
    with _pending_lock:
        _pending[cid] = {"event": ev, "result": False}
    outbox.put({"type": "confirm", "id": cid, "command": command})
    ev.wait(timeout=90)
    with _pending_lock:
        rec = _pending.pop(cid, {"result": False})
    return bool(rec["result"])


tools.confirm_fn = hud_confirm
# Posting to Telegram/Discord asks for on-screen Allow/Deny first (so a misheard
# command can't auto-post to a public channel).
import messaging  # noqa: E402
import outlook  # noqa: E402
messaging.confirm_fn = hud_confirm
outlook.confirm_fn = hud_confirm  # sending email asks Allow/Deny first
# Let the show_dashboard tool switch the HUD's on-screen view by voice.
tools.view_fn = lambda view: outbox.put({"type": "view", "view": view})
# Show the user which tool Nova is using, live.
tools.activity_fn = lambda name: outbox.put({"type": "activity", "tool": name})


@app.on_event("startup")
async def _startup():
    threading.Thread(target=engine.run, daemon=True).start()
    if engine.voiceprint is not None:  # warm voice-ID so first reply isn't slow
        threading.Thread(target=voiceid.warm, daemon=True).start()
    _tasks.append(asyncio.create_task(_drain()))
    _tasks.append(asyncio.create_task(_levels()))
    _tasks.append(asyncio.create_task(_watchdog()))
    _tasks.append(asyncio.create_task(_briefing_scheduler()))


async def _drain():
    while True:
        try:
            msg = outbox.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.02)
            continue
        for ws in list(clients):
            try:
                await ws.send_json(msg)
            except Exception:
                clients.discard(ws)


async def _levels():
    while True:
        await asyncio.sleep(0.06)
        if clients:
            v = min(1.0, engine.level * 6.0)
            for ws in list(clients):
                try:
                    await ws.send_json({"type": "level", "v": round(v, 3)})
                except Exception:
                    clients.discard(ws)


async def _watchdog():
    # Quit the (hidden) server shortly after the window is closed.
    while True:
        await asyncio.sleep(1.0)
        if clients:
            _meta["last"] = time.time()
        elif _meta["ever"] and time.time() - _meta["last"] > 5:
            log("no clients connected; shutting down")
            os._exit(0)


async def _briefing_scheduler():
    # Once a day at the configured time (while Nova is running), speak the briefing.
    while True:
        await asyncio.sleep(20)
        try:
            if briefing.due():
                log("daily briefing due — speaking")
                engine.briefing_request = True
        except Exception:
            log("briefing scheduler: " + traceback.format_exc())


# --- Remote-access auth gate ----------------------------------------------
# This PC's own window connects over 127.0.0.1 and is always trusted (never sees
# a login). Any other device (your phone) must log in once with ACCESS_PASSWORD,
# which stores a cookie. With no password set, only this PC can reach Nova.
_OPEN_PATHS = {"/login", "/favicon.ico", "/manifest.webmanifest"}


def _authed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if auth.is_local(host):
        return True
    return auth.check_token(request.cookies.get("nova_auth"))


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    if request.url.path in _OPEN_PATHS or _authed(request):
        return await call_next(request)
    if request.url.path.startswith("/api"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return RedirectResponse("/login")


@app.get("/login")
async def login_get(request: Request):
    if _authed(request):
        return RedirectResponse("/")
    return HTMLResponse((BASE / "static" / "login.html").read_text(encoding="utf-8"))


# Brute-force protection: cap failed logins per device IP so a short password
# can't be guessed by hammering. (The trusted local window never logs in, so
# this never affects your own PC.)
_login_fails = {}            # ip -> [timestamps of recent failures]
_LOGIN_MAX = 8               # this many failures...
_LOGIN_WINDOW = 300          # ...within this many seconds locks the IP out


def _login_blocked(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _login_fails.get(ip, []) if now - t < _LOGIN_WINDOW]
    _login_fails[ip] = hits
    return len(hits) >= _LOGIN_MAX


@app.post("/login")
async def login_post(request: Request):
    ip = request.client.host if request.client else ""
    if _login_blocked(ip):
        return JSONResponse(
            {"ok": False, "error": "Too many attempts — wait a few minutes."},
            status_code=429)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if auth.check_password(body.get("password", "")):
        _login_fails.pop(ip, None)  # clear the slate on success
        resp = JSONResponse({"ok": True})
        # One-year cookie; HttpOnly so page scripts can't read it. Survives
        # restarts (token is derived from the password).
        resp.set_cookie("nova_auth", auth.token_for(), max_age=31536000,
                        httponly=True, samesite="lax")
        return resp
    _login_fails.setdefault(ip, []).append(time.time())
    return JSONResponse({"ok": False}, status_code=401)


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login")
    resp.delete_cookie("nova_auth")
    return resp


@app.get("/")
async def index():
    return HTMLResponse((BASE / "static" / "index.html").read_text(encoding="utf-8"))


@app.get("/api/dashboard")
async def api_dashboard():
    # snapshot() may do a (cached) network call for weather — keep it off the loop.
    return JSONResponse(await asyncio.to_thread(dashboard.snapshot))


@app.get("/api/system")
async def api_system():
    # ram/battery are instant; ping does a quick socket connect (cached ~3s).
    return JSONResponse(await asyncio.to_thread(system_stats.info))


@app.post("/api/tasks/{action}")
async def api_tasks(action: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    if action == "add":
        tasks.add_task(body.get("text", ""), body.get("due", ""))
    elif action == "complete":
        tasks.complete_task(body.get("task", ""))
    elif action == "delete":
        tasks.delete_task(body.get("task", ""))
    elif action == "clear":
        tasks.clear_done()
    return JSONResponse(await asyncio.to_thread(dashboard.snapshot))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    # Same gate as the HTTP routes: this PC is trusted; other devices need the
    # cookie token (sent automatically by the browser) or a ?token= fallback.
    host = ws.client.host if ws.client else ""
    if not (auth.is_local(host) or auth.check_token(
            ws.cookies.get("nova_auth") or ws.query_params.get("token"))):
        await ws.close(code=1008)  # policy violation
        return
    await ws.accept()
    clients.add(ws)
    _meta["ever"] = True
    await ws.send_json({"type": "mode", "always": engine.mode_always})
    await ws.send_json({"type": "voiceid", "enrolled": engine.voiceprint is not None})
    await ws.send_json({"type": "state", "state": "idle"})
    try:
        while True:
            data = await ws.receive_json()
            cmd = data.get("cmd")
            if cmd == "talk":
                engine.talk_request = True
            elif cmd == "text":
                engine.text_request = data.get("text", "")
            elif cmd == "mode":
                engine.mode_always = bool(data.get("always"))
                await ws.send_json({"type": "mode", "always": engine.mode_always})
            elif cmd == "enroll":
                engine.enroll_request = True
            elif cmd == "confirm":
                cid = data.get("id")
                with _pending_lock:
                    rec = _pending.get(cid)
                if rec:
                    rec["result"] = bool(data.get("allow"))
                    rec["event"].set()
    except WebSocketDisconnect:
        clients.discard(ws)
    except Exception:
        clients.discard(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=PORT, log_level="warning")
