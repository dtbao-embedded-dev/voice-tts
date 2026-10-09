"""Command line for Voice TTS.

    voice-tts                       # the desktop window (default)
    voice-tts serve [--host H]      # the HTTP backend only
    voice-tts speak "Xin chào"      # read text aloud, or -o out.wav to save it
    voice-tts voices | status       # list the voices, ask a server how it is
    voice-tts --help                # every subcommand; `voice-tts <cmd> -h` for its flags

This module imports nothing outside the standard library at load time. The
backend (`app`, with numpy, FastAPI and the engine) is imported only by the
commands that run it, so the remote client - anything given ``--server`` -
works on any Python 3.10+ without the app's dependencies installed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave
from array import array

__version__ = "0.9.0"

DEFAULT_PORT = 8760
# The window's own backend. A fixed port keeps the page at one origin, and the
# settings and history the page stores are keyed by it.
GUI_PORT = 8761
ENV_TOKEN = "VOICE_TTS_TOKEN"
ENV_SERVER = "VOICE_TTS_SERVER"
LOCAL_SERVER = f"http://127.0.0.1:{DEFAULT_PORT}"
# What -o can write. wav is built here; mp3 and ogg are encoded by the backend,
# in this process or on the server, from the 16-bit samples.
FORMATS = ("wav", "mp3", "ogg")
EXTENSIONS = {".mp3": "mp3", ".ogg": "ogg", ".oga": "ogg"}

# POSIX players that take raw float32 mono on stdin, so playback starts with the
# first chunk instead of after the whole text. First one on PATH wins.
STREAM_PLAYERS = (
    ("paplay", ["--raw", "--format=float32le", "--rate={rate}", "--channels=1"]),
    ("pw-play", ["--format=f32", "--rate={rate}", "--channels=1", "-"]),
    ("aplay", ["-q", "-t", "raw", "-f", "FLOAT_LE", "-r", "{rate}", "-c", "1"]),
)


class CliError(Exception):
    """A failure to report in one line and exit with ``code`` (1 runtime, 2 usage)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def eprint(*parts) -> None:
    print(*parts, file=sys.stderr, flush=True)


# --------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice-tts",
        description="Read mixed Vietnamese/English text aloud (VieNeu-TTS v3 Turbo).",
        epilog=f"Environment: {ENV_SERVER} (default --server), {ENV_TOKEN} (default --token).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    gui = sub.add_parser("gui", help="open the desktop window (default)")
    gui.add_argument("--port", type=int, default=GUI_PORT,
                     help="loopback port for the backend; any free one if it is taken "
                          "(default: %(default)s)")
    gui.add_argument("--tray", action=argparse.BooleanOptionalAction, default=True,
                     help="minimize and close hide the window into the system tray; "
                          "--no-tray makes close quit (default: on)")

    serve = sub.add_parser("serve", help="run the HTTP backend without a window")
    serve.add_argument("--host", default="127.0.0.1",
                       help="address to bind; 0.0.0.0 serves the LAN (default: %(default)s)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT,
                       help="port to bind (default: %(default)s)")
    serve.add_argument("--token", default=os.environ.get(ENV_TOKEN),
                       help=f"require this token on /api (default: ${ENV_TOKEN}, else open)")
    serve.add_argument("--log-level", default="info",
                       choices=("critical", "error", "warning", "info", "debug"),
                       help="uvicorn log level (default: %(default)s)")
    serve.add_argument("--tray", action="store_true",
                       help="show a system tray icon; its menu opens the page and quits")
    serve.add_argument("--open", action="store_true", help="open the page in the browser")

    speak = sub.add_parser(
        "speak", help="read text aloud or save it as audio",
        description="Read text aloud, or save it. Text comes from the arguments, from "
                    "-f FILE, or from stdin ('-' or a pipe). Without -o it plays; with "
                    "-o it saves and plays only if --play is given.")
    speak.add_argument("text", nargs="*", help="text to read; '-' reads stdin")
    speak.add_argument("-f", "--file", help="read the text from FILE ('-' for stdin), UTF-8")
    speak.add_argument("-v", "--voice", help="preset voice name (default: the engine's default)")
    speak.add_argument("-s", "--speed", type=float, default=1.0,
                       help="reading speed 0.5-2.0, pitch unchanged (default: %(default)s)")
    speak.add_argument("-o", "--output", metavar="PATH",
                       help="write audio to PATH ('-' for stdout) instead of playing it")
    speak.add_argument("--play", action=argparse.BooleanOptionalAction, default=None,
                       help="play through the speakers (default: on unless -o is given)")
    speak.add_argument("--raw", action="store_true",
                       help="with -o: raw float32 LE mono 48 kHz instead of a 16-bit WAV")
    speak.add_argument("--format", choices=FORMATS,
                       help="file format for -o (default: from the file name's extension, "
                            "else wav)")
    speak.add_argument("--pronunciation", choices=("normal", "special"), default="normal",
                       help="normal reads the text as typed; special respells words the "
                            "engine gets wrong first - POST as 'post', AP as 'ây pi', "
                            "Board as 'bo', ESP32 as 'i ét pi ba hai' (default: %(default)s)")
    add_client_flags(speak, local=True)
    speak.add_argument("-q", "--quiet", action="store_true", help="no progress or summary on stderr")

    voices = sub.add_parser("voices", help="list the preset voices")
    voices.add_argument("--json", action="store_true", help="print the /api/voices JSON")
    add_client_flags(voices, local=True)

    lex = sub.add_parser(
        "lexicon", help="list or edit the words the special pronunciation respells",
        description="The user's own words, read in --pronunciation special on top of the "
                    "built-in ones. Without --server this edits the file in the data dir "
                    "($VOICE_TTS_DATA); with it, the server's list.")
    lex_sub = lex.add_subparsers(dest="action", metavar="ACTION", required=True)
    lex_list = lex_sub.add_parser("list", help="the built-in words and yours")
    lex_list.add_argument("--json", action="store_true", help="print the /api/lexicon JSON")
    lex_add = lex_sub.add_parser("add", help="add a word, or change how one is read")
    lex_add.add_argument("word", help="the word as written, e.g. MQTT")
    lex_add.add_argument("say", help="how to read it, e.g. 'em kiu ti ti'")
    lex_add.add_argument("--case", action="store_true",
                         help="match this exact case only (default: any case)")
    lex_remove = lex_sub.add_parser("remove", help="remove one of your words")
    lex_remove.add_argument("word")
    for cmd in (lex_list, lex_add, lex_remove):
        add_client_flags(cmd, local=True)

    status = sub.add_parser("status", help="ask a server whether its model is ready")
    status.add_argument("--json", action="store_true", help="print the /api/status JSON")
    status.add_argument("--wait", type=float, default=0, metavar="SECONDS",
                        help="poll until ready or SECONDS pass (default: ask once)")
    add_client_flags(status, local=False)
    return parser


