"""Voice TTS - a desktop app that reads mixed Vietnamese/English text aloud.

The UI is a web view hosted in a native window; this module is both the HTTP
backend (FastAPI on a loopback port) and the application entry point.

    python app.py              # native window
    python app.py --no-window  # backend only, prints the URL
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from numpy.lib.stride_tricks import sliding_window_view
from pydantic import BaseModel

SAMPLE_RATE = 48_000
MAX_CHARS = 20_000

# PyInstaller unpacks bundled data next to the executable, not next to this file.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
WEB_DIR = BASE_DIR / "web"

# The packaged build carries the model cache inside it. Point HuggingFace at that
# copy and keep it off the network, so a fresh machine never waits on a download.
# A source checkout has no such directory and keeps using the user's own cache.
# This runs at import time, long before `vieneu` pulls in huggingface_hub.
if (BASE_DIR / "hf").is_dir():
    os.environ["HF_HOME"] = str(BASE_DIR / "hf")
    os.environ["HF_HUB_OFFLINE"] = "1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the model in the background so the window can paint immediately."""
    threading.Thread(target=_warm, name="warm-engine", daemon=True).start()
    yield


app = FastAPI(title="Voice TTS", docs_url=None, redoc_url=None, lifespan=lifespan)

_engine = None
_engine_error: str | None = None
_engine_lock = threading.Lock()


def engine():
    """Return the shared VieNeu engine, loading it on first use.

    Loading pulls the v3 Turbo weights from the HuggingFace cache (downloading
    them on a cold machine), so it happens once and is shared by all requests.
    """
    global _engine, _engine_error
    with _engine_lock:
        if _engine is None:
            from vieneu import Vieneu

            try:
                _engine = Vieneu(precision="int8")
            except Exception as exc:  # surfaced to the UI via /api/status
                _engine_error = f"{type(exc).__name__}: {exc}"
                raise
        return _engine


REGIONS = ("Bắc", "Trung", "Nam")


def _region_of(meta: dict) -> str:
    """The engine drops the raw ``region`` field but keeps it in the description
    as ``gender · region · style`` - read it back from there."""
    if meta.get("region"):
        return meta["region"]
    parts = [p.strip() for p in meta.get("description", "").split("·")]
    return parts[1] if len(parts) > 1 and parts[1] in REGIONS else ""


def preset_voices() -> list[dict]:
    """The built-in voices, already ordered with the editors' picks first.

    ``list_preset_voices()`` yields ``(label, name)``; the per-voice record adds
    the region/gender the UI groups by.
    """
    tts = engine()
    voices = []
    for _label, name in tts.list_preset_voices():
        meta = tts.get_preset_voice(name)
        voices.append(
            {
                "name": name,
                "region": _region_of(meta),
                "gender": meta.get("gender", ""),
                "description": meta.get("description", ""),
                "featured": meta.get("featured") is not None,
            }
        )
    return voices


def default_voice() -> str:
    tts = engine()
    # The engine only exposes its own default as a private attribute; route it
    # through the public resolver so a rename degrades instead of breaking.
    name = tts.resolve_voice_name(getattr(tts, "_default_voice", None))
    return name or preset_voices()[0]["name"]


SPEED_MIN, SPEED_MAX = 0.5, 2.0
# 32 ms at 48 kHz spans two periods of a 62 Hz voice. The periodic Hann sums to
# exactly 1.0 at half-frame hops, so the overlap-add needs no normalisation.
# ponytail: tuned for a 62-250 Hz speaking range; a voice below it can warble
# faintly at 0.75x, and these two constants are the knobs for that.
STRETCH_FRAME = 1536
STRETCH_HOP = STRETCH_FRAME // 2
STRETCH_SEARCH = 512  # +/- 10.7 ms, about one period at 94 Hz
_WINDOW = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(STRETCH_FRAME) / STRETCH_FRAME)


class Stretch:
    """Make a stream of samples longer or shorter without moving its pitch.

    WSOLA: each output frame is read from the position, within
    ``STRETCH_SEARCH`` of the nominal one, whose waveform best continues the
    frame just emitted. Lining the pitch periods up that way is what keeps the
    overlap-add from doubling or cancelling them, and it is the whole difference
    from resampling - where duration and pitch can only move together.

    The engine has no speed parameter, so this is where reading speed comes
    from. Feed it whatever chunks arrive; the state carried between calls is
    what makes the joins inaudible.
    """

    def __init__(self, speed: float) -> None:
        self.hop_in = max(1, round(STRETCH_HOP * speed))
        self.buf = np.zeros(0, dtype=np.float32)
        self.nominal = 0  # advances by hop_in, exactly
        self.pos = 0  # where the current frame is read from
        self.tail = np.zeros(STRETCH_HOP, dtype=np.float32)  # awaiting its partner

    def push(self, chunk) -> np.ndarray:
        """Absorb a chunk and return whatever output it completed."""
        arriving = np.asarray(chunk, dtype=np.float32).ravel()
        self.buf = np.concatenate((self.buf, arriving))
        out = []
        while len(self.buf) >= self._need():
            out.append(self._frame())
        drop = min(self.pos, self.nominal) - STRETCH_SEARCH  # no later search reaches it
        if drop > 0:
            self.buf = self.buf[drop:]
            self.pos -= drop
            self.nominal -= drop
        return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)

    def flush(self) -> np.ndarray:
        """End the stream: the pending half-frame plus the unconsumed input.

        That remainder is under 70 ms and sits at the very end of a whole read,
        so it passes through unstretched rather than earning a second code path.
        """
        if not self.nominal:  # never filled one frame: there is nothing to overlap
            return self.buf
        return np.concatenate((self.tail, self.buf[self.pos + STRETCH_HOP:]))

    def _need(self) -> int:
        """How much ``buf`` must hold before the next frame can be placed."""
        return max(self.pos + STRETCH_HOP,
                   self.nominal + self.hop_in + STRETCH_SEARCH) + STRETCH_FRAME

    def _frame(self) -> np.ndarray:
        seg = self.buf[self.pos:self.pos + STRETCH_FRAME] * _WINDOW
        out = self.tail + seg[:STRETCH_HOP]
        self.tail = seg[STRETCH_HOP:].copy()

        # What would have followed had we not stretched - match against that.
        target = self.buf[self.pos + STRETCH_HOP:self.pos + STRETCH_HOP + STRETCH_FRAME]
        self.nominal += self.hop_in
        lo = max(self.nominal - STRETCH_SEARCH, 0)
        hi = self.nominal + STRETCH_SEARCH
        cand = sliding_window_view(self.buf[lo:hi + STRETCH_FRAME], STRETCH_FRAME)
        cand = cand[:hi - lo + 1]
        score = (cand @ target) / (np.sqrt(np.einsum("ij,ij->i", cand, cand)) + 1e-9)
        # The nominal pointer carries the time scale, not the chosen one: letting
        # the search offset accumulate makes the output drift longer every frame.
        self.pos = lo + int(np.argmax(score))
        return out


