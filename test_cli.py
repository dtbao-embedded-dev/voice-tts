"""Fast checks for the CLI, the server options and the token guard.

No model is loaded: a stub engine stands in for VieNeu, so this runs in seconds
and is what CI runs, together with the time-stretch check from ``test_tts.py``.
The real-model path is ``test_tts.py`` itself.

    python test_cli.py
"""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np

import app
import cli

TOKEN = "s3cret-token"
ROOT = Path(__file__).resolve().parent
WORD = int(app.SAMPLE_RATE * 0.1)  # samples the stub engine emits per word


class StubEngine:
    """Just enough of ``vieneu.Vieneu`` for the HTTP layer and the CLI."""

    _default_voice = "Stub A"
    VOICES = {
        "Stub A": {"gender": "Nữ", "description": "Nữ · Bắc · stub", "featured": 1},
        "Stub B": {"gender": "Nam", "description": "Nam · Nam · stub"},
    }

    def list_preset_voices(self):
        return [(name, name) for name in self.VOICES]

    def get_preset_voice(self, name):
        return self.VOICES[name]

    def resolve_voice_name(self, name):
        return name if name in self.VOICES else None

    def infer_stream(self, text, voice=None, max_chars=256):
        self.last_text = text
        self.last_max_chars = max_chars
        self.last_call = "infer_stream"
        # A 220 Hz tone, 0.1 s per word, in a few chunks - enough to be audible
        # and to be told apart from silence.
        n = int(app.SAMPLE_RATE * 0.1 * max(1, len(text.split())))
        t = np.arange(n) / app.SAMPLE_RATE
        tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        yield from np.array_split(tone, 4)

    def infer(self, text, voice=None, max_chars=256):
        audio = np.concatenate(list(self.infer_stream(text, voice, max_chars)))
        self.last_call = "infer"
        return audio


class SlowEngine(StubEngine):
    """The stub, but each chunk takes a while and every reading is recorded, so a
    check can see how many ran at once and in which order they started."""

    def __init__(self, chunks: int = 4, delay: float = 0.05) -> None:
        self.chunks, self.delay = chunks, delay
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.started: list[str] = []

    def infer_stream(self, text, voice=None, max_chars=256):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.started.append(text)
        try:
            for _ in range(self.chunks):
                time.sleep(self.delay)
                yield np.zeros(WORD, dtype=np.float32)
        finally:
            with self.lock:
                self.active -= 1


