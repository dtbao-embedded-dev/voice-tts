# Verify mode with Whisper (deferred)

Status: **not in the app.** A working version was built and then taken out before
release, so the installer stays small and nothing ships half-decided. This note keeps
what it used, what was measured and where the code is, for when it comes back.

## The idea

Two modes per reading:

1. **No verify** (what ships): the audio streams as it is generated.
2. **Verify:** synthesize the whole text, have an ASR model transcribe the audio,
   score the transcript against the text, and send/play/save the audio only when the
   score is at least a threshold (95 %); otherwise report an error with the score and
   what was heard, and send no audio.

## What it used

| Piece | Choice | Why |
| --- | --- | --- |
| ASR model | Whisper **large-v3-turbo** | large-v3 accuracy on Vietnamese + English, ~6-8x faster than large-v3; this box has no GPU |
| Runtime | [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (CTranslate2), `device="cpu"`, `compute_type="int8"`, `cpu_threads` = half the logical CPUs | no torch at runtime; int8 is the fast CPU path |
| Decoding | `language="vi"`, `beam_size=5`, `condition_on_previous_text=False`, **no `initial_prompt`** | prompting with the expected text biases Whisper into "hearing" it, so the check would pass by construction |
| Resampling | `soxr`, 48 kHz -> 16 kHz | already a dependency of the TTS engine |
| Score | `1 - CER` with [`rapidfuzz`](https://github.com/rapidfuzz/RapidFuzz) `Levenshtein.distance`, clamped to 0..1 | pure-Python edit distance is O(n*m), too slow at the 20 000-character limit |
| Canonical text | apply `lexicon.py` to **both** sides, strip `<en>` tags, NFC, lower-case, keep letters and digits only (spaces dropped) | Whisper writes case, spacing and punctuation its own way ("ESP 32", "Post"); a lost diacritic still counts |
| Threshold | `min_score` 0.95, configurable 0..1 | the user's "95 % ok" |
| Model load | lazily on the first check, behind a lock; one transcription at a time | ~1.6 GB RAM, most readings never ask |

## Interface it had

- HTTP: `POST /api/tts/stream` with `"verify": true` and `"min_score"`. Pass: the
  body in the requested `format`, plus `X-Verify-Score` (`0.9630`) and
  `X-Verify-Transcript` (percent-encoded UTF-8, headers are Latin-1). Fail: `422`
  `{"detail", "score", "transcript", "minScore"}`. Cannot run: `503`.
  `/api/status` carried `"verify": {"available", "detail"}`.
- CLI: `voice-tts speak --verify [--min-score X]`; a rejected reading exits 1 and
  writes no file.
- UI: a *Kiểm tra* switch; the status line showed *Khớp 96.3%* or the rejection with
  what Whisper heard; greyed out when unavailable.

## Measured (2026-10-09, 20-thread CPU, no GPU)

- Speed: ~6-7 s per check for up to 30 s of audio (Whisper pads to 30 s windows),
  plus ~10 s to load the model the first time.
- A clean sentence ("Chào bạn, hôm nay chúng ta sẽ deploy một model mới lên
  server.") scores 1.000; an unrelated sentence against it scores < 0.5.
- It catches real slips: "text-to-speech" once heard as "Take-to-Speak" (0.914).
- "Gửi request POST tới AP trên Board." read as typed: **0.786** (heard "FOST từ
  Actionboard"); with the `special` pronunciation: 0.926-1.000 depending on voice
  and run.
- The TTS is not deterministic: the same text scores differently run to run, and
  short sentences swing hardest (one character is a large share). "bo" at the end of
  a sentence was sometimes heard as "bò" or "bar". At 95 % expect occasional
  rejections of readings that sound fine; an automatic re-read (1-2 tries) before
  reporting failure is the obvious next step.
- `ESP32` read as typed came out "e ét phê ba hai" and scored 0.74-0.91; that led to
  the `ESP32` lexicon entry.
- `AP` respelled as `<en>a p</en>` was often heard as "IP"; the Vietnamese spelling
  "ây pi" scored 1.000 on both voices tried, hence the lexicon entry.

## Packaging lessons

- The published CTranslate2 copies of large-v3-turbo
  (`mobiuslabsgmbh/faster-whisper-large-v3-turbo`) are **fp16, 1.6 GB**. With one
  inside, the desktop folder was 2.5 GB and `makensis` (32-bit) failed:
  `Internal compiler error #12345: error mmapping datablock` - NSIS's 2 GB limit.
- Fix that worked: convert `openai/whisper-large-v3-turbo` to **int8** weights at
  build time (`ct2-transformers-converter --quantization int8 --copy_files
  tokenizer.json preprocessor_config.json`, in a build-only venv with transformers +
  CPU torch, ~3.5 min), 0.8 GB. Results match fp16, since the model ran in int8
  anyway. Folder 1.7 GB, installer **~1 GB** (from 330 MB), LZMA ~17 min.
- Stored as a local HF-cache repo (`voice-tts/whisper-large-v3-turbo-int8`, at the
  source revision) so the offline app finds it with `try_to_load_from_cache`.
- PyInstaller needed `--collect-all faster_whisper ctranslate2 rapidfuzz` (PyAV has
  its own hook). The one-file server build should leave Whisper out (it would unpack
  into `%TEMP%` on every launch) and report verify unavailable.
- `tool-build.py --smoke-installer` needs an elevated terminal (the installer asks
  for admin); it was never run for the Whisper build.

## Where the code is

Removed in the commit that added this note; the full implementation is in the
history of branch `feat/lexicon-whisper-verify`:

| Commit | What |
| --- | --- |
| `531d26a` | `verify.py` (transcribe + score), deps, tests |
| `8fb9336` | verify mode in `/api/tts/stream` and `speak --verify` |
| `1460141` | the *Kiểm tra* switch in the UI |
| `792be85` | int8 conversion and bundling in `tool-build.py`, smoke checks |

`git show df9624f:verify.py` prints the last version of the module.
