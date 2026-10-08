"""Fast checks for the CLI, the server options and the token guard.

No model is loaded: a stub engine stands in for VieNeu, so this runs in seconds
and is what CI runs. The real-model path is ``test_tts.py``.

    python test_cli.py
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

import numpy as np

import app
import cli

TOKEN = "s3cret-token"


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


def main() -> int:
    app._engine = StubEngine()
    check_parser()

    _, port, _ = app.start_server(host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{port}"
    check_token(base)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