def request(url: str, headers: dict | None = None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def check_parser() -> None:
    p = cli.build_parser()
    assert cli.parse(p, []).command == "gui", "no arguments must open the window"
    assert cli.parse(p, ["--no-window"]).command == "serve", "--no-window is serve"
    assert cli.parse(p, ["--no-window", "--port", "9001"]).port == 9001
    assert cli.parse(p, ["--port", "9002", "--no-window"]).command == "serve", \
        "--no-window after --port no longer means serve"
    args = cli.parse(p, ["serve", "--host", "0.0.0.0", "--port", "9000", "--token", "x"])
    assert (args.command, args.host, args.port, args.token) == ("serve", "0.0.0.0", 9000, "x")
    args = cli.parse(p, ["serve"])
    assert (args.host, args.port) == ("127.0.0.1", 8760), "serve defaults moved"
    print("parser: gui default, --no-window alias, serve options")


def check_token(base: str) -> None:
    app.set_token(None)
    assert request(f"{base}/api/status")[0] == 200, "no token configured must stay open"

    app.set_token(TOKEN)
    try:
        assert request(f"{base}/api/status")[0] == 401, "missing token accepted"
        bad = {"Authorization": "Bearer nope"}
        assert request(f"{base}/api/status", bad)[0] == 401, "wrong token accepted"
        good = {"Authorization": f"Bearer {TOKEN}"}
        assert request(f"{base}/api/status", good)[0] == 200, "Bearer token refused"
        cookie = {"Cookie": f"{app.TOKEN_COOKIE}={TOKEN}"}
        assert request(f"{base}/api/voices", cookie)[0] == 200, "cookie token refused"
        assert request(f"{base}/api/voices", {"Cookie": f"{app.TOKEN_COOKIE}=x"})[0] == 401
        assert request(f"{base}/api/version")[0] == 401, "version must sit behind the token"
        status, _, body = request(f"{base}/api/version", good)
        assert status == 200 and json.loads(body) == {"version": cli.__version__},             f"/api/version: {status} {body!r}"

        status, headers, _ = request(f"{base}/?token={TOKEN}")
        assert status == 200, f"/?token= gave {status}"
        assert f"{app.TOKEN_COOKIE}={TOKEN}" in headers.get("set-cookie", ""), \
            "/?token= did not set the cookie the web UI relies on"
        status, headers, _ = request(f"{base}/?token=wrong")
        assert "set-cookie" not in {k.lower() for k in headers}, "a wrong token set a cookie"
        # The page itself is static; only the API carries anything worth guarding.
        assert request(f"{base}/web/app.js")[0] == 200, "static files must stay open"
    finally:
        app.set_token(None)
    print("token: 401 without, 200 with Bearer or cookie, /?token= sets it; /api/version")


def run_cli(*args: str, stdin: bytes = b"") -> tuple[int, bytes, str]:
    """``cli.py`` in a fresh process, as a user runs it: exit code, stdout, stderr.

    A subprocess is the only honest test of ``-o -``: nothing but the WAV may
    reach stdout. It also proves the remote path imports nothing beyond the
    standard library, since this process never touches ``app``.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("VOICE_TTS_")}
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, str(ROOT / "cli.py"), *args], input=stdin,
                          capture_output=True, env=env, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")


def wav_frames(data: bytes) -> int:
    with wave.open(io.BytesIO(data)) as wav:
        assert wav.getframerate() == app.SAMPLE_RATE, f"rate {wav.getframerate()}"
        assert (wav.getnchannels(), wav.getsampwidth()) == (1, 2), "not 16-bit mono"
        frames = wav.readframes(wav.getnframes())
        assert np.abs(np.frombuffer(frames, "<i2")).max() > 3000, "WAV is silent"
        return wav.getnframes()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def check_remote(base: str, tmp: Path) -> None:
    app.set_token(TOKEN)
    try:
        remote = ("--server", base, "--token", TOKEN)

        out = tmp / "remote.wav"
        code, _, err = run_cli("speak", "xin chào", "-o", str(out), *remote)
        assert code == 0, f"speak -o failed ({code}): {err}"
        assert wav_frames(out.read_bytes()) == 2 * WORD, "WAV length does not match the stream"

        code, stdout, err = run_cli("speak", "một hai ba", "-o", "-", "-q", *remote)
        assert code == 0, f"speak -o - failed ({code}): {err}"
        assert stdout[:4] == b"RIFF", "stdout does not start with the WAV header"
        assert wav_frames(stdout) == 3 * WORD, "stdout carries more than the WAV"

        code, stdout, err = run_cli("speak", "-o", "-", "-q", *remote, stdin="một hai ba bốn".encode())
        assert code == 0 and wav_frames(stdout) == 4 * WORD, f"stdin text not read: {err}"

        src = tmp / "text.txt"
        src.write_text("năm sáu", encoding="utf-8")
        code, stdout, err = run_cli("speak", "-f", str(src), "-o", "-", "-q", *remote)
        assert code == 0 and wav_frames(stdout) == 2 * WORD, f"-f FILE not read: {err}"

        raw = tmp / "remote.f32"
        code, _, err = run_cli("speak", "xin chào", "--raw", "-o", str(raw), *remote)
        assert code == 0 and raw.stat().st_size == 2 * WORD * 4, f"--raw wrong size: {err}"

        code, _, err = run_cli("speak", "xin chào", "-v", "Không Tồn Tại", "-o", "-", *remote)
        assert code == 2 and "Không Tồn Tại" in err, f"unknown voice: exit {code}, {err!r}"
        code, _, err = run_cli("speak", "xin chào", "-s", "3", "-o", "-", *remote)
        assert code == 2, f"out-of-range speed: exit {code}"
        code, _, err = run_cli("speak", "xin chào", "--raw", *remote)
        assert code == 2, "--raw without -o must be a usage error"
        code, _, err = run_cli("speak", "xin chào", "-o", "-", "--server", base, "--token", "nope")
        assert code == 1 and "token" in err.lower(), f"wrong token: exit {code}, {err!r}"
        code, _, err = run_cli("speak", "xin chào", "-o", "-",
                               "--server", f"http://127.0.0.1:{free_port()}")
        assert code == 1 and "reach" in err.lower(), f"server down: exit {code}, {err!r}"

        code, stdout, err = run_cli("voices", "--json", *remote)
        assert code == 0, f"voices --json failed: {err}"
        info = json.loads(stdout)
        assert [v["name"] for v in info["voices"]] == ["Stub A", "Stub B"], info
        code, stdout, _ = run_cli("voices", *remote)
        table = stdout.decode("utf-8")
        assert code == 0 and "Stub A" in table and "Bắc" in table, table

        code, stdout, err = run_cli("status", *remote)
        assert code == 0 and stdout.decode().strip() == "ready", f"status: {code} {stdout!r} {err}"
        code, stdout, _ = run_cli("status", "--json", *remote)
        assert json.loads(stdout) == {"state": "ready"}, stdout
        code, _, _ = run_cli("status", "--server", f"http://127.0.0.1:{free_port()}")
        assert code == 1, "status of an unreachable server must fail"
    finally:
        app.set_token(None)
    print("remote: wav, stdout, stdin, -f, --raw, bad input -> 2, auth/unreachable -> 1")


def post(base: str, body: dict) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(f"{base}/api/tts/stream", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {}, exc.read()


def check_wav_format(base: str) -> None:
    """``"format": "wav"`` answers a whole, playable file; the default stays raw."""
    status, headers, body = post(base, {"text": "xin chào", "format": "wav"})
    assert status == 200, f"format wav: {status} {body[:200]!r}"
    assert headers["content-type"] == "audio/wav", headers["content-type"]
    assert int(headers["content-length"]) == len(body), "WAV must carry its length"
    assert wav_frames(body) == 2 * WORD, "WAV frames do not match the speech"

    status, headers, body = post(base, {"text": "xin chào", "format": "wav", "speed": 0.75})
    slack = app.STRETCH_FRAME + app.STRETCH_SEARCH + app.STRETCH_HOP
    assert status == 200 and abs(wav_frames(body) - 2 * WORD / 0.75) <= slack, "wav at 0.75x"

    status, headers, body = post(base, {"text": "xin chào"})
    assert headers["content-type"] == "application/octet-stream", "default is no longer raw"
    assert len(body) == 2 * WORD * 4, "raw stream length changed"

    assert post(base, {"text": "xin chào", "format": "flac"})[0] == 422, "unknown format accepted"
    assert post(base, {"text": " ", "format": "wav"})[0] == 400, "empty text as wav accepted"

    # The engine's babble guard runs only in infer(): a file and a short reading go
    # through it, a long raw stream still streams.
    long = "một câu đủ dài để đọc thành nhiều đoạn"
    for body, want in (({"text": long, "format": "wav"}, "infer"),
                       ({"text": long, "format": "mp3"}, "infer"),
                       ({"text": long}, "infer_stream"),
                       ({"text": "Vâng."}, "infer"),
                       ({"text": "Tóm lại là vậy."}, "infer_stream")):
        assert post(base, body)[0] == 200, body
        assert app._engine.last_call == want, (body, app._engine.last_call)
    print("format: wav is a whole 16-bit file with its length, raw stays the default; "
          "files and short readings go through the engine's babble guard")


MAGIC = {"mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"), "ogg": (b"OggS",)}


def decoded_frames(data: bytes, fmt: str) -> int:
    """Frames in an MP3/OGG file, checked to be 48 kHz mono and not silent."""
    import soundfile

    assert data.startswith(MAGIC[fmt]), f"{fmt} starts with {data[:4]!r}"
    audio, rate = soundfile.read(io.BytesIO(data), dtype="float32")
    assert rate == app.SAMPLE_RATE and audio.ndim == 1, f"{fmt}: {rate} Hz, shape {audio.shape}"
    assert np.abs(audio).max() > 0.1, f"{fmt} is silent"
    return len(audio)


def check_encode(base: str, tmp: Path) -> None:
    """MP3 and OGG: whole readings over HTTP, encoded tapes, and the CLI."""
    # Encoder priming and padding move the length a little; 50 ms is far below
    # the 100 ms one stub word lasts.
    slack = app.SAMPLE_RATE // 20
    for fmt, mime in (("mp3", "audio/mpeg"), ("ogg", "audio/ogg")):
        status, headers, body = post(base, {"text": "xin chào", "format": fmt})
        assert status == 200, f"format {fmt}: {status} {body[:200]!r}"
        assert headers["content-type"] == mime, headers["content-type"]
        assert abs(decoded_frames(body, fmt) - 2 * WORD) <= slack, f"{fmt} length is off"

        # What the window sends: the 16-bit tape it already holds.
        tone = (0.3 * np.sin(2 * np.pi * 220 * np.arange(3 * WORD) / app.SAMPLE_RATE))
        pcm = (tone * 32767).astype("<i2").tobytes()
        req = urllib.request.Request(f"{base}/api/encode?format={fmt}", data=pcm,
                                     headers={"Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.headers["content-type"] == mime, resp.headers["content-type"]
            assert abs(decoded_frames(resp.read(), fmt) - 3 * WORD) <= slack, f"encode {fmt}"

    def encode_status(query: str, data: bytes) -> int:
        req = urllib.request.Request(f"{base}/api/encode{query}", data=data,
                                     headers={"Content-Type": "application/octet-stream"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    assert encode_status("?format=flac", b"\0\0") == 400, "unknown encode format accepted"
    assert encode_status("?format=mp3", b"") == 400, "empty tape accepted"
    assert encode_status("?format=mp3", b"\0\0\0") == 400, "half a sample accepted"

    # A plain-text POST is what another site can send without a preflight.
    req = urllib.request.Request(f"{base}/api/encode?format=mp3", data=b"\0\0",
                                 headers={"Content-Type": "text/plain"})
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("a text/plain encode was accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 415, exc.code

    # The size cap holds for a chunked body too, which has no Content-Length.
    import http.client

    saved, app.ENCODE_MAX_BYTES = app.ENCODE_MAX_BYTES, 4000
    try:
        conn = http.client.HTTPConnection("127.0.0.1", int(base.rsplit(":", 1)[1]), timeout=10)
        conn.request("POST", "/api/encode?format=mp3", body=iter([b"\0" * 1000] * 8),
                     headers={"Content-Type": "application/octet-stream"}, encode_chunked=True)
        assert conn.getresponse().status == 413, "a chunked body past the cap was taken"
        conn.close()
    finally:
        app.ENCODE_MAX_BYTES = saved

    # The CLI picks the format from the file name, or from --format; locally it
    # encodes in process, against a server it asks the server to.
    for flags in ([], ["--server", base]):
        for name, extra, fmt in (("cli.mp3", [], "mp3"), ("cli.ogg", [], "ogg"),
                                 ("cli.bin", ["--format", "mp3"], "mp3")):
            out = tmp / name
            if flags:
                code, _, err = run_cli("speak", "một hai ba", "-o", str(out), "-q", *flags, *extra)
                assert code == 0, f"remote {name}: {err}"
            else:
                assert cli.main(["speak", "một hai ba", "-o", str(out), "-q", *extra]) == 0
            assert abs(decoded_frames(out.read_bytes(), fmt) - 3 * WORD) <= slack, (flags, name)
    code, stdout, err = run_cli("speak", "một hai", "-o", "-", "-q", "--format", "ogg",
                                "--server", base)
    assert code == 0 and abs(decoded_frames(stdout, "ogg") - 2 * WORD) <= slack, err
    code, _, _ = run_cli("speak", "một", "--raw", "--format", "mp3", "-o", "-", "--server", base)
    assert code == 2, "--raw with --format must be a usage error"
    print("encode: mp3/ogg readings, /api/encode tapes, CLI by extension or --format")


def check_turns(base: str) -> None:
    """One reading at a time, the others wait their turn in arrival order, and a
    listener who hangs up mid-stream hands the turn on."""
    stub = app._engine
    engine = app._engine = SlowEngine()
    try:
        names = ("one", "two", "three", "four", "five")
        results: dict[str, int] = {}

        def read(name: str) -> None:
            results[name] = post(base, {"text": name, "format": "wav"})[0]

        threads = []
        for name in names:
            thread = threading.Thread(target=read, args=(name,))
            thread.start()
            threads.append(thread)
            time.sleep(0.03)  # arrive in this order, all before "one" is done
        for thread in threads:
            thread.join(10)
        assert results == dict.fromkeys(names, 200), results
        assert engine.peak == 1, f"{engine.peak} readings ran at once"
        assert engine.started == list(names), f"served out of order: {engine.started}"

        # A 10 s stream, abandoned after its first bytes (over SHORT_WORDS words,
        # or the engine reads it in one call and nothing streams).
        engine.chunks, engine.delay = 1000, 0.01
        conn = http.client.HTTPConnection("127.0.0.1", urlsplit(base).port, timeout=10)
        conn.request("POST", "/api/tts/stream", json.dumps({"text": "đọc dở rồi bỏ đi"}),
                     {"Content-Type": "application/json"})
        conn.getresponse().read(WORD * 4)
        engine.chunks = 4  # the next reading is short again
        conn.close()
        begun = time.monotonic()
        status = post(base, {"text": "sau đó", "format": "wav"})[0]
        waited = time.monotonic() - begun
        assert status == 200, status
        assert waited < 3, f"an abandoned stream kept the turn for {waited:.1f} s"
    finally:
        app._engine = stub
    print(f"turns: one reading at a time (VOICE_TTS_MAX_STREAMS={app.MAX_STREAMS}), "
          "the rest in arrival order, a hang-up hands the turn on")


def check_reading_log(base: str) -> None:
    """Every reading leaves queue, start and end lines on stderr - whatever the
    uvicorn log level - and the text itself only with VOICE_TTS_LOG_TEXT=1."""
    stub = app._engine
    engine = app._engine = SlowEngine(chunks=8, delay=0.05)
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            first = threading.Thread(target=post, args=(base, {"text": "trước", "format": "wav"}))
            first.start()
            time.sleep(0.1)  # "trước" holds the turn, so the next one queues
            assert post(base, {"text": "bí mật", "format": "wav", "speed": 1.25})[0] == 200
            first.join(10)

            # Hung up after the first bytes of a long stream (over SHORT_WORDS
            # words, or the engine reads it in one call and nothing streams).
            engine.chunks, engine.delay = 1000, 0.01
            conn = http.client.HTTPConnection("127.0.0.1", urlsplit(base).port, timeout=10)
            conn.request("POST", "/api/tts/stream", json.dumps({"text": "đọc dở rồi bỏ đi"}),
                         {"Content-Type": "application/json"})
            conn.getresponse().read(WORD * 4)
            conn.close()
            engine.chunks, engine.delay = 2, 0.0
            assert post(base, {"text": "sau đó", "format": "wav"})[0] == 200  # waits out the hang-up

            app.LOG_TEXT = True
            assert post(base, {"text": "nói to", "format": "wav"})[0] == 200
    finally:
        app.LOG_TEXT = False
        app._engine = stub
    lines = [line for line in err.getvalue().splitlines() if line.startswith("reading #")]

    def of(rid: str) -> list[str]:
        return [line.split(" ", 2)[2] for line in lines if line.split(" ", 2)[1] == rid]

    ids = list(dict.fromkeys(line.split(" ", 2)[1] for line in lines))
    assert len(ids) == 5, f"expected 5 readings in the log, got {ids}: {lines}"
    first_id, secret, dropped, after, loud = ids

    queue, start, end = of(secret)
    assert queue.startswith("queue client=127.0.0.1 format=wav ahead=1 reading=1 waiting=0"), queue
    assert "bí mật" not in "\n".join(lines), "text logged without VOICE_TTS_LOG_TEXT"
    assert start.startswith("start waited=") and "voice=Stub A" in start, start
    assert "speed=1.25 pronunciation=normal chars=6" in start, start
    waited = float(start.split("waited=")[1].split("s")[0])
    assert waited > 0.1, f"queued behind a 0.4 s reading but waited {waited} s"
    assert end.startswith("done audio=") and " rtf=" in end and " chunks=" in end, end

    assert of(first_id)[0].split(" ")[3] == "ahead=0", of(first_id)
    assert of(dropped)[-1].startswith("hung-up "), of(dropped)
    assert of(after)[-1].startswith("done "), of(after)
    assert of(loud)[0].endswith("text='nói to'"), of(loud)
    print("reading log: queue, start, done / hung-up per reading; text only on request")


def check_local(tmp: Path) -> None:
    """The in-process engine path (the stub stands in for VieNeu)."""
    out = tmp / "local.wav"
    assert cli.main(["speak", "xin chào", "-o", str(out), "-q"]) == 0
    assert wav_frames(out.read_bytes()) == 2 * WORD, "local WAV length is off"

    assert cli.main(["speak", "xin chào", "-s", "0.75", "-o", str(out), "-q"]) == 0
    slow = wav_frames(out.read_bytes())
    slack = app.STRETCH_FRAME + app.STRETCH_SEARCH + app.STRETCH_HOP
    assert abs(slow - 2 * WORD / 0.75) <= slack, f"0.75x gave {slow} frames"

    assert cli.main(["speak", "xin chào", "-v", "Không Tồn Tại", "-o", str(out), "-q"]) == 2
    assert cli.main(["speak", " ", "-o", str(out), "-q"]) == 2, "empty text accepted"
    print("local: in-process engine, speed, validation -> 2")


def check_gui_host(base: str) -> None:
    """The window's backend answers its own address only: a page that rebinds
    a hostname to 127.0.0.1 sends that hostname, and is refused."""
    port = base.rsplit(":", 1)[1]
    app.set_gui_hosts(int(port))
    try:
        for host, want in ((f"127.0.0.1:{port}", 200), (f"localhost:{port}", 200),
                           (f"evil.example:{port}", 421), ("127.0.0.1:1", 421)):
            assert request(f"{base}/api/status", {"Host": host})[0] == want, host
        assert request(f"{base}/", {"Host": f"evil.example:{port}"})[0] == 421, "page served"
    finally:
        app.set_gui_hosts(None)
    assert request(f"{base}/api/status", {"Host": "evil.example"})[0] == 200, "serve mode refused"
    print("gui host: only 127.0.0.1/localhost on its port; serve mode takes any")


def check_gui_port() -> None:
    """The window's backend keeps one port, so the page's storage keeps one origin;
    a port already taken - by another app or a second window - falls back."""
    assert cli.parse(cli.build_parser(), []).port == cli.GUI_PORT == 8761, \
        "gui no longer defaults to the fixed port"
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        taken = holder.getsockname()[1]
        try:
            app.start_server(taken)
        except OSError:
            pass
        else:
            raise AssertionError("a second server bound a port that is in use")
        server, port, thread = app.start_gui_server(taken)
        try:
            assert port != taken and port > 0, f"no fallback from {taken}: {port}"
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    print("gui port: fixed by default, an occupied port is refused and falls back")


def check_tray() -> None:
    """The tray's menu and its fallback, without putting an icon on screen."""
    import tray

    calls = []
    icon = tray.Tray("http://127.0.0.1:1/", lan_url="http://192.168.0.2:1/",
                     on_show=lambda: calls.append("show"), on_quit=lambda: calls.append("quit"))
    labels = [label for label, _ in icon.menu_items()]
    assert labels == ["Mở cửa sổ", "Mở trong trình duyệt", "Sao chép URL", "Thoát"], labels
    dict(icon.menu_items())["Mở cửa sổ"]()
    assert calls == ["show"], calls

    # The popup menu draws each entry with the icon named by its key, and shows
    # the address that "Sao chép URL" copies.
    page = (ROOT / "web" / "tray.html").read_text(encoding="utf-8")
    for key, _, _ in icon.entries():
        assert f"\n  {key}: '" in page, f"web/tray.html has no icon for {key!r}"
    api = tray._PopupApi(type("Popup", (), {"tray": icon})())
    got = api.info()
    assert got["address"] == "192.168.0.2:1", got
    assert [i["label"] for i in got["items"]] == labels, got

    headless = tray.Tray("http://127.0.0.1:1/", on_quit=lambda: None)
    assert "Mở cửa sổ" not in [label for label, _ in headless.menu_items()], \
        "serve --tray has no window to open"

    # No tray backend (a Linux box without AppIndicator, say) must not take the
    # app down with it: start() reports False and the caller keeps going.
    broken = tray.Tray("http://127.0.0.1:1/", on_quit=lambda: None)
    broken._make_icon = lambda: (_ for _ in ()).throw(RuntimeError("no tray here"))
    assert broken.start() is False, "a failing backend must report False"
    assert broken.run() is False, "a failing backend must report False from run() too"

    p = cli.build_parser()
    args = cli.parse(p, ["serve", "--tray", "--open"])
    assert args.tray and args.open, "serve --tray --open not parsed"
    assert cli.parse(p, ["--no-tray"]).tray is False, "gui --no-tray not parsed"
    assert cli.parse(p, []).tray is True, "the window must use the tray by default"
    print("tray: menu, headless menu, backend failure falls back")


def check_icon(base: str, tmp: Path) -> None:
    """One design everywhere: a black disc, a white ring and five white bars."""
    import icon

    image = icon.image(64)
    assert image.size == (64, 64) and image.mode == "RGBA", (image.size, image.mode)
    px = image.getpixel
    assert px((0, 0))[3] == 0, "the corner outside the disc must be transparent"
    assert px((32, 32))[:3] == (255, 255, 255), "the middle bar is not white"
    assert px((32, 2))[:3] == (255, 255, 255), "the ring is not white"
    assert px((32, 8)) == (0, 0, 0, 255), "the disc between ring and bars is not black"
    white = lambda x: px((x, 32))[:3] == (255, 255, 255)
    runs = sum(1 for x in range(8, 57) if white(x) and not white(x - 1))
    assert runs == 5, f"expected 5 bars across the middle, found {runs}"
    # The title bar takes the 16 px image: there the bars once merged into one blob.
    for size in icon.ICO_SIZES:
        small = icon.image(size)
        row = [small.getpixel((x, size // 2))[:3] == (255, 255, 255) for x in range(size)]
        runs = sum(1 for x in range(size) if row[x] and (x == 0 or not row[x - 1]))
        assert runs == 7, f"{size} px: expected ring + 5 bars + ring across the middle, found {runs} runs"

    ico = tmp / "voice-tts.ico"
    icon.save_ico(ico)
    data = ico.read_bytes()
    assert data[:4] == b"\0\0\1\0", "not an ICO file"
    assert int.from_bytes(data[4:6], "little") >= 4, "the ICO lacks the small sizes"

    status, headers, body = request(f"{base}/favicon.svg")
    assert status == 200, f"/favicon.svg gave {status}"
    assert headers.get("content-type", "").startswith("image/svg+xml"), headers
    svg = body.decode()
    assert svg.count("<circle") == 1 and svg.count("<rect") == 5, svg
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'href="/favicon.svg"' in page, "the page does not use the shared favicon"
    print("icon: disc + ring + 5 bars, ICO with small sizes, /favicon.svg on the page")


def check_lexicon(base: str, tmp: Path) -> None:
    """POST, AP and Board reach the engine in a spelling it reads right."""
    import lexicon
    from vieneu_utils.phonemize_text import normalize_to_chunks_v3_with_gaps,         phonemize_text_with_emotions

    cases = {
        "Gửi POST tới AP trên Board.": "Gửi post tới ây pi trên bo.",
        "GET, PUT, PATCH và DELETE": "get, put, patch và delete",
        "board, BOARD, Board-level": "bo, bo, bo-level",
        "ESP32, esp32, ESP 32, Esp32-S3":
            "i ét pi ba hai, i ét pi ba hai, i ét pi ba hai, i ét pi ba hai-S3",
        "bằng ESP HTTP client, hỏi về esp": "bằng i ét pi HTTP client, hỏi về i ét pi",
        # Whole words only, and what the user already marked as English stays.
        "POSTMAN, APP, onboard, Boards, ap, Post, ESP320, ESPs":
            "POSTMAN, APP, onboard, Boards, ap, Post, ESP320, ESPs",
        "đọc <en>AP board</en> nguyên văn, AP thì không": "đọc <en>AP board</en> nguyên văn, ây pi thì không",
    }
    for text, want in cases.items():
        assert lexicon.apply(text) == want, f"{text!r} -> {lexicon.apply(text)!r}"
    # The table is keyed by the casefolded word: a second entry for "Vout" beside
    # "VOUT" would silently replace the first.
    keys = [w.casefold() for w, _, _ in lexicon.ENTRIES]
    assert len(keys) == len(set(keys)), sorted(k for k in keys if keys.count(k) > 1)
    # The regex matches "Wıfı" case-insensitively, but its casefold is not "wifi":
    # the respelling must come from the alternative that matched, not a lookup.
    wifi = [{"word": "wifi", "say": "oai phai", "matchCase": False}]
    assert lexicon.apply("Bật Wıfı và WIFI", wifi) == "Bật oai phai và oai phai"

    # What the engine's own front end makes of it, model-free: the spelled-out
    # Vietnamese letters (phê ô ét tê) are the bug being fixed.
    def phonemes(text: str) -> str:
        chunks, _ = normalize_to_chunks_v3_with_gaps(lexicon.apply(text), max_chars=256)
        return " ".join(phonemize_text_with_emotions(c) for c in chunks)

    for text, want, wrong in (("Gửi POST lên server", "pˈoʊst", "fˈe ˈo"),
                              ("Gọi GET", "ɡˈɛt", "ɣˈəː2 ˈɛ"),
                              ("Kết nối AP wifi", "ˈəɪ pˈi", "ˈæp"),
                              ("Cắm Board vào", "bˈɔ ", "bˈɔːɹd"),
                              ("Nạp ESP32 xong", "ˈi ˈɛɜt̪ pˈi bˈaː hˈaːj", "fˈe"),
                              ("bằng ESP HTTP client", "ˈi ˈɛɜt̪ pˈi ˈeɪtʃ", "fˈe")):
        got = phonemes(text)
        assert want in got and wrong not in got, f"{text!r}: {got!r}"

    # The paragraph that looped: packed at 256 its first three sentences were one
    # 226-character chunk; at CHUNK_CHARS no chunk holds more than two of them.
    looped = ("có mạng rồi thì gửi dữ liệu. ESP32 S3 có sẵn cảm biến nhiệt độ bên trong, đo "
              "nhiệt độ của chính con chip. đọc giá trị, đóng gói thành chuỗi json, rồi gửi "
              "HTTP post bằng ESP HTTP client. gói tin đi qua router lên server. server trả về "
              "mã hai trăm, nghĩa là đã nhận. lặp lại vài giây một lần là bạn có dữ liệu theo "
              "thời gian.")
    chunks, _ = normalize_to_chunks_v3_with_gaps(lexicon.apply(looped), max_chars=app.CHUNK_CHARS)
    assert max(len(c) for c in chunks) <= app.CHUNK_CHARS, chunks
    assert all(c.count(". ") <= 1 for c in chunks), chunks

    # "normal" (the default) hands the engine the text as typed - POST is
    # spelled as before; "special" respells it first.
    raw = "Gửi POST tới AP trên Board"
    for body, want in (({"text": raw}, raw),
                       ({"text": raw, "pronunciation": "normal"}, raw),
                       ({"text": raw, "pronunciation": "special"}, "Gửi post tới ây pi trên bo")):
        status, _, answer = post(base, body)
        assert status == 200, f"{body}: {status} {answer[:200]!r}"
        assert app._engine.last_text == want, (body, app._engine.last_text)
        assert app._engine.last_max_chars == app.CHUNK_CHARS, app._engine.last_max_chars
    assert post(base, {"text": raw, "pronunciation": "loud"})[0] == 422, "unknown mode accepted"

    # The CLI, in-process and against the server, sends the same choice.
    for flags, want in (([], raw), (["--pronunciation", "special"], "Gửi post tới ây pi trên bo")):
        out = tmp / "pron.wav"
        assert cli.main(["speak", raw, "-o", str(out), "-q", *flags]) == 0
        assert app._engine.last_text == want, ("local", flags, app._engine.last_text)
        code, _, err = run_cli("speak", raw, "-o", str(out), "--server", base, *flags)
        assert code == 0, err
        assert app._engine.last_text == want, ("remote", flags, app._engine.last_text)
    code, _, _ = run_cli("speak", raw, "-o", "-", "--server", base, "--pronunciation", "loud")
    assert code == 2, "an unknown --pronunciation must be a usage error"
    print("lexicon: POST/GET/... as English words, AP as ây pi, Board as bo, whole words only")


TERM_STATES = ("on", "pending", "listen", "known-limit")
# Units sea_g2p leaves as English letters ("pf" is pi ép, "mv" em vi): a sign the
# number in front of them was not read as a quantity.
LETTER_UNITS = {"pf", "nf", "uf", "mv", "kv", "ns", "mh", "uh", "dbm"}
VOWELS = re.compile("[aeiouyɑæɐəɛɜɪɔʊʌɚɝɯɤøœɨᵻᵿɒɵʉ]")


def check_terms() -> None:
    """terms.tsv: each checked term reaches the engine as the row says, and as words
    its front end can say - no spoken punctuation, no syllable without a vowel, no
    unit left as English letters. Model-free: only sea_g2p, the engine's front end."""
    import respell
    from sea_g2p import Normalizer, SEAPipeline

    normalizer, pipeline = Normalizer(lang="vi"), SEAPipeline(lang="vi")
    lines = (ROOT / "terms.tsv").read_text(encoding="utf-8").splitlines()
    # "# " starts a comment; "#define" is a term.
    rows = [line.split("\t") for line in lines if line and not line.startswith("# ")]
    assert rows[0] == ["input", "expected", "domain", "lang", "state"], rows[0]
    counts = dict.fromkeys(TERM_STATES, 0)
    inputs = set()
    for row in rows[1:]:
        assert len(row) == 5, f"terms.tsv: {row} has {len(row)} fields"
        text, want, domain, lang, state = row
        assert state in TERM_STATES, f"terms.tsv: {text!r} has state {state!r}"
        assert text not in inputs, f"terms.tsv: {text!r} twice"
        inputs.add(text)
        counts[state] += 1
        if state != "on":
            continue
        got = respell.special(text)
        assert got == want, f"terms.tsv: {text!r} -> {got!r}, want {want!r}"
        # In a sentence, as the engine meets it: case and context change sea_g2p's mind.
        said = f"ở đây có {got} nhé"
        words = normalizer.normalize(said, punc_norm=False)
        assert "gạch dưới" not in words and "gạch nối" not in words, f"{text!r}: {words!r}"
        assert not LETTER_UNITS & set(words.split()), f"{text!r}: unit as letters in {words!r}"
        for syllable in re.split(r"[\s,.;:!?]+", pipeline.run(said, punc_norm=False)):
            assert not syllable or VOWELS.search(syllable), \
                f"{text!r}: {syllable!r} has no vowel in {pipeline.run(said, punc_norm=False)!r}"
    print("terms: " + ", ".join(f"{n} {state}" for state, n in counts.items()))


def lexicon_call(base: str, method: str, body=None, headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}/api/lexicon", data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def check_lexicon_user(base: str, tmp: Path) -> None:
    """Words the user adds: stored in the data dir, read in special mode only."""
    os.environ["VOICE_TTS_DATA"] = str(tmp / "data")
    try:
        status, state = lexicon_call(base, "GET")
        assert status == 200 and state["user"] == [], state
        assert {"word": "POST", "say": "post", "matchCase": True} in state["builtin"], state

        mine = [{"word": "MQTT", "say": "em kiu ti ti", "matchCase": False},
                {"word": "AP", "say": "a pê", "matchCase": True},
                {"word": "ESP32 S3", "say": "i ét pi ba hai ét ba", "matchCase": False}]
        status, state = lexicon_call(base, "PUT", {"user": mine})
        assert status == 200 and state["user"] == mine, (status, state)
        stored = json.loads((tmp / "data" / "lexicon.json").read_text(encoding="utf-8"))
        assert stored == {"entries": mine}, stored

        # The user's AP replaces the built-in one; the longer ESP32 S3 wins over
        # the built-in ESP32 at the same place; mqtt matches in any case.
        raw = "Gửi mqtt qua AP tới ESP32 S3 và ESP32, POST"
        want = "Gửi em kiu ti ti qua a pê tới i ét pi ba hai ét ba và i ét pi ba hai, post"
        for body, expect in (({"text": raw, "pronunciation": "special"}, want),
                             ({"text": raw}, raw)):
            status, _, answer = post(base, body)
            assert status == 200, answer[:200]
            assert app._engine.last_text == expect, (body, app._engine.last_text)

        for bad in ([{"word": "", "say": "x"}], [{"word": "x", "say": " "}],
                    [{"word": "x" * 65, "say": "x"}], [{"word": "x", "say": "x" * 129}],
                    [{"word": "Dup", "say": "a"}, {"word": "dup", "say": "b"}]):
            status, _ = lexicon_call(base, "PUT", {"user": bad})
            assert status == 400, f"{bad} accepted ({status})"
        assert lexicon_call(base, "PUT", {"user": "MQTT"})[0] == 422, "a non-list accepted"
        assert lexicon_call(base, "GET")[1]["user"] == mine, "a rejected PUT changed the list"

        app.set_token(TOKEN)
        try:
            assert lexicon_call(base, "GET")[0] == 401, "lexicon open without the token"
            assert lexicon_call(base, "PUT", {"user": []})[0] == 401, "PUT without the token"
            good = {"Authorization": f"Bearer {TOKEN}"}
            assert lexicon_call(base, "GET", headers=good)[0] == 200
        finally:
            app.set_token(None)

        # The CLI: in this process it edits the file, with --server the server's.
        out = io.StringIO()
        assert cli.main(["lexicon", "add", "UART", "du a ét", "--local"]) == 0
        assert cli.main(["lexicon", "add", "MQTT", "mờ qui tê tê", "--case", "--local"]) == 0
        with contextlib.redirect_stdout(out):
            assert cli.main(["lexicon", "list", "--json", "--local"]) == 0
        user = json.loads(out.getvalue())["user"]
        assert {"word": "UART", "say": "du a ét", "matchCase": False} in user, user
        assert {"word": "MQTT", "say": "mờ qui tê tê", "matchCase": True} in user, user
        assert len(user) == 4, "add of an existing word must replace it"
        assert cli.main(["lexicon", "remove", "uart", "--local"]) == 0
        assert cli.main(["lexicon", "remove", "uart", "--local"]) == 2, "removing a ghost"
        assert cli.main(["lexicon", "add", "", "x", "--local"]) == 2, "empty word accepted"

        remote = ("--server", base)
        code, _, err = run_cli("lexicon", "add", "I2C", "i hai xi", *remote)
        assert code == 0, err
        assert any(e["word"] == "I2C" for e in lexicon_call(base, "GET")[1]["user"])
        code, stdout, err = run_cli("lexicon", "list", *remote)
        table = stdout.decode("utf-8")
        assert code == 0 and "I2C" in table and "i hai xi" in table and "POST" in table, table
        code, _, err = run_cli("lexicon", "remove", "I2C", *remote)
        assert code == 0, err
        assert not any(e["word"] == "I2C" for e in lexicon_call(base, "GET")[1]["user"])
        code, _, err = run_cli("lexicon", "add", "x", "y" * 129, *remote)
        assert code == 2, f"an over-long spelling over HTTP: exit {code}, {err}"
    finally:
        lexicon_call(base, "PUT", {"user": []})
        del os.environ["VOICE_TTS_DATA"]
    print("lexicon user: data-dir JSON, overrides, longest first, 400/401, CLI local + remote")


def check_install_files() -> None:
    """tool-install.py copies every module of ours that the app imports.

    A new module left off APP_FILES installs fine and then dies on the first
    import, on the Docker host and in the Windows venv alike.
    """
    import ast
    import importlib.util

    spec = importlib.util.spec_from_file_location("tool_install",
                                                  ROOT / "docs/scripts/tool-install.py")
    tool_install = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool_install)
    ours = {f.stem for f in ROOT.glob("*.py")}
    docker_context = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    docker_copy = next(line for line in (ROOT / "Dockerfile").read_text(encoding="utf-8")
                       .splitlines() if line.startswith("COPY app.py")) + " "
    for name in ("app.py", "cli.py", "tray.py", "icon.py"):
        for node in ast.walk(ast.parse((ROOT / name).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            else:
                continue
            for mod in mods:
                if mod in ours:
                    assert f"{mod}.py" in tool_install.APP_FILES,                         f"{name} imports {mod}, which tool-install.py does not copy"
                # The image is the server: no window, so no tray.
                if mod in ours and mod != "tray" and name != "tray.py":
                    assert f"!{mod}.py" in docker_context,                         f"{name} imports {mod}, which .dockerignore keeps out of the image"
                    assert f" {mod}.py " in docker_copy,                         f"{name} imports {mod}, which the Dockerfile does not COPY"
    print("install: tool-install.py and the Docker image carry every module the app imports")


def check_model_precision() -> None:
    """The build fetches and ships the ONNX graphs the app loads, and only those.

    tool-build.py runs before the venv exists, so it cannot import app and names
    the subfolder itself; this keeps the two from drifting apart.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("tool_build", ROOT / "docs/scripts/tool-build.py")
    tool_build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool_build)
    assert app.MODEL_PRECISION == "fp32", f"model precision is {app.MODEL_PRECISION}"
    want = {"fp32": "onnx_update", "int8": "onnx_int8"}[app.MODEL_PRECISION]
    assert tool_build.ONNX_SUBFOLDER == want, \
        f"tool-build.py ships {tool_build.ONNX_SUBFOLDER}, app loads {want}"
    print(f"model: {app.MODEL_PRECISION} ONNX graphs ({want}) in the app and the build")


def check_release_notes() -> None:
    """The release publishes the CHANGELOG section of ``cli.__version__``."""
    def notes(version: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "docs/scripts/tool-build.py"),
                               "--release-notes", version], capture_output=True,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=60)

    proc = notes(cli.__version__)
    body = proc.stdout.decode("utf-8")
    assert proc.returncode == 0, f"no notes for {cli.__version__}: {proc.stderr!r}"
    assert body.strip() and "## [" not in body, f"section of {cli.__version__} is off: {body!r}"
    proc = notes("9.9.9")
    assert proc.returncode == 1, f"a missing version must fail the release, got {proc.returncode}"
    # The repo is private, so the README's version badge is static: a release cut
    # that bumps cli.__version__ has to bump the badge with it.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    badge = f"https://img.shields.io/badge/version-{cli.__version__}-blue"
    assert badge in readme, f"README.md has no version badge for {cli.__version__}"
    print(f"release notes: CHANGELOG section and README badge for {cli.__version__}, "
          "a missing one fails")


def main() -> int:
    # The DSP check needs no engine either; running it here puts it in CI.
    from test_tts import check_stretch

    check_stretch()
    app._engine = StubEngine()
    check_parser()
    check_install_files()
    check_terms()
    check_model_precision()
    check_release_notes()
    check_tray()
    check_gui_port()

    _, port, _ = app.start_server(host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{port}"
    check_token(base)
    check_gui_host(base)
    with tempfile.TemporaryDirectory() as tmp:
        check_remote(base, Path(tmp))
        check_wav_format(base)
        check_turns(base)
        check_reading_log(base)
        check_encode(base, Path(tmp))
        check_lexicon(base, Path(tmp))
        check_lexicon_user(base, Path(tmp))
        check_local(Path(tmp))
        check_icon(base, Path(tmp))
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
