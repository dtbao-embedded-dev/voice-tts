# Voice TTS

Desktop app that reads mixed Vietnamese/English text aloud, powered by
[VieNeu-TTS v3 Turbo](https://github.com/pnnbao97/VieNeu-TTS).

- **UI** — a web view hosted in a native window (pywebview / WebView2). It behaves
  like an app: no reload, no context menu, no find bar, no zoom, no text selection
  outside the editor.
- **Backend** — Python (FastAPI + uvicorn) bound to a loopback port, streaming
  48 kHz audio as it is generated.
- **Limit** — 20 000 characters per request, enforced by the backend and reported to
  the UI by `/api/voices`, so the field and the counter never drift from it.
- **Model** — v3 Turbo is bilingual, so Vietnamese and English mix freely inside one
  sentence; no language tagging or manual splitting is needed.

## Quick start

```
python docs/scripts/tool-build.py
```

That creates `.venv`, installs `requirements.txt`, downloads the model into the
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
.venv/Scripts/python app.py --no-window  # backend only, on port 8760
```

## HTTP API

| Endpoint | Response |
| --- | --- |
| `GET /api/status` | `{"state": "loading" \| "ready" \| "error"}` while the model warms up |
| `GET /api/voices` | 25 preset voices with region, gender and description, plus `maxChars` |
| `POST /api/tts/stream` | raw float32 LE mono at 48 kHz, streamed as it is generated |

```
curl -X POST http://127.0.0.1:8760/api/tts/stream \
  -H "Content-Type: application/json" \
  -d '{"text": "Deploy model lên production server.", "voice": "Mai Anh"}' \
  --output speech.f32
```

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
- **The packaged build is one self-contained `VoiceTTS.exe`** (~400 MB): the runtime,
  the web view and both model repos (backbone + audio codec) are inside it, and it
  points `HF_HOME` at its own copy with `HF_HUB_OFFLINE=1`, so it never touches the
  network. The price is that a one-file build unpacks itself into `%TEMP%` on *every*
  launch — measured ~10 s from launch to *Sẵn sàng* here, longer on a cold machine
  while Defender scans it.
- **Reading speed is a playback rate, not an engine setting.** v3 Turbo has no speed
  parameter, so the 0.75×–1.5× buttons set `playbackRate` on the streamed buffers:
  faster is also higher-pitched. A saved WAV carries the speed it was read at.
- **The voices are licensed for non-commercial use only.** Bundling them into the exe
  redistributes them; check the VieNeu terms before handing the file to anyone.
- **The UI is black and white, dark only.** There is no light variant and no theme
  switch; status is told apart by shape, not colour.

## Layout

```
app.py                    FastAPI backend + native window entry point
test_tts.py               assert-based smoke test over the real HTTP path
web/                      index.html, app.css, app.js - no build step
docs/scripts/tool-build.py  setup / run / check / package
```
