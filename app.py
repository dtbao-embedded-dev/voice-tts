"""Voice TTS - a desktop app that reads mixed Vietnamese/English text aloud.

The UI is a web view hosted in a native window; this module is the HTTP backend
(FastAPI) and the entry point. The command line itself lives in ``cli.py``.

    python app.py              # native window
    python app.py serve        # backend only (``--no-window`` still works)
    python app.py --help       # every subcommand and flag
"""

from __future__ import annotations

import hmac
import io
import itertools
import os
import socket
import sys
import threading
import time
import wave
from collections import deque
from contextlib import asynccontextmanager, closing, contextmanager
from pathlib import Path
from typing import Literal

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from numpy.lib.stride_tricks import sliding_window_view
from pydantic import BaseModel

import lexicon
import respell

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

# On Linux the HuggingFace cache makes each snapshot file a symlink into blobs/.
# onnxruntime resolves the backbone through that link and then refuses its
# external .data file, a different blob, as "escaping the model directory".
# Real files in the snapshot keep the weights side by side. Windows already
# gets real files (no symlink rights), so nothing changes there.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the model in the background so the window can paint immediately."""
    threading.Thread(target=_warm, name="warm-engine", daemon=True).start()
    yield


app = FastAPI(title="Voice TTS", docs_url=None, redoc_url=None, lifespan=lifespan)

# Shared secret for a server reachable from the LAN. None keeps the API open,
# which is what a loopback-only desktop app wants.
TOKEN_COOKIE = "vtts_token"
_token: str | None = None


def set_token(token: str | None) -> None:
    """Require ``token`` on every ``/api`` request from now on (None: open)."""
    global _token
    _token = token or None


def _token_ok(candidate: str | None) -> bool:
    # compare_digest, so a wrong guess costs the same time however close it is.
    return candidate is not None and hmac.compare_digest(candidate.encode(), _token.encode())


# The desktop window's backend sits on a fixed loopback port. A web page that
# rebinds its own hostname to 127.0.0.1 would be same-origin with it; such a
# request still carries that hostname, so the window's backend accepts only its
# own. None (serve mode) accepts any Host - the token guards a LAN server.
_gui_hosts: frozenset[str] | None = None


def set_gui_hosts(port: int | None) -> None:
    global _gui_hosts
    _gui_hosts = None if port is None else frozenset(
        {f"127.0.0.1:{port}", f"localhost:{port}"})


@app.middleware("http")
async def require_host(request: Request, call_next):
    if _gui_hosts is not None and request.headers.get("host", "").lower() not in _gui_hosts:
        return JSONResponse({"detail": "Sai địa chỉ."}, status_code=421)
    return await call_next(request)


@app.middleware("http")
async def require_token(request: Request, call_next):
    """Guard the API, not the page: the page is static and carries nothing.

    A script sends ``Authorization: Bearer``; the web UI cannot add a header to
    its own fetches without knowing the token, so it rides on the cookie that
    ``/?token=`` sets instead.
    """
    if _token is None or not request.url.path.startswith("/api/"):
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    bearer = auth[7:] if auth.lower().startswith("bearer ") else None
    if _token_ok(bearer) or _token_ok(request.cookies.get(TOKEN_COOKIE)):
        return await call_next(request)
    await _drain(request)
    return JSONResponse({"detail": "Thiếu hoặc sai token."}, status_code=401)


async def _drain(request: Request) -> None:
    """Take in what the client sent before refusing it: closing on an unread body
    makes Windows reset the connection, and the client sees an abort, not the
    error. A megabyte is plenty for any honest mistake; past it, the reset is fine.
    """
    seen = 0
    async for chunk in request.stream():
        seen += len(chunk)
        if seen > 1 << 20:
            break

# The CPU engine's ONNX graphs: "fp32" (onnx_update, 475 MB, the reference
# quality) or "int8" (onnx_int8, 165 MB; faster only where the CPU has the int8
# path onnxruntime wants, distorted where it has not - on an i5-14600K fp32 ran
# at RTF 0.29, int8 at 0.55). tool-build.py fetches and ships the matching subfolder.
MODEL_PRECISION = "fp32"

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
                _engine = Vieneu(precision=MODEL_PRECISION)
            except Exception as exc:  # surfaced to the UI via /api/status
                _engine_error = f"{type(exc).__name__}: {exc}"
                raise
        return _engine


