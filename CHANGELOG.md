# Changelog

Every user-visible change, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the version is
`cli.__version__`. A release publishes its own section as the GitHub Release notes
(`tool-build.py --release-notes <version>`), and a tag without a section here fails
the release before it builds.

## [Unreleased]

### Added

- The server logs every reading: when it queues (and how many are ahead), when its
  turn comes (and how long it waited), and how it ended - done, hung up or failed -
  with the audio length, engine time, RTF and time to first audio. The lines go to
  stderr at any `--log-level`. `VOICE_TTS_LOG_TEXT=1` adds the text itself.

### Fixed

- A short reading no longer comes out with words the engine made up ("Vâng." as
  "Vâng khi tại."): `wav`, `mp3` and `ogg` readings, and any text of three words or
  fewer, now go through the engine's own babble guard, which re-reads such a chunk.
  The guard only ran outside streaming, and every reading streamed.
- The `special` pronunciation reads units after a number the way engineers say
  them: `3,3V` *vôn* (was the letter *vê*), `5mW` *mi li oát* (was megawatts),
  `10µF` *mi cờ rô pha ra* (the µ was dropped), `500mA` *mi li am pe* (was *ma*),
  `45kΩ` *ki lô ôm* (was *ca ôm*), `22pF`, `100nF`, `20 ns`, `10mH` (were English
  letters). Ranges (`1-2m` was *một đến haim*, `0~5V` *không khoảng năm*), `5V2A`,
  `3.3V/500mA`, `1/4W`, resistor codes (`100R`), capacitor codes (`tụ 104` *một
  không bốn*, was *một trăm lẻ bốn*; `tụ 22p` *pi cô*, was *hai mươi hai phút*),
  hex (`0x3C`, was *không nhân ba xê*) and `−40°C` (the minus sign was dropped) too.
  [docs/pronunciation.md](docs/pronunciation.md) has the full table.
- The `special` pronunciation spells upper-case acronyms the engine does not know
  with English letter names for the digital side (`UART` *iu ây ar ti*, was *u a rờ
  tê* and heard as "UAZT"; `RX` *ar ích*, was heard as "ZX"; `MQTT` *em kiu ti ti*)
  and Vietnamese ones for power, analog parts and reference designators (`GND` *gờ
  nờ đê*, `LM358` *lờ mờ ba năm tám*, `R1` *rờ một*). `NE555` keeps its three fives
  (one was dropped), `2N2222` is read digit by digit, and `INFO`, `HIGH`, `BOOT`,
  `RESET` are read as words. Acronyms the engine already read in English letters
  now use the same letter names: `I2C` was *i hai xê* and is *ai hai xi*, `HTTP`,
  `USB` and `IP` sound slightly different. `voice-tts lexicon add` keeps any old
  spelling.
- The `special` pronunciation reads code: identifiers part by part (`ESP_LOGI` *i ét
  pi log ai*, `uint8_t` *iu int tám ti*; `gạch dưới` was read aloud), file names
  (`main.c` *main chấm xi*, was *main. xê*), versions (`v5.3` *vi năm chấm ba*, was
  *vê năm. ba*), URLs and paths (`/` *gạch chéo*, was *trên*), ports digit by digit,
  and the numbers of a code line (`2048` was *two thousand forty eight*).
- About 80 more built-in lexicon words, Vietnamese and English: `FreeRTOS`,
  `PSRAM`, `JTAG`, `OK` *ô kê*, `FIFO`, `VOUT` *vê ao*, `module` *mô đun*, `mass`
  *mát*, `SOT-23`, `VĐK` *vi điều khiển*, `HĐH` *hệ điều hành*...

## [0.8.2] - 2026-10-09

### Changed

- The server reads one text at a time and queues the rest in arrival order, so the
  reading being heard stays faster than real time; before, every request ran at
  once and all of them stuttered. `VOICE_TTS_MAX_STREAMS` raises the limit.

### Fixed

- A listener who hangs up mid-stream frees the engine at once; the abandoned
  reading used to keep generating until the garbage collector reached it.

## [0.8.1] - 2026-10-09

### Fixed

- A long text sent to `POST /api/tts/stream` or `voice-tts speak` no longer has a
  phrase spoken twice ("post bằng ESP HTTP post bằng ESP HTTP client"): the engine
  now reads it in chunks of about 120 characters instead of 256 (5 of 20 readings
  looped before, none of 20 after).
- `ESP` on its own is read *i ét pi* in the `special` pronunciation, like `ESP32`;
  it was spelled *e ét phê* and heard as "ESV".
