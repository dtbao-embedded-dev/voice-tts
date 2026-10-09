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
    print("token: 401 without, 200 with Bearer or cookie, /?token= sets it")


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

    assert post(base, {"text": "xin chào", "format": "mp3"})[0] == 422, "unknown format accepted"
    assert post(base, {"text": " ", "format": "wav"})[0] == 400, "empty text as wav accepted"
    print("format: wav is a whole 16-bit file with its length, raw stays the default")


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


def check_score() -> None:
    """The verify score: 1 - CER over text reduced to letters and digits."""
    import verify

    ref = "Gửi request lên server, bật ESP32 rồi đọc log."
    assert verify.score(ref, ref) == 1.0, "identical text must score 1.0"
    assert verify.score(ref, "gửi Request lên server bật ESP 32 rồi đọc LOG") == 1.0, \
        "case, spacing and punctuation must not count"
    assert verify.score("Chào bạn", "Chao ban") < 1.0, "a lost diacritic is a real error"
    words = "một hai ba bốn năm sáu bảy tám chín mười " * 4
    one_off = words.replace("tám", "tam", 1)
    assert 0.95 <= verify.score(words, one_off) < 1.0, verify.score(words, one_off)
    assert verify.score(ref, "Hôm nay trời đẹp quá đi thôi.") < 0.5, "unrelated text passes"
    assert verify.score(ref, "") == 0.0, "an empty transcript must score 0"
    assert verify.score("", "") == 1.0, "nothing said, nothing heard"
    assert verify.score("abc", "abcabcabcabc") == 0.0, "the score must not go negative"
    print("score: 1 - CER, case/spacing/punctuation ignored, clamped to 0..1")


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
    print(f"release notes: CHANGELOG section for {cli.__version__}, a missing one fails")


def main() -> int:
    # The DSP check needs no engine either; running it here puts it in CI.
    from test_tts import check_stretch

    check_stretch()
    app._engine = StubEngine()
    check_parser()
    check_score()
    check_release_notes()
    check_tray()

    _, port, _ = app.start_server(host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{port}"
    check_token(base)
    with tempfile.TemporaryDirectory() as tmp:
        check_remote(base, Path(tmp))
        check_wav_format(base)
        check_local(Path(tmp))
        check_icon(base, Path(tmp))
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
