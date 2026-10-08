#!/usr/bin/env python3
"""Build/run helper for Voice TTS. Standard library only - run it with any Python.

    python docs/scripts/tool-build.py             # set up (if needed) and launch
    python docs/scripts/tool-build.py --check     # set up and run the smoke test
    python docs/scripts/tool-build.py --package   # set up and build dist/VoiceTTS
    python docs/scripts/tool-build.py --setup     # set up only

    python docs/scripts/tool-build.py --package --server-only   # dist/voice-tts: console,
                                                                # server + CLI, no window
    python docs/scripts/tool-build.py --smoke dist/voice-tts    # run a build offline as a
                                                                # server and read a sentence
    python docs/scripts/tool-build.py --release-notes 0.5.0     # that version's CHANGELOG
                                                                # section, for the release

Every step is skipped when it is already done, so the second run is the fast one.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQS = ROOT / "requirements-desktop.txt"  # pulls in requirements.txt with -r
REQ_FILES = (ROOT / "requirements.txt", REQS)
STAMP = VENV / ".requirements-sha256"
# The engine resolves its weights from two Hub repos - the backbone and the audio
# codec - and needs both. Read off vieneu's _V3_REPO / _CODEC_REPO; verify_stage()
# is what catches this list going stale after an upgrade.
MODEL_REPOS = (
    "models--pnnbao-ump--VieNeu-TTS-v3-Turbo",
    "models--OpenMOSS-Team--MOSS-Audio-Tokenizer-Nano-ONNX",
)
HF_HUB = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub"
# Staged outside build/ and dist/: PyInstaller's --clean wipes both.
MODEL_STAGE = VENV / "model-bundle"

# PyInstaller cannot see these through vieneu's lazy imports.
COLLECT = ["vieneu", "onnxruntime", "sea_g2p", "kaldi_native_fbank", "soxr", "soundfile"]
# pystray picks its backend module by name at runtime; name the Windows one.
HIDDEN = ["pystray._win32"] if os.name == "nt" else []
# vieneu ships a Gradio demo we never import; it would double the bundle.
EXCLUDE = ["gradio", "gradio_client", "matplotlib", "tkinter", "IPython"]
# A server-only build has no window and no tray.
EXCLUDE_SERVER = ["webview", "pystray", "tray"]
CHANGELOG = ROOT / "CHANGELOG.md"
SMOKE_TEXT = "Xin chào, bản đóng gói này chạy offline và đọc được tiếng Việt lẫn English."


def run(cmd: list[str], **kw) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def step(label: str):
    print(f"  {label} ... ", end="", flush=True)
    return time.perf_counter()


def done(t0: float, note: str = "") -> None:
    print(f"{time.perf_counter() - t0:.1f}s {note}".rstrip(), flush=True)


def ensure_venv() -> None:
    if PY.exists():
        print("  venv ... already there", flush=True)
        return
    t0 = step("venv")
    # The wheels the engine needs (kaldi-native-fbank) exist for 3.12; a newer
    # default Python falls back to a source build that fails without MSVC/CMake.
    launcher = shutil.which("py")
    if sys.version_info[:2] == (3, 12) or not launcher:
        cmd = [sys.executable, "-m", "venv", str(VENV)]
    else:
        # which() keeps the PATHEXT case, e.g. "py.EXE" on the GitHub runners.
        cmd = [launcher, "-3.12", "-m", "venv", str(VENV)]
    try:
        run(cmd)
    except subprocess.CalledProcessError:
        run([sys.executable, "-m", "venv", str(VENV)])  # no py launcher / no 3.12
    done(t0)


def ensure_deps(server_only: bool = False) -> None:
    files = REQ_FILES[:1] if server_only else REQ_FILES
    digest = hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()
    if STAMP.exists() and STAMP.read_text().strip() == digest:
        print("  deps ... unchanged", flush=True)
        return
    t0 = step("deps")
    run([str(PY), "-m", "pip", "install", "--upgrade", "--quiet", "pip"])
    run([str(PY), "-m", "pip", "install", "--quiet", "-r", str(files[-1])])
    STAMP.write_text(digest)
    done(t0)


def ensure_model() -> None:
    """Pull the weights now, so the first launch is not a silent 30 s wait."""
    if all((HF_HUB / repo).is_dir() for repo in MODEL_REPOS):
        print("  model ... cached", flush=True)
        return
    t0 = step("model (first download, this takes a while)")
    run([str(PY), "-c", "import app; app.engine()"], env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    done(t0)


def setup(server_only: bool = False) -> None:
    print("Voice TTS build" + (" (server only)" if server_only else ""), flush=True)
    ensure_venv()
    ensure_deps(server_only)
    ensure_model()


def stage_model() -> Path:
    """Copy the revision each repo currently points at into ``MODEL_STAGE``.

    The HuggingFace cache keeps every revision it has ever seen; only the one
    ``refs/main`` names goes into the exe, which is a third of what is on disk.
    On Windows ``blobs/`` stays empty and the snapshot holds the real files, so
    a plain copy is all an offline ``hf_hub_download`` needs to resolve.
    """
    if MODEL_STAGE.exists():
        shutil.rmtree(MODEL_STAGE)
    for repo in MODEL_REPOS:
        src = HF_HUB / repo
        if not src.is_dir():
            sys.exit(f"ERROR: model cache missing at {src} - run --setup first")
        revision = (src / "refs" / "main").read_text().strip()
        out = MODEL_STAGE / "hub" / repo
        (out / "refs").mkdir(parents=True)
        (out / "refs" / "main").write_text(revision)
        shutil.copytree(src / "snapshots" / revision, out / "snapshots" / revision)
    return MODEL_STAGE


def verify_stage(stage: Path) -> None:
    """Load the engine against the staged cache alone, with the network off.

    This is the same situation the packaged exe is in, and it costs seconds
    against the minutes PyInstaller spends - so a missing repo surfaces here
    rather than on the machine the exe was carried to.
    """
    run([str(PY), "-c", "import app; app.engine()"],
        env={**os.environ, "HF_HOME": str(stage), "HF_HUB_OFFLINE": "1",
             "PYTHONIOENCODING": "utf-8"})


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def exe_path(server_only: bool) -> Path:
    name = "voice-tts" if server_only else "VoiceTTS"
    return ROOT / "dist" / (f"{name}.exe" if os.name == "nt" else name)


def package(server_only: bool = False) -> Path:
    t0 = step("pyinstaller")
    run([str(PY), "-m", "pip", "install", "--quiet", "pyinstaller"])
    done(t0)

    t0 = step("model")
    stage = stage_model()
    done(t0, f"{dir_size(stage) / 1e6:.0f} MB")

    t0 = step("offline check")
    verify_stage(stage)
    done(t0)

    exe = exe_path(server_only)
    t0 = step("bundle (one file, this takes a while)")
    # The desktop build is windowed: no console flashes up behind the window.
    # The server build is a console program - it is run from a shell.
    cmd = [str(PY), "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
           "--console" if server_only else "--windowed",
           "--name", exe.stem,
           "--add-data", f"web{os.pathsep}web",
           "--add-data", f"{stage}{os.pathsep}hf"]
    for mod in COLLECT:
        cmd += ["--collect-all", mod]
    for mod in [] if server_only else HIDDEN:
        cmd += ["--hidden-import", mod]
    for mod in EXCLUDE + (EXCLUDE_SERVER if server_only else []):
        cmd += ["--exclude-module", mod]
    cmd.append("app.py")
    run(cmd)
    done(t0)

    if not exe.exists():
        sys.exit(f"ERROR: PyInstaller finished but {exe} is missing")
    print(f"\n{exe}  ({exe.stat().st_size / 1e6:.0f} MB)")
    print("Model and runtime are inside the file; it needs no network and no install.")
    print("A one-file build unpacks itself on every launch - around 10 s before it is")
    print("ready, and longer on a cold machine while a virus scanner reads it.")
    return exe


def smoke(exe: Path) -> int:
    """Run a packaged build as a server, offline, and have it read one sentence.

    This is the check a release ships on: the file starts with no network, its
    bundled model loads, and the audio it returns is speech-length and not
    silence. The CLI side is ``cli.py`` from this checkout, standard library only.
    """
    import socket
    import tempfile
    import wave
    from array import array

    sys.path.insert(0, str(ROOT))
    import cli

    exe = exe.resolve()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log = tempfile.TemporaryFile()
    proc = subprocess.Popen([str(exe), "serve", "--port", str(port), "--log-level", "warning"],
                            env={**os.environ, "HF_HUB_OFFLINE": "1"},
                            stdout=log, stderr=subprocess.STDOUT)
    print(f"smoke: {exe.name} serving on {url} (pid {proc.pid})", flush=True)
    passed = False
    try:
        if cli.main(["status", "--server", url, "--wait", "600"]) != 0:
            raise SystemExit("ERROR: the build never reported ready")
        out = ROOT / "out" / "package-smoke.wav"
        out.parent.mkdir(exist_ok=True)
        if cli.main(["speak", SMOKE_TEXT, "--server", url, "-o", str(out)]) != 0:
            raise SystemExit("ERROR: speak against the build failed")
        with wave.open(str(out)) as wav:
            pcm = array("h", wav.readframes(wav.getnframes()))
            seconds = wav.getnframes() / wav.getframerate()
        peak = max(map(abs, pcm), default=0)
        print(f"smoke: {seconds:.2f} s, peak {peak}", flush=True)
        if seconds < 2.0 or peak < 3000:
            raise SystemExit(f"ERROR: audio too short or silent ({seconds:.2f} s, peak {peak})")
        print("smoke: OK")
        passed = True
        return 0
    finally:
        # A one-file build is a bootloader plus the real process; take both down.
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        if not passed:  # the build's own output is the first thing to read then
            log.seek(0)
            print(log.read().decode("utf-8", "replace")[-2000:], flush=True)


def release_notes(version: str) -> int:
    """Print the body of ``## [version]`` in CHANGELOG.md - the GitHub Release notes.

    A version with no section fails, so a tag nobody wrote notes for stops the
    release before it spends an hour building.
    """
    text = CHANGELOG.read_text(encoding="utf-8")
    heading = re.search(rf"^## \[{re.escape(version)}\].*$", text, re.MULTILINE)
    if heading is None:
        print(f"ERROR: {CHANGELOG.name} has no '## [{version}]' section", file=sys.stderr)
        return 1
    rest = text[heading.end():]
    following = re.search(r"^## \[", rest, re.MULTILINE)
    body = rest[:following.start()] if following else rest
    if not body.strip():
        print(f"ERROR: the '## [{version}]' section of {CHANGELOG.name} is empty", file=sys.stderr)
        return 1
    # Bytes, not print(): a Windows console or pipe would encode it as cp1252 and
    # choke on the Vietnamese in the notes.
    sys.stdout.buffer.write(body.strip().encode("utf-8") + b"\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="run the smoke test instead of the app")
    mode.add_argument("--package", action="store_true", help="build a standalone bundle")
    mode.add_argument("--setup", action="store_true", help="prepare the environment and stop")
    mode.add_argument("--smoke", type=Path, metavar="EXE",
                      help="run a packaged build offline as a server and read a sentence")
    mode.add_argument("--release-notes", metavar="VERSION",
                      help="print that version's CHANGELOG.md section and stop")
    ap.add_argument("--server-only", action="store_true",
                    help="with --setup/--package: server + CLI only, no window or tray")
    args = ap.parse_args()

    if args.release_notes:
        return release_notes(args.release_notes)
    if args.smoke:
        return smoke(args.smoke)
    setup(args.server_only)
    if args.setup:
        return 0
    if args.package:
        package(args.server_only)
        return 0

    print()
    target = ["test_tts.py"] if args.check else ["app.py"]
    return subprocess.run([str(PY), *target], cwd=ROOT,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"}).returncode


if __name__ == "__main__":
    sys.exit(main())
