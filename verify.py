"""Check a reading by ear: transcribe it with Whisper and score it against the text.

The score is ``1 - CER``: the character edit distance between what was asked for
and what Whisper heard, over the length of what was asked for. Both sides are
reduced to letters and digits first, so case, spacing and punctuation - which
Whisper writes its own way - never count as errors; a lost diacritic does.

Whisper (large-v3-turbo, CTranslate2 int8 on the CPU) is loaded on the first
check, not at startup: it holds about 1.6 GB, and most readings never ask.
"""

from __future__ import annotations

import importlib.util
import os
import re
import threading
import unicodedata

import numpy as np

import lexicon

MODEL = "large-v3-turbo"
# faster-whisper's own name for it; looked up in the HF cache to answer
# available() without loading anything.
MODEL_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
WHISPER_RATE = 16_000
MIN_SCORE = 0.95

_EN_TAG = re.compile(r"</?en>", re.IGNORECASE)

_model = None
_error: str | None = None
_lock = threading.Lock()


def canonical(text: str) -> str:
    """``text`` as compared: respelled, NFC, lower case, letters and digits only.

    The lexicon runs on both sides, so "Board" asked for and "bo" heard - or
    "AP" written by Whisper for the "ây pi" that was read - are the same word.
    """
    text = _EN_TAG.sub(" ", lexicon.apply(unicodedata.normalize("NFC", text)))
    text = unicodedata.normalize("NFC", text).lower()
    return "".join(ch for ch in text if ch.isalnum())


def score(reference: str, transcript: str) -> float:
    """``1 - CER`` of ``transcript`` against ``reference``, clamped to 0..1."""
    from rapidfuzz.distance import Levenshtein

    ref, hyp = canonical(reference), canonical(transcript)
    if not ref:
        return 1.0 if not hyp else 0.0
    return max(0.0, 1.0 - Levenshtein.distance(ref, hyp) / len(ref))


def available() -> tuple[bool, str]:
    """Whether a check can run here, and why not when it cannot.

    Cheap: nothing is loaded. Offline (the packaged app) the model must already
    sit in the HF cache; online it is downloaded on the first check.
    """
    if _model is not None:
        return True, ""
    if _error is not None:
        return False, _error
    if importlib.util.find_spec("faster_whisper") is None:
        return False, "Chưa cài faster-whisper (pip install -r requirements.txt)."
    if os.environ.get("HF_HUB_OFFLINE") == "1":
        from huggingface_hub import try_to_load_from_cache

        if not isinstance(try_to_load_from_cache(MODEL_REPO, "model.bin"), str):
            return False, f"Bản này không kèm model Whisper {MODEL}."
    return True, ""


def model():
    """Return the shared Whisper model, loading it on first use."""
    global _model, _error
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            try:
                # Half the logical CPUs: the hyperthread siblings add little to
                # CTranslate2's matrix kernels and would starve the TTS engine.
                _model = WhisperModel(MODEL, device="cpu", compute_type="int8",
                                      cpu_threads=max(1, (os.cpu_count() or 2) // 2))
            except Exception as exc:
                _error = f"Không nạp được Whisper: {type(exc).__name__}: {exc}"
                raise
        return _model


def transcribe(audio: np.ndarray, rate: int) -> str:
    """What Whisper hears in ``audio`` (float32 mono at ``rate``)."""
    import soxr

    audio = np.asarray(audio, dtype=np.float32).ravel()
    if rate != WHISPER_RATE:
        audio = soxr.resample(audio, rate, WHISPER_RATE)
    whisper = model()
    with _lock:  # one at a time: a second run would only split the same cores
        # No initial_prompt: handing Whisper the expected text would bias it
        # towards hearing exactly that, and the check would pass by construction.
        segments, _ = whisper.transcribe(audio, language="vi", beam_size=5,
                                         condition_on_previous_text=False)
        return " ".join(seg.text.strip() for seg in segments).strip()


def check(audio: np.ndarray, rate: int, reference: str) -> tuple[float, str]:
    """``(score, transcript)`` of ``audio`` read from ``reference``."""
    transcript = transcribe(audio, rate)
    return score(reference, transcript), transcript