class Turns:
    """Let at most ``slots`` readings run at once; the rest wait in arrival order.

    ``threading.Semaphore`` wakes an arbitrary waiter, so a reader who came later
    could overtake one who has waited longer; the explicit queue cannot.
    """

    def __init__(self, slots: int) -> None:
        self.slots = slots
        self._busy = 0
        self._waiting: deque[object] = deque()
        self._cv = threading.Condition()

    @contextmanager
    def turn(self):
        me = object()
        with self._cv:
            self._waiting.append(me)
            self._cv.wait_for(lambda: self._waiting[0] is me and self._busy < self.slots)
            self._waiting.popleft()
            self._busy += 1
            self._cv.notify_all()  # with slots > 1, the next in line may fit too
        try:
            yield
        finally:
            with self._cv:
                self._busy -= 1
                self._cv.notify_all()

    def load(self) -> tuple[int, int]:
        """``(reading, waiting)`` right now."""
        with self._cv:
            return self._busy, len(self._waiting)


# Readings the engine runs at once. On CPU it takes one ONNX call at a time, so a
# second reading adds no throughput and only halves everyone's speed: on an
# i5-8500T, 1 reading ran at RTF 0.79, 2 at 1.65 each, 3 at 2.5 each - the same
# ~1.2 s of audio per second in total. One at a time keeps the one being heard
# faster than real time and finishes the queue sooner on average.
MAX_STREAMS = max(1, int(os.environ.get("VOICE_TTS_MAX_STREAMS", "1")))
_turns = Turns(MAX_STREAMS)

# What each reading logs carries no text unless this is set: the text is what a
# listener typed, and the journal keeps it long after the reading is gone.
LOG_TEXT = os.environ.get("VOICE_TTS_LOG_TEXT", "") == "1"
_reading_ids = itertools.count(1)


def log_reading(rid: int, event: str) -> None:
    """One line per step of a reading, on stderr whatever uvicorn's log level:
    the homelab service runs at ``warning``, which silences uvicorn's access log.
    A windowed build has no stderr, and print() then writes nothing."""
    print(f"reading #{rid} {event}", file=sys.stderr, flush=True)


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
    # "f32": raw float32 streamed as it is generated. "wav", "mp3", "ogg": the
    # whole reading as one file, sent once it is complete.
    format: Literal["f32", "wav", "mp3", "ogg"] = "f32"
    # "normal": the engine reads the text as typed (POST spelled "phê ô ét tê").
    # "special": respell.py rewrites terms first (POST as "post", AP as "ây pi").
    pronunciation: Literal["normal", "special"] = "normal"


def wav_bytes(chunks) -> bytes:
    """Collect float32 chunks into a complete 16-bit mono WAV file."""
    audio = np.concatenate([np.zeros(0, dtype=np.float32), *chunks])
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm.tobytes())
    return buf.getvalue()


# format -> (libsndfile container, codec, media type). The libsndfile that the
# soundfile wheels bundle carries LAME and Vorbis, so no encoder is installed.
ENCODINGS = {
    "mp3": ("MP3", "MPEG_LAYER_III", "audio/mpeg"),
    "ogg": ("OGG", "VORBIS", "audio/ogg"),
}
# A tape the window sends to /api/encode: 20 000 characters read at 0.5x is
# under an hour of 16-bit audio at 48 kHz, about 330 MB; past that it is a mistake.
ENCODE_MAX_BYTES = 400 * 1024 * 1024


def encode_audio(audio: np.ndarray, fmt: str) -> bytes:
    """``audio`` (float32 mono at ``SAMPLE_RATE``) as a complete MP3 or OGG file."""
    import soundfile

    container, codec, _ = ENCODINGS[fmt]
    buf = io.BytesIO()
    soundfile.write(buf, np.clip(audio, -1.0, 1.0), SAMPLE_RATE, format=container,
                    subtype=codec)
    return buf.getvalue()


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


