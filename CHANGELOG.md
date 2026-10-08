# Changelog

Every user-visible change, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the version is
`cli.__version__`. A release publishes its own section as the GitHub Release notes
(`tool-build.py --release-notes <version>`), and a tag without a section here fails
the release before it builds.

## [Unreleased]

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