def add_client_flags(cmd: argparse.ArgumentParser, local: bool) -> None:
    where = "run the engine in this process" if local else LOCAL_SERVER
    cmd.add_argument("--server", metavar="URL", default=os.environ.get(ENV_SERVER),
                     help=f"use the server at URL (default: ${ENV_SERVER}, else {where})")
    cmd.add_argument("--token", default=os.environ.get(ENV_TOKEN),
                     help=f"token for --server (default: ${ENV_TOKEN})")
    cmd.add_argument("--timeout", type=float, default=600,
                     help="seconds to wait on the server (default: %(default)s)")
    if local:
        cmd.add_argument("--local", action="store_true",
                         help=f"ignore ${ENV_SERVER} and run the engine in this process")


def parse(parser: argparse.ArgumentParser, argv: list[str]) -> argparse.Namespace:
    """Parse ``argv``, defaulting to ``gui`` and keeping the old ``--no-window``."""
    argv = list(argv)
    if "--no-window" in argv and (not argv or argv[0].startswith("-")):
        # The pre-subcommand spelling, in any position: backend only, port 8760
        # unless given.
        argv.remove("--no-window")
        argv.insert(0, "serve")
    elif not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "gui")
    args = parser.parse_args(argv)
    if args.command == "speak" and args.raw and not args.output:
        parser.error("--raw needs -o: it describes the file, not the playback")
    if args.command == "speak" and args.raw and args.format:
        parser.error("--raw and --format both describe the file; give one")
    return args


# --------------------------------------------------------------------- server

def server_url(args: argparse.Namespace) -> str | None:
    """The server to talk to, or None to run the engine in this process."""
    url = args.server
    if getattr(args, "local", False):
        url = None
    elif url is None and args.command == "status":
        url = LOCAL_SERVER
    if url and "://" not in url:
        url = f"http://{url}"
    return url.rstrip("/") if url else None