@app.get("/api/version")
def version() -> dict:
    """The version this server runs, so a client can tell it from its own."""
    import cli  # standard library only at import; the version lives there

    return {"version": cli.__version__}


@app.get("/api/voices")
def voices() -> dict:
    return {
        "voices": preset_voices(),
        "default": default_voice(),
        "sampleRate": SAMPLE_RATE,
        "maxChars": MAX_CHARS,
    }


PRONUNCIATIONS = ("normal", "special")

# The engine packs sentences into chunks of up to 256 characters by default.
# Three sentences packed into one 226-character chunk made it speak a phrase
# twice ("post bằng ESP HTTP post bằng ESP HTTP client") in 5 of 20 readings,
# about as often once ESP was respelled; at 120 none of 20 did. A sentence longer than
# this is still split at its commas, as before.
CHUNK_CHARS = 120


def synthesize(text: str, voice: str | None = None, speed: float = 1.0,
               pronunciation: str = "normal", origin: str | None = None):
    """Validate a request and return ``(voice, chunks)``.

    ``chunks`` yields float32 arrays at ``SAMPLE_RATE`` as the engine produces
    them, time-scaled by ``speed``. Validation runs here, eagerly, and raises
    ``ValueError`` - so the HTTP route can still answer 400 before streaming,
    and the CLI can report it before opening any output.

    ``origin`` (``"client=<ip> format=<fmt>"``) logs the reading's queue, start
    and end; the CLI passes none and logs nothing.
    """
    text = text.strip()
    if not text:
        raise ValueError("Chưa có văn bản để đọc.")
    if len(text) > MAX_CHARS:
        raise ValueError(f"Văn bản dài quá {MAX_CHARS} ký tự.")
    if pronunciation not in PRONUNCIATIONS:
        raise ValueError(f"Cách đọc phải là {' hoặc '.join(PRONUNCIATIONS)}.")
    if not SPEED_MIN <= speed <= SPEED_MAX:
        raise ValueError(f"Tốc độ phải trong khoảng {SPEED_MIN}-{SPEED_MAX}.")

    tts = engine()
    resolved = tts.resolve_voice_name(voice) or (None if voice else default_voice())
    if resolved is None:
        raise ValueError(f"Không có giọng '{voice}'.")

    spoken = respell.special(text, lexicon.load_user()) if pronunciation == "special" else text

    def generate():
        for chunk in stretch(tts.infer_stream(spoken, voice=resolved,
                                              max_chars=CHUNK_CHARS), speed):
            yield np.asarray(chunk, dtype=np.float32)

    def chunks():
        # The turn is taken on the first chunk asked for, not here, so a
        # request that fails validation never queues; closing the generator
        # (the listener hung up) gives the turn back.
        with _turns.turn():
            yield from generate()

    def logged_chunks():
        # chunks(), plus a line when the reading queues, when its turn comes and
        # when it ends - done, hung-up or error - with what it cost.
        rid = next(_reading_ids)
        reading, waiting = _turns.load()
        log_reading(rid, f"queue {origin} ahead={reading + waiting} reading={reading} "
                         f"waiting={waiting}" + (f" text={text!r}" if LOG_TEXT else ""))
        arrived = time.monotonic()
        with _turns.turn():
            waited = time.monotonic() - arrived
            log_reading(rid, f"start waited={waited:.2f}s voice={resolved} speed={speed:.2f} "
                             f"pronunciation={pronunciation} chars={len(text)} "
                             f"spoken_chars={len(spoken)}")
            source = generate()
            frames = count = 0
            compute = first = 0.0
            outcome, detail = "done", ""
            try:
                while True:
                    # Only the time spent in the engine counts toward the RTF: a
                    # stream sits at the yield below while the client drains it.
                    begun = time.monotonic()
                    try:
                        chunk = next(source)
                    except StopIteration:
                        break
                    now = time.monotonic()
                    compute += now - begun
                    if not count:
                        first = now - arrived
                    frames += len(chunk)
                    count += 1
                    yield chunk
            except GeneratorExit:
                outcome = "hung-up"
                raise
            except Exception as exc:
                outcome, detail = "error", f" error={exc!r}"
                raise
            finally:
                source.close()
                audio = frames / SAMPLE_RATE
                rtf = f"{compute / audio:.2f}" if audio else "-"
                log_reading(rid, f"{outcome} audio={audio:.2f}s compute={compute:.2f}s "
                                 f"rtf={rtf} first={first:.2f}s chunks={count} "
                                 f"wall={time.monotonic() - arrived:.2f}s{detail}")

    return resolved, (logged_chunks() if origin else chunks())


