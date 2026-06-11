"""Speaker verification ("only my voice").

Learns the user's voiceprint once (enroll), then checks whether a captured
utterance is actually them. Uses SpeechBrain's ECAPA-TDNN embedding model,
runs locally on CPU. Embeddings are L2-normalized so a plain dot product is
cosine similarity (same speaker -> high, different -> low)."""
import numpy as np

import config

VOICEPRINT = config.BASE_DIR / "voiceprint.npy"
_model = None


def _get_model():
    global _model
    if _model is None:
        try:
            from speechbrain.inference import EncoderClassifier
        except Exception:  # older SpeechBrain
            from speechbrain.pretrained import EncoderClassifier
        kwargs = dict(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(config.BASE_DIR / "models" / "ecapa"),
            run_opts={"device": "cpu"},
        )
        # On Windows, SpeechBrain's default SYMLINK fetch needs admin / Developer
        # Mode. Copy the model files into the savedir instead so it works without
        # any special privileges.
        try:
            from speechbrain.utils.fetching import LocalStrategy
            _model = EncoderClassifier.from_hparams(
                local_strategy=LocalStrategy.COPY, **kwargs)
        except (ImportError, TypeError):
            _model = EncoderClassifier.from_hparams(**kwargs)
    return _model


def warm():
    """Pre-load the model (slow on first use)."""
    _get_model()


def _voiced(audio, floor=0.012, win=800):
    """Keep only the speech-energy parts (drop silence/pauses) so the embedding
    is about the voice, not the room. Falls back to the whole clip if nothing
    passes the floor."""
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    kept = [a[i:i + win] for i in range(0, max(0, len(a) - win + 1), win)
            if float(np.sqrt(np.mean(a[i:i + win] ** 2))) > floor]
    return np.concatenate(kept) if kept else a


def embed(audio):
    """16k mono float32 numpy -> normalized speaker embedding (silence removed)."""
    import torch
    a = _voiced(audio)
    wav = torch.from_numpy(np.asarray(a, dtype=np.float32).reshape(-1)).unsqueeze(0)
    with torch.no_grad():
        emb = _get_model().encode_batch(wav).reshape(-1).cpu().numpy()
    return emb / (np.linalg.norm(emb) + 1e-9)


def enroll(audio, sample_rate=16000):
    """Build + save a voiceprint from the user's actual speech (silence removed)."""
    vp = embed(audio)
    np.save(VOICEPRINT, vp)
    return vp


def load_voiceprint():
    if VOICEPRINT.exists():
        try:
            return np.load(VOICEPRINT)
        except Exception:
            return None
    return None


def score(audio, voiceprint):
    return float(np.dot(embed(audio), voiceprint))


def verify(audio, voiceprint, threshold):
    """Return (is_match, similarity). If no voiceprint, always matches."""
    if voiceprint is None:
        return True, 1.0
    s = score(audio, voiceprint)
    return s >= threshold, s
