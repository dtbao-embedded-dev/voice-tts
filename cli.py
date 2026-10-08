"""Command line for Voice TTS.

    voice-tts                       # the desktop window (default)
    voice-tts serve [--host H]      # the HTTP backend only
    voice-tts --help                # every subcommand; `voice-tts <cmd> -h` for its flags

This module imports nothing outside the standard library at load time. The
backend (`app`, with numpy, FastAPI and the engine) is imported only by the
commands that run it, so the remote client works on any Python 3.10+ without
the app's dependencies installed.
"""

from __future__ import annotations

import argparse
import os
import sys

__version__ = "0.4.0"

DEFAULT_PORT = 8760
ENV_TOKEN = "VOICE_TTS_TOKEN"

COMMANDS = ("gui", "serve")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice-tts",
        description="Read mixed Vietnamese/English text aloud (VieNeu-TTS v3 Turbo).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    gui = sub.add_parser("gui", help="open the desktop window (default)")
    gui.add_argument("--port", type=int, default=0,
                     help="loopback port for the backend (default: any free port)")

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
    return parser


def parse(parser: argparse.ArgumentParser, argv: list[str]) -> argparse.Namespace:
    """Parse ``argv``, defaulting to ``gui`` and keeping the old ``--no-window``."""
    argv = list(argv)
    if argv and argv[0] == "--no-window":
        # The pre-subcommand spelling: backend only, port 8760 unless given.
        argv[0] = "serve"
    elif not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "gui")
    return parser.parse_args(argv)


def cmd_gui(args: argparse.Namespace) -> int:
    import app

    app.run_gui(args.port)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import app

    app.set_token(args.token)
    if args.host not in ("127.0.0.1", "localhost") and not args.token:
        print(f"warning: serving {args.host} with no token - anyone on the network can use it",
              file=sys.stderr)
    app.serve(args.host, args.port, args.log_level)
    return 0


HANDLERS = {"gui": cmd_gui, "serve": cmd_serve}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parse(parser, sys.argv[1:] if argv is None else argv)
    return HANDLERS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
