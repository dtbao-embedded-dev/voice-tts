# Voice TTS

Desktop app that reads mixed Vietnamese/English text aloud, powered by
[VieNeu-TTS v3 Turbo](https://github.com/pnnbao97/VieNeu-TTS).

- **UI** — a web view hosted in a native window (pywebview / WebView2). It behaves
  like an app: no reload, no context menu, no find bar, no zoom, no text selection
  outside the editor.
- **Backend** — Python (FastAPI + uvicorn) bound to a loopback port, streaming
  48 kHz audio as it is generated.
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
| `python docs/scripts/tool-build.py --package` | build `dist/VoiceTTS/` with PyInstaller |
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
| `GET /api/voices` | 25 preset voices with region, gender and description |
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
  The window shows *Đang tải model…* until it is ready.
- **The packaged build does not bundle the model** — it downloads on first launch,
  which keeps `dist/` small enough to move around.

## Layout

```
app.py                    FastAPI backend + native window entry point
test_tts.py               assert-based smoke test over the real HTTP path
web/                      index.html, app.css, app.js - no build step
docs/scripts/tool-build.py  setup / run / check / package
```