class ClosingStream(StreamingResponse):
    """A ``StreamingResponse`` that closes its generator however the response ends.

    When the listener hangs up, Starlette stops iterating and skips the
    background task, leaving the generator open until the garbage collector
    finds it - and an open reading holds its turn, so the queue behind it stalls.
    """

    def __init__(self, content, **kwargs) -> None:
        super().__init__(content, **kwargs)
        self._source = content

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await run_in_threadpool(self._source.close)


@app.post("/api/tts/stream")
def tts_stream(req: SpeakRequest, request: Request):
    """Stream raw float32 LE samples at 48 kHz as they are generated.

    ``speed`` scales the duration and leaves the pitch where it is, so the
    stream is always 48 kHz and the client plays it back untouched.

    ``format: "wav"`` (or ``"mp3"``, ``"ogg"``) trades the streaming for a file
    any player opens: the whole reading is synthesized first, then sent as one
    file with its real length in ``Content-Length``.
    """
    try:
        client = request.client.host if request.client else "-"
        _, chunks = synthesize(req.text, req.voice, req.speed, req.pronunciation,
                               origin=f"client={client} format={req.format}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    if req.format != "f32":
        if req.format == "wav":
            body, media = wav_bytes(chunks), "audio/wav"
        else:
            audio = np.concatenate([np.zeros(0, dtype=np.float32), *chunks])
            body, media = encode_audio(audio, req.format), ENCODINGS[req.format][2]
        return Response(
            body,
            media_type=media,
            headers={"X-Sample-Rate": str(SAMPLE_RATE), "Cache-Control": "no-store",
                     "Content-Disposition": f'inline; filename="speech.{req.format}"'},
        )

    def samples():
        # A failure here lands mid-body, so the client sees a short stream
        # rather than an HTTP error; it reports that as a playback failure.
        with closing(chunks):
            for chunk in chunks:
                yield chunk.tobytes()

    return ClosingStream(
        samples(),
        media_type="application/octet-stream",
        headers={"X-Sample-Rate": str(SAMPLE_RATE), "Cache-Control": "no-store"},
    )


class LexiconEntry(BaseModel):
    word: str
    say: str
    matchCase: bool = False


class LexiconBody(BaseModel):
    user: list[LexiconEntry]


def _lexicon_state(user: list[dict]) -> dict:
    return {"builtin": lexicon.builtin(), "user": user}


@app.get("/api/lexicon")
def lexicon_get() -> dict:
    """The built-in words and the user's own, which ``special`` reads with."""
    try:
        return _lexicon_state(lexicon.load_user())
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from None


@app.put("/api/lexicon")
def lexicon_put(body: LexiconBody) -> dict:
    """Replace the user's words. One list for the whole server: on a LAN server
    everyone who holds the token reads, and edits, the same one."""
    try:
        return _lexicon_state(lexicon.save_user([e.model_dump() for e in body.user]))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/encode")
async def encode(request: Request, format: str):
    """Encode a tape the client already holds: 16-bit LE mono PCM at 48 kHz in,
    an MP3 or OGG file out. Saving a reading as MP3 then costs no second synthesis.
    """
    # Octets only: a text/plain POST is one another site may send with no
    # preflight, and nothing of ours sends that.
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/octet-stream":
        await _drain(request)
        raise HTTPException(415, "Cần Content-Type application/octet-stream.")
    # Read the body before any other refusal: answering while the client is
    # still sending makes Windows abort the connection instead of showing a 400.
    # Counted as it arrives, since a chunked body has no Content-Length to trust.
    if int(request.headers.get("content-length") or 0) > ENCODE_MAX_BYTES:
        raise HTTPException(413, "Âm thanh quá dài để mã hoá.")
    parts, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > ENCODE_MAX_BYTES:
            raise HTTPException(413, "Âm thanh quá dài để mã hoá.")
        parts.append(chunk)
    body = b"".join(parts)
    if format not in ENCODINGS:
        raise HTTPException(400, f"Định dạng phải là {' hoặc '.join(ENCODINGS)}.")
    if not body or len(body) % 2:
        raise HTTPException(400, "Cần âm thanh 16-bit mono 48 kHz.")
    audio = np.frombuffer(body, dtype="<i2").astype(np.float32) / 32767
    # Encoding blocks for seconds on a long tape; keep the event loop free.
    data = await run_in_threadpool(encode_audio, audio, format)
    return Response(data, media_type=ENCODINGS[format][2],
                    headers={"Cache-Control": "no-store",
                             "Content-Disposition": f'inline; filename="speech.{format}"'})


@app.get("/")
def index(token: str | None = None) -> FileResponse:
    """The page; ``?token=`` hands the web UI its cookie for a guarded server."""
    page = FileResponse(WEB_DIR / "index.html")
    if _token is not None and _token_ok(token):
        page.set_cookie(TOKEN_COOKIE, token, httponly=True, samesite="strict",
                        max_age=365 * 24 * 3600)
    return page


@app.get("/favicon.svg")
def favicon() -> Response:
    """The app icon, drawn from the same geometry as the tray and the window icon."""
    import icon

    return Response(icon.svg(), media_type="image/svg+xml",
                    headers={"Cache-Control": "max-age=86400"})


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


def start_server(port: int = 0, host: str = "127.0.0.1",
                 log_level: str = "warning") -> tuple[uvicorn.Server, int, threading.Thread]:
    """Bind a socket, serve on it in a daemon thread, return the bound port.

    Binding before handing the socket to uvicorn avoids the race of picking a
    free port and then losing it to another process. Listening here too means a
    request made the moment this returns waits in the backlog instead of being
    refused while uvicorn is still starting - Linux refuses at once, Windows
    only hides it by retrying the connect for a second or two.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":
        # Windows' SO_REUSEADDR lets a second socket bind a port that is in use,
        # and the two then split the connections; claim the port outright.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    sock.listen(2048)  # uvicorn's default backlog; its own listen() is then a no-op
    bound_port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(app, log_level=log_level))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    return server, bound_port, thread


def start_gui_server(port: int) -> tuple[uvicorn.Server, int, threading.Thread]:
    """``start_server`` on ``port``, or on any free port if that one is taken.

    The window asks for a fixed port so its page keeps one origin - the settings
    and history it stores belong to that origin. A second window, or another
    program on the port, still gets a working app, just without those.
    """
    try:
        return start_server(port)
    except OSError:
        if not port:
            raise
        print(f"voice-tts: port {port} is taken; this window will not see saved "
              "settings or history", file=sys.stderr)
        return start_server(0)


def lan_address() -> str:
    """This machine's address on the LAN, for a URL another machine can open.

    Connecting a UDP socket sends nothing; it only makes the OS pick the
    interface it would route through.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1: never routed anywhere
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def page_urls(host: str, port: int) -> tuple[str, str]:
    """``(local, shareable)`` URLs of the page, carrying the token if one is set."""
    query = f"?token={_token}" if _token else ""
    wildcard = host in ("0.0.0.0", "::", "")
    local_host = "127.0.0.1" if wildcard else host
    shared_host = lan_address() if wildcard else host
    return f"http://{local_host}:{port}/{query}", f"http://{shared_host}:{port}/{query}"


def serve(host: str = "127.0.0.1", port: int = 8760, log_level: str = "info",
          tray: bool = False, open_browser: bool = False) -> None:
    """Run the backend until interrupted, or until "Thoát" with ``tray``."""
    import webbrowser

    local_url, shared_url = page_urls(host, port)
    if not tray:
        if open_browser:
            threading.Timer(1.0, webbrowser.open, [local_url]).start()
        uvicorn.run(app, host=host, port=port, log_level=log_level)
        return

    from tray import Tray

    server, _, thread = start_server(port, host, log_level)
    if open_browser:
        webbrowser.open(local_url)
    if Tray(local_url, on_quit=lambda: None, lan_url=shared_url).run():
        server.should_exit = True  # "Thoát": let uvicorn finish what it is sending
        thread.join(timeout=5)
    else:
        thread.join()  # no tray on this desktop: keep serving in the foreground


def window_icon() -> str | None:
    """Write the app icon as an ``.ico`` for the window; None if that fails.

    Without one, pywebview takes the icon of ``sys.executable`` - the Python
    logo for ``pythonw app.py``. The file is rewritten on every launch (it takes
    milliseconds), so it can live in the temp dir and never goes stale.
    """
    import tempfile

    import icon

    target = Path(tempfile.gettempdir()) / "voice-tts.ico"
    # Write beside it and swap in, so two windows starting at once never hand
    # WinForms a half-written file.
    staged = target.with_name(f"voice-tts-{os.getpid()}.ico")
    try:
        os.replace(icon.save_ico(staged), target)
        return str(target)
    except (OSError, ImportError, ValueError):  # no icon is cosmetic, not fatal
        staged.unlink(missing_ok=True)
        return None


def run_gui(port: int = 0, tray: bool = True) -> None:
    """The desktop app: the backend on loopback plus a native window over it.

    With ``tray`` the window hides into the system tray when minimized or
    closed, and the server keeps running; "Thoát" in the tray menu ends it.
    """
    import webview

    # WebView2 cancels every download while this is off - that is why "Lưu WAV"
    # used to do nothing at all. With it on, the platform shows its Save dialog.
    webview.settings["ALLOW_DOWNLOADS"] = True

    if sys.platform == "win32":
        # The taskbar groups windows by app id, and by default that is the
        # interpreter's: the button would show pythonw's logo, not ours. Set it
        # before the first window exists.
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VoiceTTS.Desktop")

    _, port, _ = start_gui_server(port)
    set_gui_hosts(port)
    url = f"http://127.0.0.1:{port}/"
    # pywebview asks WinForms for FormStartPosition.CenterScreen, but it does so
    # after the form handle exists, so the window lands at 78,78 instead. Passing
    # a screen takes the branch that computes the position itself.
    # ponytail: screens[0], not a "primary" lookup pywebview does not expose - on a
    # multi-monitor box where it is not the primary, centre on that one instead.
    window = webview.create_window(
        "Voice TTS",
        url,
        width=980,
        height=760,
        resizable=False,   # drops the maximize box too; minimize and close stay
        screen=webview.screens[0],
        background_color="#000000",
    )

    icon = None
    if tray:
        from tray import Tray

        quitting = threading.Event()

        def show() -> None:
            window.show()
            window.restore()

        def quit_app() -> None:
            quitting.set()
            window.destroy()

        def on_closing():
            if quitting.is_set():
                return True
            # This handler runs on the UI thread while the close is pending;
            # hiding from here would wait on that same thread, so hand it off.
            threading.Thread(target=window.hide, daemon=True).start()
            return False  # cancel the close: the app lives on in the tray

        icon = Tray(url, on_quit=quit_app, on_show=show)
        if icon.start():
            window.events.closing += on_closing
            window.events.minimized += window.hide
            if sys.platform == "win32":
                from tray import PopupMenu

                # Right-click opens the app's own dark menu, not the native one.
                icon.popup = PopupMenu(icon, url)
        else:
            icon = None  # no tray here: closing the window quits, as before

    # Returns when the window is destroyed; daemon threads go with it. pywebview
    # defaults to a private profile, wiped on exit; a profile kept in the data dir
    # is what lets the page remember settings, the draft and the history.
    webview.start(icon=window_icon(), private_mode=False,
                  storage_path=str(lexicon.data_dir() / "webview"))
    if icon is not None:
        icon.stop()


def main(argv: list[str] | None = None) -> int:
    import cli

    return cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
