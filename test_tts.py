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


def post_stream(base: str, text: str, voice: str, speed: float | None = None) -> tuple[bytes, int]:
    payload = {"text": text, "voice": voice}
    if speed is not None:
        payload["speed"] = speed
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base}/api/tts/stream",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read(), int(resp.headers["X-Sample-Rate"])


def peak_hz(audio: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
    return float(np.fft.rfftfreq(len(audio), 1 / rate)[int(np.argmax(spectrum))])


def chunked(audio: np.ndarray, sizes: list[int]):
    """Hand the stretcher the same samples in arbitrary slices, as HTTP does."""
    start = 0
    for n in sizes:
        yield audio[start:start + n]
        start += n
    if start < len(audio):
        yield audio[start:]


def stretched(audio: np.ndarray, speed: float, sizes: list[int] | None = None) -> np.ndarray:
    return np.concatenate(list(app.stretch(chunked(audio, sizes or [len(audio)]), speed)))


def check_stretch() -> None:
    """The time-stretcher on its own - no server, no engine, milliseconds.

    Reading speed is the one piece of real signal processing here, so it gets
    checked before anything slow runs.
    """
    rate = app.SAMPLE_RATE
    t = np.arange(3 * rate) / rate
    # A sawtooth, not a sine: its harmonics make a misaligned overlap-add
    # audible, where a single partial survives almost any splice.
    source = ((2 * (200 * t % 1) - 1) * 0.5).astype(np.float32)
    source_jump = float(np.max(np.abs(np.diff(source))))

    for speed in (0.75, 1.0, 1.25, 1.5):
        out = stretched(source, speed)
        # flush() lets the final partial frame through unstretched; bound it
        # rather than allowing a blanket percentage.
        slack = app.STRETCH_FRAME + app.STRETCH_SEARCH + round(app.STRETCH_HOP * speed)
        assert abs(len(out) - len(source) / speed) <= slack, (
            f"speed {speed}: {len(out) / rate:.2f}s, expected "
            f"{len(source) / speed / rate:.2f}s"
        )
        # Resampling would have moved the peak to 200/speed Hz. That it does not
        # is the whole point of the change.
        peak = peak_hz(out, rate)
        assert abs(peak - 200) < 2, f"speed {speed}: pitch moved to {peak:.1f} Hz"
        jump = float(np.max(np.abs(np.diff(out))))
        assert jump <= source_jump * 1.05, (
            f"speed {speed}: joins click - jump {jump:.3f} over {source_jump:.3f}"
        )

    # The state carried between calls is the part that breaks silently, so feed
    # the same audio as one block and as forty ragged ones.
    sizes = np.random.default_rng(7).integers(200, 5000, 40).tolist()
    for speed in (0.75, 1.25, 1.5):
        one, many = stretched(source, speed), stretched(source, speed, sizes)
        assert len(one) == len(many), f"speed {speed}: {len(one)} vs {len(many)} samples"
        assert np.allclose(one, many, atol=1e-6), f"speed {speed}: chunking changed the output"

    assert np.array_equal(stretched(source, 1.0), source), "speed 1.0 is not the identity"

    # A stream that ends before one frame is filled has nothing to overlap, so
    # it must come through as itself rather than behind a half-frame of silence.
    assert not list(app.stretch([], 0.75)), "an empty stream produced audio"
    tiny = np.full(900, 0.3, dtype=np.float32)
    assert np.array_equal(stretched(tiny, 0.75), tiny), "sub-frame input was altered"

    print("stretch: pitch held, lengths exact, chunking invariant")


def main() -> int:
    check_stretch()

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
    try:
        post_stream(base, "test", info["default"], speed=app.SPEED_MAX + 1)
    except urllib.error.HTTPError as exc:
        assert exc.code == 400, f"out-of-range speed: expected 400, got {exc.code}"
    else:
        raise AssertionError("out-of-range speed was accepted")

    # The stretcher on the real stream: chunk sizes here are the engine's, not
    # the ones check_stretch() picked.
    slow_raw, slow_rate = post_stream(base, MIXED_TEXT, info["default"], speed=0.75)
    assert slow_rate == 48_000, f"0.75x changed the sample rate: {slow_rate}"
    slow = np.frombuffer(slow_raw, dtype=np.float32)
    slow_rms = float(np.sqrt(np.mean(np.square(slow))))
    assert slow_rms > 0.01, f"0.75x is silent: rms={slow_rms:.4f}"
    print(f"0.75x: {len(slow) / slow_rate:.2f}s, rms={slow_rms:.4f}")

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
