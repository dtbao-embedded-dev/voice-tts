# Voice TTS

[![CI](https://github.com/dtbao-embedded-dev/voice-tts/actions/workflows/ci.yml/badge.svg)](https://github.com/dtbao-embedded-dev/voice-tts/actions/workflows/ci.yml)

Desktop app that reads mixed Vietnamese/English text aloud, powered by
[VieNeu-TTS v3 Turbo](https://github.com/pnnbao97/VieNeu-TTS).

- **UI** — a web view hosted in a native window (pywebview / WebView2). It behaves
  like an app: no reload, no context menu, no find bar, no zoom, no text selection
  outside the editor.
- **Backend** — Python (FastAPI + uvicorn) streaming 48 kHz audio as it is
  generated; loopback-only inside the desktop app, or a LAN server with a token.
- **Everywhere** — a desktop app with a tray icon on Windows, a Docker server on
  Linux, and one `voice-tts` command line for both.
- **Limit** — 20 000 characters per request, enforced by the backend and reported to
  the UI by `/api/voices`, so the field and the counter never drift from it.
- **Speed** — a backend time-stretch, so 0.75× is the same voice read slower rather
  than a lower one.
- **Model** — v3 Turbo is bilingual, so Vietnamese and English mix freely inside one
  sentence; no language tagging or manual splitting is needed.

## Usage

### Pick a way to run it

| You want | Get it with | Then |
| --- | --- | --- |
| The app on a Windows PC | [Releases](https://github.com/dtbao-embedded-dev/voice-tts/releases): `VoiceTTS-windows-x64.exe`, or `python docs/scripts/tool-install.py` | open *Voice TTS*, type, press **Đọc** |
| A server for the whole LAN | `python docs/scripts/tool-install.py --remote user@linux-host` | open `http://<host>:8760/?token=<token>` |
| Text to audio from a script | `voice-tts speak ... -o out.wav` | see [Command line](#command-line) |
| A Linux binary, no Docker | Releases: `voice-tts-linux-x86_64` | `./voice-tts-linux-x86_64 serve --host 0.0.0.0` |

Every way ships or downloads the same model; the first start takes ~30 s to load
it (plus a one-off download for a source install).

### Read text in the window

1. Open **Voice TTS** (Start Menu, or the downloaded exe).
2. Paste or type the text - up to 20 000 characters, Vietnamese and English mixed
   freely in one sentence.
3. **Giọng đọc** picks the voice (★ = featured); **Tốc độ** picks 0.75×-1.5×.
4. **Đọc** (`Ctrl+Enter`) reads it as it is generated; press again or `Esc` to stop.
5. **Lưu WAV** saves what was read.

Minimizing or closing the window hides it in the system tray and the app keeps
running; click the tray icon to bring it back, right-click → *Thoát* to quit.
To have it start with Windows, install with `--autostart`.

### Use the LAN server

Install once on a Linux box with Docker (see [Linux (Docker)](#linux-docker)); the
install prints the page URL with its token. From any machine on the LAN:

- **Browser:** open `http://<host>:8760/?token=<token>` once; the browser keeps the
  token in a cookie, so `http://<host>:8760/` works from then on.
- **CLI:** point `voice-tts` at it once per machine, then use it as if it were local:

  ```powershell
  setx VOICE_TTS_SERVER http://<host>:8760     # Windows; open a new terminal after
  setx VOICE_TTS_TOKEN  <token>
  ```
  ```sh
  export VOICE_TTS_SERVER=http://<host>:8760    # Linux/macOS, e.g. in ~/.profile
  export VOICE_TTS_TOKEN=<token>
  ```

  The CLI talks to a server with the Python standard library only, so a plain
  `python cli.py ...` from a checkout works on any machine with Python 3.10+.

The token is in `~/voice-tts/.env` on the server. To change it, re-run the install
with `--token <new>`; to see logs, `cd ~/voice-tts && docker compose logs -f`.

### Common commands

```
voice-tts speak "Xin chào, deploy lên production server."        # read aloud
voice-tts speak -f chuong-1.txt -v "Mai Anh" -s 1.25 -o ch1.wav   # a file to a WAV
cat notes.txt | voice-tts speak -o - > notes.wav                  # a pipe to a WAV
voice-tts voices                                                  # the voices to pick from
voice-tts status --wait 120                                       # is the server ready?
voice-tts speak "..." --local                                     # ignore the server, run here
```

`voice-tts <command> -h` lists every flag; [Command line](#command-line) has the
full table and the exit codes.

### Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `server refused the token` | wrong or missing token: `--token`, or `VOICE_TTS_TOKEN` |
| `cannot reach http://...` | server down or port blocked: `voice-tts status`, `docker ps` on the host |
| Page says *Đang tải model…* for long | first start after install is loading or downloading the model; wait |
| `Không có giọng '...'` (exit 2) | voice name mistyped: `voice-tts voices` lists the exact names |
| `voice-tts` not found on Windows | open a new terminal after the install, so it sees the new `PATH` |
| `no audio player found` on Linux | install `pulseaudio-utils` or `alsa-utils`, or write a file with `-o` |
| Exe takes ~10 s to show up | a one-file build unpacks itself on every launch; that is normal |

## Quick start (development)

```
python docs/scripts/tool-build.py
```

That creates `.venv`, installs `requirements-desktop.txt`, downloads the model into the
HuggingFace cache and launches the app. Every step is skipped when it is already
done, so later runs start in seconds.

| Command | What it does |
| --- | --- |
| `python docs/scripts/tool-build.py` | set up if needed, then launch the app |
| `python docs/scripts/tool-build.py --check` | run the smoke test |
| `python docs/scripts/tool-build.py --package` | build `dist/VoiceTTS.exe`, model included |
| `python docs/scripts/tool-build.py --setup` | prepare the environment and stop |

Running `app.py` directly works too:

```
.venv/Scripts/python app.py              # native window
.venv/Scripts/python app.py serve        # backend only, on port 8760
.venv/Scripts/python app.py --help       # every subcommand and flag
```

`--no-window` is still accepted and means `serve`.

## Install

### Windows

```
python docs/scripts/tool-install.py              # install for this user
python docs/scripts/tool-install.py --autostart  # ... and run `serve --tray` at login
python docs/scripts/tool-install.py --uninstall
```

The app goes to `%LOCALAPPDATA%\Programs\VoiceTTS` with its own venv (Python 3.12
through the `py` launcher when present). `voice-tts` is added to the user `PATH` -
open a new terminal to see it - and a *Voice TTS* Start Menu shortcut opens the
window through `pythonw`, so no console comes with it. Re-running updates the app
files in place and reinstalls packages only when the requirements changed;
`--prefix DIR` installs elsewhere. Uninstall removes the folder, the shortcuts and
the `PATH` entry, and leaves the HuggingFace model cache alone.

This is the install that gives a working CLI. The packaged `VoiceTTS.exe` is a
windowed build with no console, so it is for the window and `serve --tray` only.

### Linux (Docker)

```
python3 docs/scripts/tool-install.py                                   # on the Linux box
python docs/scripts/tool-install.py --remote panboy@192.168.0.137      # from any machine, over ssh
python docs/scripts/tool-install.py --remote panboy@192.168.0.137 --uninstall
```

The Linux box needs Docker (with compose v2) and `python3`, nothing else - not even
`python3-venv`. The install copies the app and the Docker files to `~/voice-tts`,
writes `~/voice-tts/.env` (mode 600) with a generated token unless one is there
already or `--token` gives one, runs `docker compose up -d --build` and waits for
the model. `~/.local/bin/voice-tts` is the CLI: it runs `cli.py` on the system
`python3` with `VOICE_TTS_SERVER` and `VOICE_TTS_TOKEN` taken from that `.env`, so
`speak`, `voices` and `status` talk to the container. `--port` changes the host
port. `--remote` packs the needed files, runs the same install on the host and
deletes its staging copy afterwards; re-running it updates the server in place and
keeps the token. Uninstall stops and removes the container and its image, and keeps
the `voice-tts-hf` model volume.

The page is then at `http://<host>:8760/?token=<token>` - once per browser, the
cookie remembers it - and any machine with this repo can use the CLI against it:

```
voice-tts speak "Xin chào" --server http://192.168.0.137:8760 --token <token>
```

## Command line

```
voice-tts speak "Xin chào, deploy lên production server."           # play it
voice-tts speak -f bai-doc.txt -v "Mai Anh" -s 1.25 -o bai-doc.wav  # save it
echo "Chào bạn" | voice-tts speak -o - > chao.wav                   # pipe it
voice-tts speak "Xin chào" --server http://192.168.0.137:8760 --token <t>
voice-tts voices                 # * default, + featured; --json for the raw list
voice-tts status --wait 600      # exit 0 once the server's model is ready
```

| `speak` flag | Meaning |
| --- | --- |
| `TEXT...` / `-f FILE` / stdin | the text; `-` (or a pipe with no `TEXT`) reads stdin, UTF-8 |
| `-v`, `--voice` | preset voice name; `voice-tts voices` lists them |
| `-s`, `--speed` | 0.5-2.0, pitch unchanged (default 1.0) |
| `-o`, `--output` | write to a file, or `-` for stdout; without it the text is played |
| `--play` / `--no-play` | force playback on or off (default: on unless `-o`) |
| `--raw` | with `-o`: raw float32 LE mono 48 kHz instead of a 16-bit WAV |
| `--server URL`, `--token T` | use a running server instead of loading the model here |
| `--local` | ignore `$VOICE_TTS_SERVER` |
| `--timeout S` | seconds to wait on the server (default 600) |
| `-q`, `--quiet` | nothing on stderr except errors |

`voices` and `status` take `--server`, `--token`, `--timeout` and `--json` too.
`$VOICE_TTS_SERVER` and `$VOICE_TTS_TOKEN` are the defaults for `--server` and
`--token`. Exit codes: `0` done, `1` runtime failure (unreachable server, wrong
token, model failed), `2` bad input (usage, empty or over-long text, unknown voice,
speed out of range).

- **Without `--server`** the model loads in the CLI process (~30 s); for many short
  reads, start `voice-tts serve` once and point the CLI at it.
- **With `--server`** `cli.py` imports only the standard library, so it runs on any
  Python 3.10+ with nothing installed.
- **Playback** streams into `paplay`, `pw-play` or `aplay` on Linux as the audio
  arrives. Windows (`winsound`) and macOS (`afplay`) have no streaming player in the
  base system, so they play once the whole text is synthesized.

## Server mode

```
python app.py serve --host 0.0.0.0 --port 8760 --token <secret>
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | address to bind; `0.0.0.0` serves the LAN |
| `--port` | `8760` | port to bind |
| `--token` | `$VOICE_TTS_TOKEN`, else none | require this token on every `/api` request |
| `--log-level` | `info` | uvicorn log level |

With a token set, `/api/*` answers `401` unless the request carries
`Authorization: Bearer <token>` or the `vtts_token` cookie. Open
`http://<host>:8760/?token=<token>` once in a browser and the page sets that cookie
for itself, so the web UI works unchanged. The page and `/web/*` stay open; they are
static. Without a token the API is open, which is what the loopback-only desktop app
wants - binding anything else without one prints a warning. The token travels over
plain HTTP: fine on a home LAN, not for the internet.

## HTTP API

| Endpoint | Response |
| --- | --- |
| `GET /api/status` | `{"state": "loading" \| "ready" \| "error"}` while the model warms up |
| `GET /api/voices` | 25 preset voices with region, gender and description, plus `maxChars` |
| `POST /api/tts/stream` | raw float32 LE mono at 48 kHz, streamed as it is generated |

`POST /api/tts/stream` takes `{"text", "voice", "speed"}`; `speed` defaults to `1.0`
and must be between `0.5` and `2.0`.

```
curl -X POST http://127.0.0.1:8760/api/tts/stream \
  -H "Content-Type: application/json" \
  -d '{"text": "Deploy model lên production server.", "voice": "Mai Anh"}' \
  --output speech.f32
```

## Docker (Linux server)

```
echo "VOICE_TTS_TOKEN=$(openssl rand -hex 16)" > .env
docker compose up -d --build
docker compose logs -f            # first start downloads the model, ~30 s on a LAN
```

The image (`python:3.12-slim`, ~1 GB) runs `serve --host 0.0.0.0 --port 8760` as an
unprivileged user. The model lives in the `voice-tts-hf` volume, so rebuilds and
reinstalls do not download it again. `restart: unless-stopped` brings it back after
a reboot; the healthcheck turns `healthy` once the model is ready. `.env` holds
`VOICE_TTS_TOKEN`, and optionally `VOICE_TTS_PORT` (host port, default 8760) and
`VOICE_TTS_CONTAINER` (default `voice-tts`); it is git-ignored.

A Linux HuggingFace cache normally links snapshot files to blobs; onnxruntime then
rejects the backbone's external `.data` file as outside the model directory.
`app.py` sets `HF_HUB_DISABLE_SYMLINKS=1` so the snapshot holds real files. A cache
filled before that, with symlinks, has to be deleted once (`docker volume rm
voice-tts-hf`, or `~/.cache/huggingface/hub/models--*` for a source checkout).

## System tray

The window lives in the system tray: **minimize or close hides it there and the
server keeps running**. A click on the tray icon brings the window back; its menu
has *Mở cửa sổ*, *Mở trong trình duyệt*, *Sao chép URL* and *Thoát* - only *Thoát*
ends the app. `--no-tray` restores the old behaviour, close = quit.

```
voice-tts serve --tray --open              # no window at all: an icon and a browser tab
voice-tts serve --tray --host 0.0.0.0 --token <t>
```

`serve --tray` puts only the icon on screen; its first entry opens the page (with the
token, if one is set) and *Sao chép URL* copies the LAN address. When the desktop
has no tray (a Linux session without AppIndicator, say) the app logs a warning and
carries on without one: the window closes as before, `serve` keeps serving.

## Keyboard

| Key | Action |
| --- | --- |
| `Ctrl` + `Enter` | read / stop |
| `Esc` | stop, or close the voice sheet |

## Notes

- **No GPU is required.** The default install is the torch-free ONNX build, and
  streaming runs on the CPU engine either way. `int8` precision is used for speed.
- **The first launch downloads the model** (HuggingFace cache, `~/.cache/huggingface`).
  The window shows *Đang tải model…* until it is ready. This applies to a source
  checkout only.
- **The packaged build is one self-contained `VoiceTTS.exe`** (~610 MB): the runtime,
  the web view, the tray icon and both model repos (backbone + audio codec) are
  inside it, and it takes the same subcommands as `app.py` (`VoiceTTS.exe serve
  --tray`, say) - but, being windowed, it prints nothing; the CLI is the installed
  `voice-tts`. It
  points `HF_HOME` at its own copy with `HF_HUB_OFFLINE=1`, so it never touches the
  network. The price is that a one-file build unpacks itself into `%TEMP%` on *every*
  launch — measured ~10 s from launch to *Sẵn sàng* here, longer on a cold machine
  while Defender scans it.
- **Reading speed is a time-stretch, not a playback rate.** v3 Turbo has no speed
  parameter, so the backend stretches the stream itself (WSOLA: overlap-add with a
  waveform-similarity search, `Stretch` in `app.py`). The 0.75×–1.5× buttons change
  the duration and leave the pitch where it is, so the voice at 0.75× is the voice at
  1×, only slower. The stream is always 48 kHz and a saved WAV is a plain 48 kHz file
  carrying the speed it was read at.
- **The voices are licensed for non-commercial use only.** Bundling them into the exe
  redistributes them; check the VieNeu terms before handing the file to anyone.
- **The UI is iOS dark, dark only.** A true-black background under `#1C1C1E` grouped
  surfaces, Apple's dark label colours and `systemBlue` as the one tint (the *Đọc*
  button, the chosen speed, the selected voice). There is no light variant and no
  theme switch; status is told apart by shape (ring, dot, square) as well as colour.

## CI

`.github/workflows/ci.yml` runs on every push to `main`, `developing`, `feat/**` and
`fix/**` and on pull requests, on `ubuntu-latest` and `windows-latest` with Python
3.12: `test_cli.py` (CLI, token guard, tray menu and the time-stretcher, against a
stub engine - no model download) and `--help` for every subcommand and the
installer. The real-model smoke test runs locally (`tool-build.py --check`).

## Release

```
git tag v0.4.0 && git push origin v0.4.0
```

`.github/workflows/release.yml` checks that the tag matches `cli.__version__`, then
builds on both platforms and attaches to a GitHub Release, with `SHA256SUMS`:

| File | What it is |
| --- | --- |
| `VoiceTTS-windows-x64.exe` | the desktop app: window + tray + every subcommand, model inside |
| `voice-tts-linux-x86_64` | console server + CLI (`serve`, `speak`, `voices`, `status`), model inside, no window |

Each file is smoke-tested before it ships: `tool-build.py --smoke <file>` starts it
as a server with `HF_HUB_OFFLINE=1`, waits for the bundled model and has it read a
mixed sentence. *Run workflow* in the Actions tab does the build and the test
without publishing; the files stay as artifacts for 14 days. The Linux binary is
built on `ubuntu-latest`, so it needs a glibc at least as new as that runner's;
older distributions use the Docker image instead. The voices are licensed for
non-commercial use - a release redistributes them.

```
python docs/scripts/tool-build.py --package --server-only   # dist/voice-tts, locally
python docs/scripts/tool-build.py --smoke dist/voice-tts
```

## Layout

```
app.py                    FastAPI backend + native window entry point
tray.py                   system tray icon and its menu (pystray)
cli.py                    command line: subcommands and flags, stdlib-only at import
test_tts.py               assert-based smoke test over the real HTTP path
test_cli.py               fast checks with a stub engine: CLI (local + remote), token guard
web/                      index.html, app.css, app.js - no build step
requirements.txt          server + CLI core (what Docker installs)
requirements-desktop.txt  core + window + tray (what tool-build.py installs)
Dockerfile, compose.yaml  Linux server image, token from .env
.github/workflows/        ci.yml (tests, both OSes), release.yml (exe + Linux binary)
docs/scripts/tool-build.py  setup / run / check / package
docs/scripts/tool-install.py  install / uninstall: Windows venv, Linux Docker, --remote over ssh
```
