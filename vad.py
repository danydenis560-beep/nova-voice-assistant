"""Neural speech detection (Silero VAD).

Tells speech from non-speech far more reliably than a loudness check, so
breaths, clicks, and background noise don't trigger Nova. Runs locally on
CPU. Feed 512-sample, 16 kHz chunks to prob() to get a speech probability."""
import numpy as np

WINDOW = 512  # required chunk size for 16 kHz audio (Silero v5)
_model = None


def _get_model():
    global _model
    if _model is None:
        from silero_vad import load_silero_vad
        _model = load_silero_vad()
    return _model


def warm():
    _get_model()


def reset():
    try:
        _get_model().reset_states()
    except Exception:
        pass


def prob(window):
    """Speech probability in [0, 1] for one 512-sample, 16 kHz chunk."""
    import torch
    m = _get_model()
    t = torch.from_numpy(np.asarray(window, dtype=np.float32).reshape(-1))
    with torch.no_grad():
        return float(m(t, 16000).item())