def call(args: argparse.Namespace, path: str, body: dict | None = None,
         raw: bytes | None = None, method: str | None = None):
    """Open ``path`` on the server; translate failures into ``CliError``.

    ``body`` goes as JSON, ``raw`` as octets; neither makes it a GET.
    """
    url = server_url(args) + path
    headers = {}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    elif raw is not None:
        headers["Content-Type"] = "application/octet-stream"
        data = raw
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        return urllib.request.urlopen(req, timeout=args.timeout)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc).get("detail", exc.reason)
        except (ValueError, AttributeError):
            detail = exc.reason
        if exc.code == 401:
            raise CliError(1, f"server refused the token ({detail}); "
                              f"pass --token or set {ENV_TOKEN}") from None
        if exc.code == 400:
            raise CliError(2, str(detail)) from None
        raise CliError(1, f"server error {exc.code}: {detail}") from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise CliError(1, f"cannot reach {url}: {reason}") from None


def get_json(args: argparse.Namespace, path: str) -> dict:
    with call(args, path) as resp:
        return json.load(resp)


def remote_samples(resp):
    """Yield the body as whole float32 samples, however the bytes arrive."""
    rest = b""
    with resp:
        while True:
            try:
                block = resp.read1(65536)
            except OSError as exc:
                raise CliError(1, f"stream broke off: {exc}") from None
            if not block:
                break
            block = rest + block
            cut = len(block) - len(block) % 4
            rest = block[cut:]
            if cut:
                yield block[:cut]


# --------------------------------------------------------------------- audio

def f32_to_i16(data: bytes) -> bytes:
    """Float32 LE samples to clipped 16-bit LE PCM, standard library only."""
    floats = array("f")
    floats.frombytes(data)
    if sys.byteorder == "big":
        floats.byteswap()
    pcm = array("h", (32767 if x >= 1.0 else -32767 if x <= -1.0 else int(x * 32767)
                      for x in floats))
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm.tobytes()


