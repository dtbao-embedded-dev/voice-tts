#!/usr/bin/env python3
"""Install Voice TTS for the current user. Standard library only.

    python docs/scripts/tool-install.py               # Windows: install here
    python docs/scripts/tool-install.py --autostart   # ... and start `serve --tray` at login
    python docs/scripts/tool-install.py --uninstall   # remove what the install made

Windows: the app goes to %LOCALAPPDATA%\\Programs\\VoiceTTS with its own venv,
`voice-tts` lands on the user PATH, and a Start Menu shortcut opens the window.
The model stays in the shared HuggingFace cache, which uninstall leaves alone.

Re-running updates an install in place: the app files are replaced, the venv
and its packages are kept unless the requirements changed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_FILES = ("app.py", "cli.py", "tray.py", "requirements.txt", "requirements-desktop.txt")
APP_DIRS = ("web",)
NAME = "Voice TTS"


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def say(msg: str) -> None:
    print(f"  {msg}", flush=True)


# --------------------------------------------------------------------- Windows

class Windows:
    def __init__(self, prefix: Path | None) -> None:
        local = Path(os.environ["LOCALAPPDATA"])
        self.prefix = prefix or local / "Programs" / "VoiceTTS"
        self.app = self.prefix / "app"
        self.venv = self.prefix / "venv"
        self.bin = self.prefix / "bin"
        self.py = self.venv / "Scripts" / "python.exe"
        self.pyw = self.venv / "Scripts" / "pythonw.exe"
        self.icon = self.prefix / "voice-tts.ico"
        programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        self.start_menu = programs / f"{NAME}.lnk"
        self.startup = programs / "Startup" / f"{NAME} Server.lnk"

    # -- install

    def install(self, autostart: bool) -> None:
        print(f"Installing {NAME} to {self.prefix}", flush=True)
        self.copy_app()
        self.ensure_venv()
        self.ensure_deps()
        self.ensure_model()
        self.write_shim()
        self.add_to_path()
        self.make_icon()
        self.shortcut(self.start_menu, "gui", "Đọc văn bản tiếng Việt/Anh")
        say(f"Start Menu: {self.start_menu.name}")
        if autostart:
            self.shortcut(self.startup, "serve --tray", "Voice TTS server in the tray")
            say("autostart: `serve --tray` at login")
        elif self.startup.exists():
            self.startup.unlink()
            say("autostart: removed (re-run with --autostart to keep it)")
        print(f"\nDone. Open a new terminal and run `voice-tts --help`.")

    def copy_app(self) -> None:
        if self.app.exists():
            shutil.rmtree(self.app)
        self.app.mkdir(parents=True)
        for name in APP_FILES:
            shutil.copy2(ROOT / name, self.app / name)
        for name in APP_DIRS:
            shutil.copytree(ROOT / name, self.app / name)
        say("app files: copied")

    def ensure_venv(self) -> None:
        if self.py.exists():
            say("venv: already there")
            return
        launcher = shutil.which("py")
        cmd = [launcher, "-3.12", "-m", "venv", self.venv] if launcher \
            else [sys.executable, "-m", "venv", self.venv]
        try:
            run(cmd)
        except subprocess.CalledProcessError:
            run([sys.executable, "-m", "venv", self.venv])  # no 3.12: use this Python
        say("venv: created")

    def ensure_deps(self) -> None:
        reqs = [self.app / "requirements.txt", self.app / "requirements-desktop.txt"]
        digest = hashlib.sha256(b"".join(r.read_bytes() for r in reqs)).hexdigest()
        stamp = self.venv / ".requirements-sha256"
        if stamp.exists() and stamp.read_text().strip() == digest:
            say("packages: unchanged")
            return
        say("packages: installing (first time takes a few minutes) ...")
        run([self.py, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
        run([self.py, "-m", "pip", "install", "--quiet", "-r", reqs[1]], cwd=self.app)
        stamp.write_text(digest)
        say("packages: installed")

    def ensure_model(self) -> None:
        say("model: loading once (downloads it on a fresh machine) ...")
        run([self.py, "-c", "import app; app.engine()"], cwd=self.app,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        say("model: ready")

    def write_shim(self) -> None:
        self.bin.mkdir(exist_ok=True)
        (self.bin / "voice-tts.cmd").write_text(
            "@echo off\r\n"
            "setlocal\r\n"
            "set PYTHONIOENCODING=utf-8\r\n"
            '"%~dp0..\\venv\\Scripts\\python.exe" "%~dp0..\\app\\cli.py" %*\r\n',
            encoding="ascii")
        say(f"command: {self.bin / 'voice-tts.cmd'}")

    def make_icon(self) -> None:
        run([self.py, "-c",
             "import sys, tray; tray.icon_image(256).save(sys.argv[1], "
             "sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])", self.icon], cwd=self.app)

    def shortcut(self, link: Path, args: str, description: str) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)

        def q(value) -> str:  # a PowerShell single-quoted literal
            return "'" + str(value).replace("'", "''") + "'"

        arguments = f'"{self.app / "cli.py"}" {args}'
        script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({q(link)}); "
                  f"$s.TargetPath = {q(self.pyw)}; "
                  f"$s.Arguments = {q(arguments)}; "
                  f"$s.WorkingDirectory = {q(self.app)}; "
                  f"$s.IconLocation = {q(self.icon)}; "
                  f"$s.Description = {q(description)}; "
                  f"$s.Save()")
        run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])

    # -- PATH

    def _user_path(self):
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                             winreg.KEY_READ | winreg.KEY_WRITE)
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        return key, value, kind

    def _set_user_path(self, entries: list[str]) -> None:
        import ctypes
        import winreg

        key, _, kind = self._user_path()
        with key:
            winreg.SetValueEx(key, "Path", 0, kind, ";".join(entries))
        # Tell Explorer, so terminals started from it see the new PATH.
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002,
                                                 5000, ctypes.byref(ctypes.c_ulong()))

    def _path_entries(self) -> list[str]:
        key, value, _ = self._user_path()
        key.Close()
        return [e for e in value.split(";") if e]

    def _is_ours(self, entry: str) -> bool:
        return os.path.normcase(os.path.expandvars(entry).rstrip("\\")) == \
            os.path.normcase(str(self.bin))

    def add_to_path(self) -> None:
        entries = self._path_entries()
        if any(self._is_ours(e) for e in entries):
            say("PATH: already has bin")
            return
        self._set_user_path(entries + [str(self.bin)])
        say("PATH: bin added for this user")

    # -- uninstall

    def uninstall(self) -> None:
        print(f"Removing {NAME} from {self.prefix}", flush=True)
        for link in (self.start_menu, self.startup):
            if link.exists():
                link.unlink()
                say(f"removed {link.name}")
        entries = self._path_entries()
        if any(self._is_ours(e) for e in entries):
            self._set_user_path([e for e in entries if not self._is_ours(e)])
            say("PATH: bin removed")
        if self.prefix.exists():
            try:
                shutil.rmtree(self.prefix)
            except PermissionError as exc:
                sys.exit(f"ERROR: {exc.filename} is in use - quit Voice TTS (tray: Thoát) "
                         f"and run --uninstall again")
            say(f"removed {self.prefix}")
        print("Done. The model cache (~/.cache/huggingface) was left in place.")


# --------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uninstall", action="store_true", help="remove the install")
    ap.add_argument("--autostart", action="store_true",
                    help="Windows: start `serve --tray` at login")
    ap.add_argument("--prefix", type=Path, help="install directory (default: per platform)")
    args = ap.parse_args()

    if os.name != "nt":
        sys.exit("ERROR: only Windows installs are supported by this version")
    target = Windows(args.prefix)
    if args.uninstall:
        target.uninstall()
    else:
        target.install(args.autostart)
    return 0


if __name__ == "__main__":
    sys.exit(main())
