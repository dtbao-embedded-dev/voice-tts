#!/usr/bin/env python3
"""Build/run helper for Voice TTS. Standard library only - run it with any Python.

    python docs/scripts/tool-build.py             # set up (if needed) and launch
    python docs/scripts/tool-build.py --check     # set up and run the smoke test
    python docs/scripts/tool-build.py --package   # set up and build dist/VoiceTTS
    python docs/scripts/tool-build.py --setup     # set up only

Every step is skipped when it is already done, so the second run is the fast one.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements-sha256"
MODEL_CACHE_NAME = "models--pnnbao-ump--VieNeu-TTS-v3-Turbo"
HF_HUB = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub"
# Staged outside build/ and dist/: PyInstaller's --clean wipes both.
MODEL_STAGE = VENV / "model-bundle"

# PyInstaller cannot see these through vieneu's lazy imports.
COLLECT = ["vieneu", "onnxruntime", "sea_g2p", "kaldi_native_fbank", "soxr", "soundfile"]
# vieneu ships a Gradio demo we never import; it would double the bundle.
EXCLUDE = ["gradio", "gradio_client", "matplotlib", "tkinter", "IPython"]


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
    base = shutil.which("py") or sys.executable
    cmd = [base, "-3.12", "-m", "venv", str(VENV)] if base.endswith("py.exe") \
        else [base, "-m", "venv", str(VENV)]
    try:
        run(cmd)
    except subprocess.CalledProcessError:
        run([sys.executable, "-m", "venv", str(VENV)])  # no py launcher / no 3.12
    done(t0)


def ensure_deps() -> None:
    digest = hashlib.sha256(REQS.read_bytes()).hexdigest()
    if STAMP.exists() and STAMP.read_text().strip() == digest:
        print("  deps ... unchanged", flush=True)
        return
    t0 = step("deps")
    run([str(PY), "-m", "pip", "install", "--upgrade", "--quiet", "pip"])
    run([str(PY), "-m", "pip", "install", "--quiet", "-r", str(REQS)])
    STAMP.write_text(digest)
    done(t0)


def ensure_model() -> None:
    """Pull the weights now, so the first launch is not a silent 30 s wait."""
    cache = HF_HUB
    if (cache / MODEL_CACHE_NAME).exists():
        print("  model ... cached", flush=True)
        return
    t0 = step("model (first download, this takes a while)")
    run([str(PY), "-c", "import app; app.engine()"], env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    done(t0)


def setup() -> None:
    print("Voice TTS build", flush=True)
    ensure_venv()
    ensure_deps()
    ensure_model()


def stage_model() -> Path:
    """Copy the revision the cache currently points at into ``MODEL_STAGE``.

    The HuggingFace cache keeps every revision it has ever seen; only the one
    ``refs/main`` names goes into the exe, which is a third of what is on disk.
    On Windows ``blobs/`` stays empty and the snapshot holds the real files, so
    a plain copy is all an offline ``hf_hub_download`` needs to resolve.
    """
    src = HF_HUB / MODEL_CACHE_NAME
    if not src.is_dir():
        sys.exit(f"ERROR: model cache missing at {src} - run --setup first")
    revision = (src / "refs" / "main").read_text().strip()

    out = MODEL_STAGE / "hub" / MODEL_CACHE_NAME
    if MODEL_STAGE.exists():
        shutil.rmtree(MODEL_STAGE)
    (out / "refs").mkdir(parents=True)
    (out / "refs" / "main").write_text(revision)
    shutil.copytree(src / "snapshots" / revision, out / "snapshots" / revision)
    return MODEL_STAGE


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def package() -> None:
    t0 = step("pyinstaller")
    run([str(PY), "-m", "pip", "install", "--quiet", "pyinstaller"])
    done(t0)

    t0 = step("model")
    stage = stage_model()
    done(t0, f"{dir_size(stage) / 1e6:.0f} MB")

    t0 = step("bundle (one file, this takes a while)")
    cmd = [str(PY), "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onefile",
           "--name", "VoiceTTS",
           "--add-data", f"web{os.pathsep}web",
           "--add-data", f"{stage}{os.pathsep}hf"]
    for mod in COLLECT:
        cmd += ["--collect-all", mod]
    for mod in EXCLUDE:
        cmd += ["--exclude-module", mod]
    cmd.append("app.py")
    run(cmd)
    done(t0)

    exe = ROOT / "dist" / ("VoiceTTS.exe" if os.name == "nt" else "VoiceTTS")
    if not exe.exists():
        sys.exit(f"ERROR: PyInstaller finished but {exe} is missing")
    print(f"\n{exe}  ({exe.stat().st_size / 1e6:.0f} MB)")
    print("Model and runtime are inside the file; it needs no network and no install.")
    print("A one-file build unpacks itself on every launch - expect 10-30 s before")
    print("the window appears, and longer the first time while Defender scans it.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="run the smoke test instead of the app")
    mode.add_argument("--package", action="store_true", help="build a standalone bundle")
    mode.add_argument("--setup", action="store_true", help="prepare the environment and stop")
    args = ap.parse_args()

    setup()
    if args.setup:
        return 0
    if args.package:
        package()
        return 0

    print()
    target = ["test_tts.py"] if args.check else ["app.py"]
    return subprocess.run([str(PY), *target], cwd=ROOT,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"}).returncode


if __name__ == "__main__":
    sys.exit(main())