def stretch(chunks, speed: float):
    """Yield ``chunks`` time-scaled by ``speed``, pitch untouched."""
    if speed == 1.0:
        yield from chunks
        return
    scaler = Stretch(speed)
    for chunk in chunks:
        out = scaler.push(chunk)
        if len(out):
            yield out
    rest = scaler.flush()
    if len(rest):
        yield rest


class SpeakRequest(BaseModel):
    text: str
    voice: str | None = None
    speed: float = 1.0


def _warm() -> None:
    try:
        engine()
    except Exception:
        pass  # /api/status reports _engine_error


@app.get("/api/status")
def status() -> dict:
    if _engine is not None:
        return {"state": "ready"}
    if _engine_error is not None:
        return {"state": "error", "detail": _engine_error}
    return {"state": "loading"}


@app.get("/api/voices")
def voices() -> dict:
    return {
        "voices": preset_voices(),
        "default": default_voice(),
        "sampleRate": SAMPLE_RATE,
        "maxChars": MAX_CHARS,
    }


@app.post("/api/tts/stream")
def tts_stream(req: SpeakRequest):
    """Stream raw float32 LE samples at 48 kHz as they are generated.

    ``speed`` scales the duration and leaves the pitch where it is, so the
    stream is always 48 kHz and the client plays it back untouched.
    """
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Chưa có văn bản để đọc.")
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"Văn bản dài quá {MAX_CHARS} ký tự.")
    if not SPEED_MIN <= req.speed <= SPEED_MAX:
        raise HTTPException(400, f"Tốc độ phải trong khoảng {SPEED_MIN}-{SPEED_MAX}.")

    tts = engine()
    voice = tts.resolve_voice_name(req.voice) or (None if req.voice else default_voice())
    if voice is None:
        raise HTTPException(400, f"Không có giọng '{req.voice}'.")

    def samples():
        # A failure here lands mid-body, so the client sees a short stream
        # rather than an HTTP error; it reports that as a playback failure.
        for chunk in stretch(tts.infer_stream(text, voice=voice), req.speed):
            yield np.asarray(chunk, dtype=np.float32).tobytes()

    return StreamingResponse(
        samples(),
        media_type="application/octet-stream",
        headers={"X-Sample-Rate": str(SAMPLE_RATE), "Cache-Control": "no-store"},
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


def start_server(port: int = 0) -> tuple[uvicorn.Server, int, threading.Thread]:
    """Bind a loopback socket, serve on it in a daemon thread, return the port.

    Binding before handing the socket to uvicorn avoids the race of picking a
    free port and then losing it to another process.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    bound_port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    return server, bound_port, thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Voice TTS")
    parser.add_argument("--no-window", action="store_true", help="run the backend only")
    parser.add_argument("--port", type=int, default=0, help="fixed port (default: any free port)")
    args = parser.parse_args()

    if args.no_window:
        uvicorn.run(app, host="127.0.0.1", port=args.port or 8760, log_level="info")
        return

    import webview

    # WebView2 cancels every download while this is off - that is why "Lưu WAV"
    # used to do nothing at all. With it on, the platform shows its Save dialog.
    webview.settings["ALLOW_DOWNLOADS"] = True

    _, port, _ = start_server(args.port)
    # pywebview asks WinForms for FormStartPosition.CenterScreen, but it does so
    # after the form handle exists, so the window lands at 78,78 instead. Passing
    # a screen takes the branch that computes the position itself.
    # ponytail: screens[0], not a "primary" lookup pywebview does not expose - on a
    # multi-monitor box where it is not the primary, centre on that one instead.
    webview.create_window(
        "Voice TTS",
        f"http://127.0.0.1:{port}/",
        width=980,
        height=760,
        resizable=False,   # drops the maximize box too; minimize and close stay
        screen=webview.screens[0],
        background_color="#000000",
    )
    webview.start()  # returns when the window closes; daemon threads go with it


if __name__ == "__main__":
    main()
