"""Nova — a voice assistant for your Windows PC.

Hold the push-to-talk key, speak, release. Whisper transcribes you locally,
Claude decides what to do (open apps, files, URLs, run commands, search the
web), and it talks back. Ctrl+C to quit.
"""
import queue
import sys

import keyboard
import numpy as np
import sounddevice as sd
import pyttsx3
from faster_whisper import WhisperModel

import brain
import config


def speak(engine, text: str) -> None:
    print(f"Nova: {text}")
    engine.say(text)
    engine.runAndWait()


def resolve_input_device():
    """Pick which mic to record from. Returns (device_index_or_None, name).

    Honors config.INPUT_DEVICE (a name fragment or a number); otherwise auto-
    picks a real microphone, skipping virtual cables like VB-Audio.
    """
    pref = config.INPUT_DEVICE.strip()
    devices = sd.query_devices()
    inputs = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]

    if pref:
        if pref.isdigit():
            idx = int(pref)
            try:
                return idx, sd.query_devices(idx)["name"]
            except Exception:  # noqa: BLE001
                print(f"[warn] mic #{idx} not found; auto-detecting instead.")
        else:
            for i, d in inputs:
                if pref.lower() in d["name"].lower():
                    return i, d["name"]
            print(f"[warn] mic '{pref}' not found; auto-detecting instead.")

    skip = ("cable", "vb-audio", "virtual", "stereo mix", "sound mapper",
            "primary sound", "mapper")
    real = [(i, d) for i, d in inputs
            if not any(s in d["name"].lower() for s in skip)]
    for i, d in real:                       # prefer something actually named "microphone"
        if "microphone" in d["name"].lower():
            return i, d["name"]
    if real:
        i, d = real[0]
        return i, d["name"]
    return None, "system default"


def record_while_held(key: str, device):
    """Capture mic audio for as long as `key` is held down. Returns float32 mono."""
    frames = []
    q: queue.Queue = queue.Queue()

    def callback(indata, _frames, _time, _status):
        q.put(indata.copy())

    keyboard.wait(key)  # block until the key is pressed
    with sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1,
                        dtype="float32", callback=callback, device=device):
        while keyboard.is_pressed(key):
            try:
                frames.append(q.get(timeout=0.1))
            except queue.Empty:
                pass
        while not q.empty():
            frames.append(q.get())

    if not frames:
        return None
    return np.concatenate(frames, axis=0).flatten()


def main() -> None:
    if not config.ANTHROPIC_API_KEY:
        print("ERROR: No ANTHROPIC_API_KEY found.")
        print("Create a file called .env next to this script containing:")
        print("    ANTHROPIC_API_KEY=sk-ant-...")
        print("(get a key at https://console.anthropic.com -> API Keys)")
        sys.exit(1)

    print("Starting Nova...")
    print(f"  brain   : {config.MODEL}")
    print(f"  hearing : Whisper '{config.WHISPER_MODEL}' "
          "(first run downloads the model, ~150 MB)")
    stt = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")

    mic_index, mic_name = resolve_input_device()
    print(f"  mic     : {mic_name}")

    engine = pyttsx3.init()
    engine.setProperty("rate", config.TTS_RATE)
    if config.TTS_VOICE:
        for v in engine.getProperty("voices"):
            if config.TTS_VOICE.lower() in v.name.lower():
                engine.setProperty("voice", v.id)
                break

    messages: list = []
    key = config.PUSH_TO_TALK_KEY.upper()
    print(f"\nNova is ready. Hold [{key}] and speak, release to send. "
          "Ctrl+C to quit.\n")
    speak(engine, "Nova online. Hold the talk key and tell me what you need.")

    while True:
        try:
            print(f"(hold {key} to talk)")
            audio = record_while_held(config.PUSH_TO_TALK_KEY, mic_index)
            if audio is None or len(audio) < config.SAMPLE_RATE * 0.3:
                continue  # too short to be speech
            segments, _ = stt.transcribe(audio, language="en")
            text = " ".join(s.text for s in segments).strip()
            if not text:
                continue
            print(f"You: {text}")
            print("(thinking...)")
            messages.append({"role": "user", "content": text})
            speak(engine, brain.respond(messages))
        except KeyboardInterrupt:
            print("\nShutting down. Bye.")
            break
        except Exception as e:  # noqa: BLE001  (keep the loop alive on any error)
            print(f"[error] {e}")
            try:
                speak(engine, "Sorry, something went wrong.")
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    main()
