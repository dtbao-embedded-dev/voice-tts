"""Smoke test: the HTTP backend speaks a mixed Vietnamese/English sentence.

Run it directly - no test framework, no fixtures:

    python test_tts.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

import app

MIXED_TEXT = (
    "Chào bạn, hôm nay chúng ta sẽ deploy một model text-to-speech mới "
    "lên production server."
)
MODEL_LOAD_TIMEOUT = 900  # first run downloads the weights from HuggingFace
OUT_WAV = Path(__file__).resolve().parent / "out" / "smoke.wav"


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def wait_until_ready(base: str) -> None:
    deadline = time.time() + MODEL_LOAD_TIMEOUT
    while time.time() < deadline:
        state = get_json(f"{base}/api/status")
        if state["state"] == "ready":
            return
        if state["state"] == "error":
            raise AssertionError(f"engine failed to load: {state['detail']}")
        time.sleep(2)
    raise AssertionError(f"engine still loading after {MODEL_LOAD_TIMEOUT}s")


def post_stream(base: str, text: str, voice: str) -> tuple[bytes, int]:
    body = json.dumps({"text": text, "voice": voice}).encode()
    req = urllib.request.Request(
        f"{base}/api/tts/stream",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read(), int(resp.headers["X-Sample-Rate"])


def main() -> int:
    _, port, _ = app.start_server()
    base = f"http://127.0.0.1:{port}"

    print("waiting for the VieNeu engine (first run downloads the model)...")
    wait_until_ready(base)

    info = get_json(f"{base}/api/voices")
    voices = info["voices"]
    assert voices, "no preset voices reported"
    # The UI sizes its field from this, so it has to be the limit the API enforces.
    assert info["maxChars"] == app.MAX_CHARS == 20_000, f"maxChars: {info['maxChars']}"
    print(f"voices: {len(voices)} presets, default={info['default']!r}")

    raw, rate = post_stream(base, MIXED_TEXT, info["default"])
    assert rate == 48_000, f"expected 48 kHz, got {rate}"
    assert raw, "stream returned no audio"
    assert len(raw) % 4 == 0, "stream is not whole float32 samples"

    audio = np.frombuffer(raw, dtype=np.float32)
    seconds = len(audio) / rate
    rms = float(np.sqrt(np.mean(np.square(audio))))
    peak = float(np.max(np.abs(audio)))
    print(f"audio: {seconds:.2f}s, rms={rms:.4f}, peak={peak:.4f}")

    assert seconds > 2.0, f"too short for this sentence: {seconds:.2f}s"
    assert rms > 0.01, f"audio is silent: rms={rms:.4f}"
    assert peak <= 1.5, f"audio is clipping hard: peak={peak:.4f}"

    # Rejecting bad input matters more than the happy path; check the boundary.
    for bad, why in ((" ", "empty text"), ("a" * (app.MAX_CHARS + 1), "over-long text")):
        try:
            post_stream(base, bad, info["default"])
        except urllib.error.HTTPError as exc:
            assert exc.code == 400, f"{why}: expected 400, got {exc.code}"
        else:
            raise AssertionError(f"{why} was accepted")
    try:
        post_stream(base, "test", "Không Tồn Tại")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400, f"unknown voice: expected 400, got {exc.code}"
    else:
        raise AssertionError("unknown voice was accepted")

    OUT_WAV.parent.mkdir(exist_ok=True)
    with wave.open(str(OUT_WAV), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    print(f"OK - wrote {OUT_WAV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
