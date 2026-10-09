"""Fast checks for the CLI, the server options and the token guard.

No model is loaded: a stub engine stands in for VieNeu, so this runs in seconds
and is what CI runs, together with the time-stretch check from ``test_tts.py``.
The real-model path is ``test_tts.py`` itself.

    python test_cli.py
"""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave
from pathlib import Path

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

    def infer_stream(self, text, voice=None):
        self.last_text = text
        # A 220 Hz tone, 0.1 s per word, in a few chunks - enough to be audible
        # and to be told apart from silence.
        n = int(app.SAMPLE_RATE * 0.1 * max(1, len(text.split())))
        t = np.arange(n) / app.SAMPLE_RATE
        tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        yield from np.array_split(tone, 4)


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
    print("format: wav is a whole 16-bit file with its length, raw stays the default")


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
        # Whole words only, and what the user already marked as English stays.
        "POSTMAN, APP, onboard, Boards, ap, Post, ESP320, ESP":
            "POSTMAN, APP, onboard, Boards, ap, Post, ESP320, ESP",
        "đọc <en>AP board</en> nguyên văn, AP thì không": "đọc <en>AP board</en> nguyên văn, ây pi thì không",
    }
    for text, want in cases.items():
        assert lexicon.apply(text) == want, f"{text!r} -> {lexicon.apply(text)!r}"

    # What the engine's own front end makes of it, model-free: the spelled-out
    # Vietnamese letters (phê ô ét tê) are the bug being fixed.
    def phonemes(text: str) -> str:
        chunks, _ = normalize_to_chunks_v3_with_gaps(lexicon.apply(text), max_chars=256)
        return " ".join(phonemize_text_with_emotions(c) for c in chunks)

    for text, want, wrong in (("Gửi POST lên server", "pˈoʊst", "fˈe ˈo"),
                              ("Gọi GET", "ɡˈɛt", "ɣˈəː2 ˈɛ"),
                              ("Kết nối AP wifi", "ˈəɪ pˈi", "ˈæp"),
                              ("Cắm Board vào", "bˈɔ ", "bˈɔːɹd"),
                              ("Nạp ESP32 xong", "ˈi ˈɛɜt̪ pˈi bˈaː hˈaːj", "fˈe")):
        got = phonemes(text)
        assert want in got and wrong not in got, f"{text!r}: {got!r}"

    # "normal" (the default) hands the engine the text as typed - POST is
    # spelled as before; "special" respells it first.
    raw = "Gửi POST tới AP trên Board"
    for body, want in (({"text": raw}, raw),
                       ({"text": raw, "pronunciation": "normal"}, raw),
                       ({"text": raw, "pronunciation": "special"}, "Gửi post tới ây pi trên bo")):
        status, _, answer = post(base, body)
        assert status == 200, f"{body}: {status} {answer[:200]!r}"
        assert app._engine.last_text == want, (body, app._engine.last_text)
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
    check_release_notes()
    check_tray()

    _, port, _ = app.start_server(host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{port}"
    check_token(base)
    with tempfile.TemporaryDirectory() as tmp:
        check_remote(base, Path(tmp))
        check_wav_format(base)
        check_encode(base, Path(tmp))
        check_lexicon(base, Path(tmp))
        check_local(Path(tmp))
        check_icon(base, Path(tmp))
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