- `POST /api/encode` with a body that is not `application/octet-stream` answers
  `415` on Windows every time; it sometimes aborted the connection instead.

## [0.8.0] - 2026-10-09

### Added

- The project is licensed under the Apache License 2.0 (`LICENSE`).
- `GET /api/version` answers `{"version": "<version>"}`, the version the server
  runs - `voice-tts --version` only ever told the CLI's own.
- MP3 and OGG (Vorbis) output: `"format": "mp3"` / `"ogg"` on `POST /api/tts/stream`,
  `POST /api/encode?format=` to encode 16-bit PCM a client already holds, and
  `voice-tts speak -o out.mp3` (format from the extension, or `--format`).
- Your own pronunciation words, read in `special` on top of the built-ins:
  `GET`/`PUT /api/lexicon` and `voice-tts lexicon list|add|remove`, stored in
  `lexicon.json` in the data dir (`$VOICE_TTS_DATA`, `%APPDATA%\VoiceTTS`,
  `~/.local/share/voice-tts`; the `voice-tts-data` volume in Docker). A user word
  replaces a built-in one with the same spelling, and the longest word wins.
- *Từ điển* in the window lists the built-in words and yours, adds, changes and
  removes yours, and plays how a spelling sounds (*Nghe*, *Nghe thử*). A changed
  list makes the next special-pronunciation reading read anew.
- *Lịch sử* in the window keeps the last 20 readings with their audio in the
  browser (IndexedDB); one click plays a reading again, to seek or save, without
  synthesis. Readings stopped after at least a second are kept, marked *một phần*.
- Open a `.txt` or `.md` file in the window: *Mở file…*, `Ctrl+O`, or drop it on the
  window. Markdown is read for its words (marks, URLs and code blocks left out);
  past 20 000 characters the rest is cut, and the status line says so.
- *Lưu dạng* in the window saves a reading as WAV, MP3 or OGG; MP3 and OGG are
  encoded by `/api/encode` from the audio already read.
- The window remembers the voice, speed, pronunciation, file format and the draft
  across a reload and a restart; a browser on the LAN server remembers them per
  browser.
- Pause, seek and replay in the window, from what was already read: the main
  button reads, pauses (*Tạm dừng*), carries on (*Tiếp tục*) and plays again (*Phát
  lại*), a bar seeks, and **■** stops. The backend is asked again only once the
  text, voice, speed or pronunciation changes.

### Changed

- The CPU engine loads the fp32 ONNX graphs of v3 Turbo (`onnx_update`) instead of
  the int8 ones: the reference quality, and no int8 distortion. On an i5-14600K it
  is faster too (real-time factor 0.29 against 0.55). The first start downloads
  475 MB of graphs, and the packaged build carries them instead of the 165 MB int8
  set.
- The window reads one sentence per request and shows the text while it reads:
  the sentence being heard is lit, and clicking one jumps to it, or reads from it
  if it is not made yet.
- The window's backend listens on the fixed port 8761 (`gui --port`, any free port
  if it is taken) and keeps a WebView2 profile in `<data dir>/webview`, so what the
  page stores survives a restart. It answers only requests addressed to
  `127.0.0.1` or `localhost` on that port.
- The lexicon respells in one pass, longest word first, so a spelling one entry
  produces is never respelled by another.

### Fixed

- On Windows a second server could bind a port already in use and split its
  connections; the port is now claimed exclusively.
- A request refused for its token, or an `/api/encode` call refused for its format,
  could reach a Windows client as a reset connection instead of the error.

## [0.7.0] - 2026-10-09

### Added

- A `special` pronunciation (`"pronunciation": "special"` on `POST /api/tts/stream`,
  `speak --pronunciation special`, *Phát âm → Đặc biệt* in the window) respells
  whole words the engine gets wrong before it reads them (`lexicon.py`): `POST`,
  `GET`, `PUT`, `PATCH` and `DELETE` as the English words instead of *phê ô ét tê*,
  `AP` as *ây pi* instead of the syllable *ap*, `Board` as *bo*, and `ESP32` (any
  case, also `ESP 32`) as *i ét pi ba hai*. The default, `normal`, reads the text
  as typed, as before.

## [0.6.1] - 2026-10-08

### Changed

- The Windows installer installs for every user into `C:\Program Files\Voice TTS`
  and asks for admin, with the Start Menu entry and desktop shortcut for all users.
  It first removes a 0.6.0 install from `%LOCALAPPDATA%\Programs\Voice TTS`, so
  Settings > Apps lists the app once.