class WavSink:
    """A 16-bit mono WAV written as the samples arrive.

    ``wave`` patches the length into the header on close, which needs a seek;
    stdout may be a pipe, so there the PCM is held until the end and written
    with its length known up front. Only a file we opened counts as seekable:
    a Windows pipe answers ``seekable()`` with True, and the "patch" then lands
    as stray bytes after the audio.
    """

    def __init__(self, fileobj, rate: int, owned: bool) -> None:
        self.fileobj, self.rate, self.owned = fileobj, rate, owned
        self.held = bytearray()
        self.wav = self._open() if owned else None

    def _open(self):
        wav = wave.open(self.fileobj, "wb")
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(self.rate)
        return wav

    def write(self, data: bytes) -> None:
        pcm = f32_to_i16(data)
        if self.wav:
            self.wav.writeframes(pcm)
        else:
            self.held += pcm

    def close(self) -> None:
        if not self.wav:
            self.wav = self._open()
            self.wav.setnframes(len(self.held) // 2)
            self.wav.writeframes(bytes(self.held))
        self.wav.close()
        self.fileobj.flush()
        if self.owned:
            self.fileobj.close()

    def abort(self) -> None:
        if self.owned:
            self.fileobj.close()


class EncodedSink:
    """An MP3 or OGG file: the samples are held, then encoded once complete.

    ``encode`` turns the float32 bytes into the file - in this process through
    the backend, or on the server through ``/api/encode`` - so the remote client
    needs no encoder of its own.
    """

    def __init__(self, fileobj, owned: bool, encode) -> None:
        self.fileobj, self.owned, self.encode = fileobj, owned, encode
        self.held = bytearray()

    def write(self, data: bytes) -> None:
        self.held += data

    def close(self) -> None:
        self.fileobj.write(self.encode(bytes(self.held)))
        self.fileobj.flush()
        if self.owned:
            self.fileobj.close()

    def abort(self) -> None:
        if self.owned:
            self.fileobj.close()


class RawSink:
    def __init__(self, fileobj, owned: bool) -> None:
        self.fileobj, self.owned = fileobj, owned

    def write(self, data: bytes) -> None:
        self.fileobj.write(data)

    def close(self) -> None:
        self.fileobj.flush()
        if self.owned:
            self.fileobj.close()

    abort = close


class Player:
    """Play through the speakers.

    POSIX: stream into the first player found on PATH as the audio arrives.
    Windows and macOS have no such player in the base system, so the audio is
    collected into a temporary WAV and played when the text is complete.
    """

    def __init__(self, rate: int) -> None:
        self.proc = self.wav = None
        if sys.platform in ("win32", "darwin"):
            handle = tempfile.NamedTemporaryFile(prefix="voice-tts-", suffix=".wav", delete=False)
            self.path = handle.name
            self.wav = WavSink(handle, rate, owned=True)
            return
        for exe, argv in STREAM_PLAYERS:
            path = shutil.which(exe)
            if path:
                self.proc = subprocess.Popen([path, *(a.format(rate=rate) for a in argv)],
                                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
                return
        raise CliError(1, "no audio player found (paplay, pw-play or aplay); "
                          "install one or save the audio with -o FILE")

    def write(self, data: bytes) -> None:
        if self.wav:
            self.wav.write(data)
            return
        try:
            self.proc.stdin.write(data)
        except BrokenPipeError:
            raise CliError(1, "the audio player exited early") from None

    def close(self) -> None:
        if self.proc:
            self.proc.stdin.close()
            self.proc.wait()
            return
        self.wav.close()
        try:
            if sys.platform == "win32":
                import winsound

                winsound.PlaySound(self.path, winsound.SND_FILENAME)
            else:
                subprocess.run(["afplay", self.path], check=False)
        finally:
            os.remove(self.path)

    def abort(self) -> None:
        if self.proc:
            self.proc.kill()
            return
        self.wav.abort()
        os.remove(self.path)


def output_format(args: argparse.Namespace) -> str:
    """``--format``, else the extension of ``-o``, else wav."""
    if args.format:
        return args.format
    return EXTENSIONS.get(os.path.splitext(args.output or "")[1].lower(), "wav")


def open_output(path: str, rate: int, raw: bool, stdout, fmt: str = "wav", encode=None):
    owned = path != "-"
    if owned:
        try:
            handle = open(path, "wb")
        except OSError as exc:
            raise CliError(1, f"cannot write {path}: {exc.strerror}") from None
    else:
        handle = stdout
    if raw:
        return RawSink(handle, owned)
    if fmt != "wav":
        return EncodedSink(handle, owned, encode)
    return WavSink(handle, rate, owned)


# --------------------------------------------------------------------- commands

def read_text(args: argparse.Namespace) -> str:
    def stdin_text() -> str:
        return sys.stdin.buffer.read().decode("utf-8-sig")

    if args.file and args.text:
        raise CliError(2, "give the text as arguments or with -f, not both")
    if args.file == "-" or args.text == ["-"]:
        return stdin_text()
    if args.file:
        try:
            with open(args.file, encoding="utf-8-sig") as handle:
                return handle.read()
        except OSError as exc:
            raise CliError(1, f"cannot read {args.file}: {exc.strerror}") from None
    if args.text:
        return " ".join(args.text)
    if not sys.stdin.isatty():
        return stdin_text()
    raise CliError(2, "no text: give it as arguments, with -f FILE, or on stdin")


def local_engine(quiet: bool):
    """Import the backend and load the model, with a note while that takes."""
    if not quiet:
        eprint("loading the model ...")
    import app

    try:
        app.engine()
    except Exception as exc:
        raise CliError(1, f"model failed to load: {type(exc).__name__}: {exc}") from None
    return app


def cmd_speak(args: argparse.Namespace) -> int:
    text = read_text(args)
    play = args.play if args.play is not None else args.output is None
    stdout = sys.stdout.buffer
    if args.output == "-" and stdout.isatty():
        raise CliError(2, "refusing to write audio to a terminal; redirect it or use -o FILE")
    server = server_url(args)
    fmt = output_format(args)

    # Whatever a library prints must not land in a WAV going to stdout.
    with contextlib.redirect_stdout(sys.stderr):
        if server:
            if not text.strip():
                raise CliError(2, "no text to read")
            body = {"text": text, "voice": args.voice, "speed": args.speed,
                    "pronunciation": args.pronunciation}
            resp = call(args, "/api/tts/stream", body)
            rate = int(resp.headers.get("X-Sample-Rate", 48000))
            voice = args.voice or "default voice"
            chunks = remote_samples(resp)

            def encode(data: bytes) -> bytes:
                with call(args, f"/api/encode?format={fmt}", raw=f32_to_i16(data)) as answer:
                    return answer.read()
        else:
            app = local_engine(args.quiet)
            try:
                voice, samples = app.synthesize(text, args.voice, args.speed,
                                                args.pronunciation)
            except ValueError as exc:
                raise CliError(2, str(exc)) from None
            rate = app.SAMPLE_RATE
            chunks = (chunk.tobytes() for chunk in samples)

            def encode(data: bytes) -> bytes:
                import numpy as np

                return app.encode_audio(np.frombuffer(data, dtype=np.float32), fmt)

        sinks = []
        try:
            if args.output:
                sinks.append(open_output(args.output, rate, args.raw, stdout, fmt, encode))
            if play:
                sinks.append(Player(rate))
            samples_out = 0
            for data in chunks:
                samples_out += len(data) // 4
                for sink in sinks:
                    sink.write(data)
        except BaseException:
            for sink in sinks:
                with contextlib.suppress(Exception):
                    sink.abort()
            raise
        for sink in sinks:
            sink.close()

    if not args.quiet:
        where = f" -> {args.output}" if args.output and args.output != "-" else ""
        eprint(f"{voice}: {samples_out / rate:.2f} s at {args.speed}x{where}")
    return 0


def cmd_voices(args: argparse.Namespace) -> int:
    if server_url(args):
        info = get_json(args, "/api/voices")
    else:
        app = local_engine(quiet=args.json)
        with contextlib.redirect_stdout(sys.stderr):
            info = {"voices": app.preset_voices(), "default": app.default_voice(),
                    "sampleRate": app.SAMPLE_RATE, "maxChars": app.MAX_CHARS}
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    width = max(len(v["name"]) for v in info["voices"])
    gender = max(len(v["gender"]) for v in info["voices"])
    for v in info["voices"]:
        mark = "*" if v["name"] == info["default"] else " "
        star = "+" if v.get("featured") else " "
        print(f"{mark}{star} {v['name']:<{width}}  {v['region']:<5}  {v['gender']:<{gender}}  "
              f"{v['description']}")
    print("\n* default   + featured")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    import time

    deadline = time.monotonic() + args.wait
    while True:
        try:
            state = get_json(args, "/api/status")
        except CliError:
            if time.monotonic() >= deadline:
                raise
            state = {"state": "unreachable"}
        if state["state"] != "loading" and state["state"] != "unreachable":
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(1)
    if args.json:
        print(json.dumps(state, ensure_ascii=False))
    else:
        print(state["state"] + (f": {state['detail']}" if state.get("detail") else ""))
    return 0 if state["state"] == "ready" else 1


def cmd_lexicon(args: argparse.Namespace) -> int:
    import lexicon

    if server_url(args):
        def load() -> list[dict]:
            return get_json(args, "/api/lexicon")["user"]

        def store(user: list[dict]) -> None:
            call(args, "/api/lexicon", {"user": user}, method="PUT").close()

        def builtin() -> list[dict]:
            return get_json(args, "/api/lexicon")["builtin"]
    else:
        def load() -> list[dict]:
            try:
                return lexicon.load_user()
            except ValueError as exc:
                raise CliError(1, str(exc)) from None

        def store(user: list[dict]) -> None:
            try:
                lexicon.save_user(user)
            except ValueError as exc:
                raise CliError(2, str(exc)) from None

        builtin = lexicon.builtin

    user = load()
    if args.action == "list":
        if args.json:
            print(json.dumps({"builtin": builtin(), "user": user}, ensure_ascii=False, indent=2))
            return 0
        rows = [(e, "") for e in user] + [(e, "built-in") for e in builtin()]
        width = max(len(e["word"]) for e, _ in rows)
        say = max(len(e["say"]) for e, _ in rows)
        for e, note in rows:
            case = "case" if e["matchCase"] else "    "
            print(f"{e['word']:<{width}}  {e['say']:<{say}}  {case}  {note}".rstrip())
        return 0

    key = args.word.strip().casefold()
    kept = [e for e in user if e["word"].casefold() != key]
    if args.action == "add":
        store(kept + [{"word": args.word, "say": args.say, "matchCase": args.case}])
    else:
        if len(kept) == len(user):
            raise CliError(2, f"'{args.word}' is not one of your words")
        store(kept)
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    import app

    app.run_gui(args.port, tray=args.tray)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import app

    app.set_token(args.token)
    if args.host not in ("127.0.0.1", "localhost") and not args.token:
        eprint(f"warning: serving {args.host} with no token - anyone on the network can use it")
    app.serve(args.host, args.port, args.log_level, tray=args.tray, open_browser=args.open)
    return 0


HANDLERS = {"gui": cmd_gui, "serve": cmd_serve, "speak": cmd_speak,
            "voices": cmd_voices, "status": cmd_status, "lexicon": cmd_lexicon}


def main(argv: list[str] | None = None) -> int:
    # pythonw, the Start Menu shortcut and a windowed build run with no console:
    # stdout/stderr are None there, and the first print or log line would raise.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    # Voice names and server messages are Vietnamese; a redirected stream on
    # Windows would otherwise be cp1252 and fail on the first diacritic.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parse(parser, sys.argv[1:] if argv is None else argv)
    try:
        return HANDLERS[args.command](args)
    except CliError as exc:
        eprint(f"voice-tts: {exc}")
        return exc.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
