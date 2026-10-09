# Voice TTS

[![CI](https://github.com/dtbao-embedded-dev/voice-tts/actions/workflows/ci.yml/badge.svg)](https://github.com/dtbao-embedded-dev/voice-tts/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.7.0-blue)](https://github.com/dtbao-embedded-dev/voice-tts/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

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
- **Pronunciation** — `normal` reads the text as typed; `special` first respells the
  words the engine gets wrong (POST, AP, Board, ESP32...), see [Notes](#notes).

## Usage

### Pick a way to run it

| You want | Get it with | Then |
| --- | --- | --- |
| The app on a Windows PC | [Releases](https://github.com/dtbao-embedded-dev/voice-tts/releases): `VoiceTTS-windows-x64-setup.exe`, or `python docs/scripts/tool-install.py` | open *Voice TTS*, type, press **Đọc** |
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
4. **Phát âm** is *Thường* (the text as typed: `POST` is spelled *phê ô ét tê*) or
   *Đặc biệt* (`POST` read "post", `AP` "ây pi", `Board` "bo", `ESP32` "i ét pi ba
   hai").
5. **Đọc** (`Ctrl+Enter`) reads it as it is generated; press again or `Esc` to stop.
6. **Lưu WAV** saves what was read.

The window remembers the voice, speed and pronunciation you picked and the text you
were typing, across a restart. A browser on the LAN server remembers them per
browser.

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
voice-tts speak "Gửi POST tới ESP32" --pronunciation special      # POST "post", ESP32 "i ét pi ba hai"
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
| `POST` read as *phê ô ét tê*, `AP` as *ap* | the default `normal` pronunciation reads the text as typed: use `--pronunciation special` / *Phát âm → Đặc biệt* |
| `no audio player found` on Linux | install `pulseaudio-utils` or `alsa-utils`, or write a file with `-o` |

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
| `python docs/scripts/tool-build.py --package` | build `dist/VoiceTTS/`, model included |
| `python docs/scripts/tool-build.py --installer` | wrap it in `dist/VoiceTTS-<version>-setup.exe` (needs NSIS) |
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

This is the install that gives a working CLI. The release installer's `VoiceTTS.exe`
is a windowed build with no console, so it is for the window and `serve --tray` only.
The two live side by side: this one in `%LOCALAPPDATA%\Programs\VoiceTTS` with a
shortcut for this user, the installer's in `C:\Program Files\Voice TTS` with one for
every user, so the Start Menu lists *Voice TTS* twice while both are installed.

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
voice-tts speak -f bai-doc.txt -o bai-doc.mp3                       # MP3 (or .ogg) by extension
voice-tts speak "Xin chào" --server http://192.168.0.137:8760 --token <t>
voice-tts speak "Bật AP trên Board" --pronunciation special     # AP "ây pi", Board "bo"
voice-tts voices                 # * default, + featured; --json for the raw list
voice-tts lexicon add MQTT "em kiu ti ti"   # read MQTT that way in --pronunciation special
voice-tts lexicon list           # your words, then the built-in ones; --json for the raw list
voice-tts lexicon remove MQTT
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
| `--format F` | `wav`, `mp3` or `ogg` for `-o` (default: from the extension - `.mp3`, `.ogg`, `.oga` - else `wav`); needed for `-o -` |
| `--pronunciation P` | `normal` reads the text as typed (default); `special` respells POST, AP, Board, ESP32... first |
| `--server URL`, `--token T` | use a running server instead of loading the model here |
| `--local` | ignore `$VOICE_TTS_SERVER` |
| `--timeout S` | seconds to wait on the server (default 600) |
| `-q`, `--quiet` | nothing on stderr except errors |

`voices` and `status` take `--server`, `--token`, `--timeout` and `--json` too.
`lexicon add WORD SAY [--case]` adds a word or changes how one is read (`--case`:
that exact case only), `lexicon remove WORD` drops one; without `--server` they edit
`lexicon.json` in the data dir, with it the server's list.
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
| `GET /api/version` | `{"version": "0.7.0"}` - the version the server runs (`voice-tts --version` is the CLI's own) |
| `GET /api/voices` | the 25 preset voices with region, gender and description, the default voice, `sampleRate` and `maxChars` |
| `GET /api/lexicon` | `{"builtin": [...], "user": [...]}`, each entry `{"word", "say", "matchCase"}` |
| `PUT /api/lexicon` | replaces the user's words with `{"user": [...]}`; answers the new state, `400` for an empty, duplicate or over-long entry |
| `POST /api/tts/stream` | raw float32 LE mono at 48 kHz, streamed as it is generated; or one WAV, MP3 or OGG file with `"format"` |
| `POST /api/encode?format=mp3\|ogg` | the request body - 16-bit LE mono PCM at 48 kHz - encoded as one MP3 or OGG (Vorbis) file; how the window saves what it already read |

`GET /api/voices` is the list of voices a request may name - featured voices first,
then the rest in the engine's order (shortened here):

```json
{
  "voices": [
    {"name": "Adam bựa", "region": "Bắc", "gender": "male",
     "description": "Nam · Bắc · Phong cách tự nhiên", "featured": true},
    {"name": "Hải Đăng", "region": "Bắc", "gender": "male",
     "description": "Nam · Bắc · Phong cách tự nhiên", "featured": true},
    {"name": "Quốc Tuấn", "region": "Bắc", "gender": "male",
     "description": "Nam · Bắc · Phong cách tự nhiên", "featured": false}
  ],
  "default": "Hải Đăng",
  "sampleRate": 48000,
  "maxChars": 20000
}
```

`region` is `Bắc`, `Trung` or `Nam`; `default` is the voice used when a request names
none. The list comes from the installed `vieneu` SDK, so it changes with an SDK
upgrade: since 3.8.3 `Minh Quân Pro` is `Hải Đăng`, `Anh Khôi` is `Thiện Minh` and
`Mạnh Dũng` is `Quốc Tuấn`. The old names (and `Minh Quân`) are still accepted as
`voice` and read with the renamed voice; they are just no longer listed.

`POST /api/tts/stream` takes `{"text", "voice", "speed", "format", "pronunciation"}`:
`text` up to 20 000 characters, `voice` a name from `/api/voices` (omit it for the
default), `speed` between `0.5` and `2.0` (default `1.0`), `format` one of `"f32"`
(default), `"wav"`, `"mp3"` or `"ogg"`, `pronunciation` either `"normal"` (default, the text as typed)
or `"special"` (respelled by `lexicon.py`, see Notes).

| `format` | Body | `Content-Type` | Starts arriving |
| --- | --- | --- | --- |
| `"f32"` | raw float32 LE mono, 48 kHz, no header | `application/octet-stream` | with the first generated chunk - for live playback |
| `"wav"` | a complete 16-bit mono WAV, 48 kHz, real length in the header and `Content-Length` | `audio/wav` | once the whole text is synthesized - for saving a file |
| `"mp3"` | a complete MP3 (LAME through libsndfile), 48 kHz mono | `audio/mpeg` | once the whole text is synthesized |
| `"ogg"` | a complete Ogg Vorbis file, 48 kHz mono | `audio/ogg` | once the whole text is synthesized |

`POST /api/encode` answers `400` for an unknown `format` or a body that is empty or
not whole 16-bit samples, and `413` above 400 MB.

The answer is `400` for empty or over-long text, an unknown voice or a speed out
of range, `422` for an unknown `format` or `pronunciation`, and `401` when the server
has a token and the request does not carry it. Every `/api` call takes the token as
`Authorization: Bearer <token>`; leave the header out for a server without one.

The examples below read one sentence from a LAN server (`<host>` is its address,
`<token>` the `VOICE_TTS_TOKEN` from its `.env`; for the desktop app use
`127.0.0.1:<port>` and no header).

**curl.** Put the body in a UTF-8 file and send it with `--data-binary @file`.
Vietnamese typed straight into a `curl -d '...'` argument gets re-encoded by the
Windows console (Git Bash and PowerShell alike), and the server answers `400 There
was an error parsing the body`.

`request.json`:
```json
{"text": "Xin chào, đây là ví dụ gọi API.", "voice": "Mai Anh", "speed": 1.0, "format": "wav"}
```
```bash
curl -f -X POST http://<host>:8760/api/tts/stream \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  --data-binary @request.json --output speech.wav
```

Without `"format": "wav"` the same call streams raw float32; save that as
`speech.f32` and convert it with
`ffmpeg -f f32le -ar 48000 -ac 1 -i speech.f32 speech.wav`.

**Python**, standard library only, the server writing the WAV:
```python
import json, urllib.request

req = urllib.request.Request(
    "http://<host>:8760/api/tts/stream",
    data=json.dumps({"text": "Xin chào, đây là ví dụ gọi API.",
                     "voice": "Mai Anh", "speed": 1.0, "format": "wav"}).encode("utf-8"),
    headers={"Authorization": "Bearer <token>",
             "Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=600) as resp, open("speech.wav", "wb") as out:
    out.write(resp.read())
```

To start playing before the whole text is done, leave `format` out and read the
raw stream as it arrives:
```python
with urllib.request.urlopen(req, timeout=600) as resp:   # a request without "format"
    rate = int(resp.headers["X-Sample-Rate"])             # 48000
    while block := resp.read1(65536):                     # float32 LE mono
        ...                                               # hand it to an audio device
```

**CLI**, which does the request and the WAV in one step:
```bash
voice-tts speak -f text.txt -v "Mai Anh" -s 1.25 -o speech.wav \
  --server http://<host>:8760 --token <token>
```

The other endpoints take the same header:
```bash
curl -H "Authorization: Bearer <token>" http://<host>:8760/api/voices   # names to use as "voice"
curl -H "Authorization: Bearer <token>" http://<host>:8760/api/status   # {"state": "ready"}
curl -H "Authorization: Bearer <token>" http://<host>:8760/api/version  # {"version": "0.7.0"}
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

On Windows the right-click menu is the app's own (`web/tray.html`, shown by
`tray.PopupMenu`): the status and the address *Sao chép URL* copies on top, an icon
per entry, *Thoát* in red below a separator. It is a hidden window made at start,
so opening it only moves and shows it; it closes on Esc, a click elsewhere or a
pick, and the arrow keys and Enter work as in a native menu. Should it fail to open,
the native menu shows instead.

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
  streaming runs on the CPU engine either way. The model is
  [`pnnbao-ump/VieNeu-TTS-v3-Turbo`](https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo)
  through the `vieneu` SDK (`requirements.txt`), with its `int8` ONNX graphs for
  speed (about 2x the fp32 ones; a CPU without VNNI may sound distorted).
- **The first launch downloads the model** (HuggingFace cache, `~/.cache/huggingface`).
  The window shows *Đang tải model…* until it is ready. This applies to a source
  checkout only.
- **The packaged desktop build is a folder** (`dist/VoiceTTS/`, ~760 MB; the NSIS
  installer around it is ~330 MB): the runtime, the web view, the tray icon and both
  model repos (backbone + audio codec) are inside, and `VoiceTTS.exe` takes the same
  subcommands as `app.py` (`VoiceTTS.exe serve --tray`, say) - but, being windowed,
  it prints nothing; the CLI is the installed `voice-tts`. It points `HF_HOME` at its
  own copy with `HF_HUB_OFFLINE=1`, so it never touches the network. It is a folder
  and not one file because a one-file build unpacks itself into `%TEMP%` on *every*
  launch (~10 s here before *Sẵn sàng*). Building the installer compresses the model
  with LZMA, which takes ~9 minutes.
- **Reading speed is a time-stretch, not a playback rate.** v3 Turbo has no speed
  parameter, so the backend stretches the stream itself (WSOLA: overlap-add with a
  waveform-similarity search, `Stretch` in `app.py`). The 0.75×–1.5× buttons change
  the duration and leave the pitch where it is, so the voice at 0.75× is the voice at
  1×, only slower. The stream is always 48 kHz and a saved WAV is a plain 48 kHz file
  carrying the speed it was read at.
- **Two pronunciations: `normal` (default) and `special`.** The engine's text front
  end spells an upper-case word it does not know with Vietnamese letter names
  (`POST` is *phê ô ét tê*), turns `AP` into the syllable *ap*, and reads `Board` as
  English. `normal` leaves that as it is: the text is read as typed. `special`
  (`"pronunciation": "special"`, `--pronunciation special`, *Phát âm → Đặc biệt*)
  has `lexicon.py` rewrite whole words first: `POST`/`GET`/`PUT`/`PATCH`/`DELETE` as
  the English words, `AP` as *ây pi*, `board` (any case) as *bo*, `ESP32` (any case,
  also `ESP 32`) as *i ét pi ba hai*. `POSTMAN`, `APP` and `onboard` are left alone,
  and so is anything inside `<en>...</en>`. Another built-in word is one more line
  in `ENTRIES`.
- **Your own words.** `voice-tts lexicon add` or `PUT /api/lexicon` add words on top
  of the built-ins, read in `special` only (`normal` stays the text as typed). They live in `lexicon.json` in the data dir: `$VOICE_TTS_DATA`,
  else `%APPDATA%\VoiceTTS` on Windows and `~/.local/share/voice-tts` on Linux;
  the Docker image keeps it in the `voice-tts-data` volume (`/data/app`). A word you
  add replaces a built-in one with the same spelling, and where two words start at
  the same place the longer one wins (`ESP32 S3` before `ESP32`). On a LAN server the
  list is the server's: everyone who holds the token reads and edits the same one.
  Up to 500 words, 64 characters a word and 128 for how it is read.
- **What the window remembers lives in its own browser profile.** Settings and the
  draft are kept by the page (`localStorage`), so they belong to its origin. The
  window therefore serves its backend on a fixed port, `8761` (`voice-tts gui
  --port`), and keeps a WebView2 profile in `<data dir>/webview` instead of
  pywebview's private one. If 8761 is taken - a second window, another program -
  that window runs on any free port and starts without them.
- **Verify mode is deferred.** Checking a reading by ear - Whisper large-v3-turbo
  transcribes it, and it is sent only if it matches the text by 95% - was built,
  measured and taken out before release (it needs a 0.8 GB int8 model in the
  installer). [docs/verify-whisper.md](docs/verify-whisper.md) records what it used,
  the results and the commits that hold the code.
- **Licence.** The model card puts every shipped artifact - weights, ONNX exports and
  the preset-voice assets - under Apache-2.0 and allows commercial use of the audio;
  keep the notices of [pnnbao97/VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS)
  and the model repo when redistributing the exe. Cloning a voice you have no rights
  to is not covered.
- **One icon everywhere.** `icon.py` draws the white sound wave on a black disc for
  the tray, the window title bar and taskbar button, the Start Menu shortcut, the
  `VoiceTTS.exe` file and the page's `/favicon.svg`. The window sets its own taskbar
  app id (`VoiceTTS.Desktop`), so a source run is not grouped under `pythonw.exe`
  and its Python logo.
- **The UI is iOS dark, dark only.** A true-black background under `#1C1C1E` grouped
  surfaces, Apple's dark label colours and `systemBlue` as the one tint (the *Đọc*
  button, the chosen speed, the selected voice). There is no light variant and no
  theme switch; status is told apart by shape (ring, dot, square) as well as colour.

## CI

`.github/workflows/ci.yml` runs on every push to `main`, `developing`, `feat/**` and
`fix/**` and on pull requests, on `ubuntu-latest` and `windows-latest` with Python
3.12: `test_cli.py` (CLI, token guard, tray menu, the time-stretcher and the
pronunciation lexicon, against a stub engine - no model download) and `--help` for every subcommand and the
installer. The real-model smoke test runs locally (`tool-build.py --check`).

## Release

Write the version's section in `CHANGELOG.md` first, bump `cli.__version__` and the
version badge at the top of this file (`test_cli.py` fails if they differ), then:

```
git tag v0.5.0 && git push origin v0.5.0
```

`.github/workflows/release.yml` checks that the tag matches `cli.__version__` and that
`CHANGELOG.md` has a `## [<version>]` section - either missing fails the run before
the build. It then builds on both platforms and publishes a GitHub Release whose
notes are that section, with these files and `SHA256SUMS`:

| File | What it is |
| --- | --- |
| `VoiceTTS-windows-x64-setup.exe` | the desktop app's installer (all users, `C:\Program Files`, asks for admin): window + tray + every subcommand, model inside |
| `voice-tts-linux-x86_64` | console server + CLI (`serve`, `speak`, `voices`, `status`), model inside, no window |

Each file is smoke-tested before it ships: `tool-build.py --smoke <file>` starts it
as a server with `HF_HUB_OFFLINE=1`, waits for the bundled model and has it read a
mixed sentence. The installer gets the same test after a silent install into a temp
folder (`--smoke-installer`, from an elevated terminal locally), and then must uninstall without leaving a file
behind. *Run workflow* in the Actions tab does the build and the test
without publishing; the files stay as artifacts for 14 days. The Linux binary is
built on `ubuntu-latest`, so it needs a glibc at least as new as that runner's;
older distributions use the Docker image instead. A release redistributes the model
and its preset voices (Apache-2.0, see *Licence* under Notes).

```
python docs/scripts/tool-build.py --package --server-only   # dist/voice-tts, locally
python docs/scripts/tool-build.py --smoke dist/voice-tts
python docs/scripts/tool-build.py --package && python docs/scripts/tool-build.py --installer
python docs/scripts/tool-build.py --smoke-installer dist/VoiceTTS-0.6.0-setup.exe
python docs/scripts/tool-build.py --release-notes 0.5.0     # the notes a v0.5.0 tag publishes
```

## License

Copyright 2026 dtbao. Licensed under the [Apache License, Version 2.0](LICENSE): you
may use, modify and redistribute this code, including commercially, provided you keep
the license and copyright notices and state your changes. The model and its preset
voices are Apache-2.0 too, under their own notices (see *Licence* under
[Notes](#notes)).

## Layout

```
app.py                    FastAPI backend + native window entry point
tray.py                   system tray icon, its native menu (pystray) and the popup menu
lexicon.py                whole-word respellings for the special pronunciation
icon.py                   the app icon, one geometry: tray/window/exe .ico and /favicon.svg
cli.py                    command line: subcommands and flags, stdlib-only at import
test_tts.py               assert-based smoke test over the real HTTP path
test_cli.py               fast checks with a stub engine: CLI (local + remote), token guard
CHANGELOG.md              user-visible changes per version; a release publishes its section
LICENSE                   Apache License 2.0
web/                      index.html, app.css, app.js, tray.html (tray menu) - no build step
requirements.txt          server + CLI core (what Docker installs)
requirements-desktop.txt  core + window + tray (what tool-build.py installs)
Dockerfile, compose.yaml  Linux server image, token from .env
.github/workflows/        ci.yml (tests, both OSes), release.yml (installer + Linux binary)
docs/verify-whisper.md    deferred verify mode: what it used, results, where the code is
docs/scripts/tool-build.py  setup / run / check / package / installer
docs/scripts/voice-tts.nsi  the NSIS installer script tool-build.py --installer runs
docs/scripts/tool-install.py  install / uninstall: Windows venv, Linux Docker, --remote over ssh
```
