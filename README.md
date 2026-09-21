# Voice TTS

Desktop app that reads mixed Vietnamese/English text aloud, powered by
[VieNeu-TTS v3 Turbo](https://github.com/pnnbao97/VieNeu-TTS).

- **UI** — web view rendered in a native desktop window (pywebview / WebView2).
- **Backend** — Python (FastAPI + uvicorn) on a local port, streaming 48 kHz audio.

## Quick start

```
python docs/scripts/tool-build.py
```

See `docs/scripts/tool-build.py --help` for the packaging and check modes.