### Fixed

- The installer's Vietnamese text was garbled (*Mở Voice TTS* read *Má»Ÿ Voice
  TTS*): the script is now compiled as UTF-8.

## [0.6.0] - 2026-10-08

### Changed

- The Windows release is an installer, `VoiceTTS-windows-x64-setup.exe` (NSIS),
  instead of a one-file `VoiceTTS.exe`. It installs for the current user without an
  admin prompt into `%LOCALAPPDATA%\Programs\Voice TTS`, adds a Start Menu entry
  (and a desktop shortcut, optional), and uninstalls from Settings > Apps. The app
  inside is a folder build, so it no longer unpacks ~400 MB into `%TEMP%` on every
  launch.
- The tray icon's right-click menu is the app's own dark menu - status and address
  at the top, an icon per entry, *Thoát* set apart in red - in place of the white
  Windows menu. It opens at the pointer, closes on Esc or a click elsewhere, and
  *Sao chép URL* confirms the copy in place. `serve --tray`, which has no window,
  keeps the native menu.

### Fixed

- The title bar icon was a white blob: at 16 px the five bars merged into one. The
  bars now sit on whole pixels at every size, and the `.ico` carries a 20 px image
  for 125 % scaling.

## [0.5.0] - 2026-10-08

### Added

- `CHANGELOG.md`; a tagged release publishes the section of its version as the
  release notes instead of a generated commit list.
- README: a `GET /api/voices` response example and how renamed voices resolve.

### Changed

- VieNeu SDK 3.8.3 (`vieneu>=3.8.3`), still the int8 graphs of
  `pnnbao-ump/VieNeu-TTS-v3-Turbo`. Its voice list renames three presets: the default
  `Minh Quân Pro` is now `Hải Đăng`, `Anh Khôi` is `Thiện Minh`, `Mạnh Dũng` is
  `Quốc Tuấn`. The old names, and `Minh Quân`, still work as `voice`.
- The engine now also loads the model repo's `denoiser.onnx` (43 MB), so the
  packaged build carries it.
- README licence note follows the model card: Apache-2.0 for the weights and the
  preset voices, commercial use allowed.
- One app icon - a white sound wave on a black disc - drawn from one place
  (`icon.py`): the tray, the Start Menu shortcut and the web page's favicon
  (`/favicon.svg`, which used to be a different white square) all show it. Each
  `.ico` size is drawn at its own resolution instead of scaled down from 256 px.

### Fixed

- The window's title bar and taskbar button showed the Python logo (or
  PyInstaller's, in `VoiceTTS.exe`); they show the app icon now, and so does the
  exe file in Explorer.

## [0.4.0] - 2026-10-08

First published release.

### Added

- Desktop app: a native window over a web view that reads mixed Vietnamese/English
  text aloud with VieNeu-TTS v3 Turbo, streaming 48 kHz audio as it is generated.
- iOS dark interface: grouped voice sheet by region, reading speed 0.75x-1.5x,
  live level meter, *Lưu WAV*, a 20 000-character limit reported by the backend.
- Reading speed as a WSOLA time-stretch, so the pitch stays where it is.
- `voice-tts` command line: `gui`, `serve`, `speak`, `voices`, `status`; `speak` plays,
  writes a WAV or raw float32, reads a file or stdin, and works against a server with
  the standard library only.
- `serve` with `--host`, `--port` and an optional token (`Authorization: Bearer` or the
  `/?token=` cookie) for a LAN server.
- `POST /api/tts/stream` answers one 16-bit WAV file with `"format": "wav"`.
- System tray: the window hides there when minimized or closed; `serve --tray` runs
  the server with only an icon.
- Per-user Windows installer (`tool-install.py`): `voice-tts` on `PATH`, Start Menu
  shortcut, optional autostart; Linux install as a Docker server, locally or over ssh.
- Docker image and compose file for a headless Linux server.
- One-file `VoiceTTS.exe` with the model inside, and a console `voice-tts` Linux
  binary; both smoke-tested offline before a release ships them.
- CI on Linux and Windows; a tag builds and publishes the release.

### Fixed

- *Lưu WAV* writes a file again (downloads were cancelled by WebView2).
- The window opens centred at a fixed size.
- The stop button stays for as long as audio plays.
- The model loads from a Linux HuggingFace cache (symlinked snapshots).
- The server listens before handing its socket to uvicorn, so an early request waits
  instead of being refused.
