# Decisions from studying other repositories

Append-only. Each entry is a pattern seen elsewhere and why it was or was not
taken here; a changed verdict gets a new entry and the old one a `Superseded-by`
line. Adopted patterns are not listed: their record is the commit that landed them.

### 2026-10-09 — Upgrade vieneu past 3.8.3
- Upstream: https://github.com/pnnbao97/VieNeu-TTS@8534432
- Verdict: reject
- Status: rejected
- Reason: the installed 3.8.3 is upstream HEAD for the whole text pipeline (`diff -w`); HEAD adds only `check_sampling`, a GPU guard for sampling settings this app never passes.
- Superseded-by: none

### 2026-10-09 — Upgrade sea-g2p to 0.10.0
- Upstream: https://github.com/pnnbao97/sea-g2p@e825173
- Verdict: reject
- Status: rejected
- Reason: 0.10.0 adds a C ABI and moves the PyO3 wrapper; the Vietnamese normalizer reads the same, so none of the unit or acronym faults it has is fixed by it.
- Superseded-by: none

### 2026-10-09 — Fork sea-g2p, or rebuild its sea_g2p.bin, to add embedded terms
- Upstream: https://github.com/pnnbao97/sea-g2p@e825173
- Verdict: reject
- Status: rejected
- Reason: its tables are compiled into the Rust crate and its dictionary path is ignored (`g2p.py:32`), so a fork means maintaining a Rust build; `respell.py` before it reaches the same words.
- Superseded-by: none

### 2026-10-09 — Sentence splitting, chunk packing, short-chunk merge, pause table, repetition window
- Upstream: https://github.com/pnnbao97/VieNeu-TTS@8534432
- Verdict: reject
- Status: rejected
- Reason: already in effect: the server reads through `infer_stream` / `infer`, which run `normalize_to_chunks_v3_with_gaps` and the rest; adopting them again would be two mechanisms for one job.
- Superseded-by: none

### 2026-10-09 — Guard against a repeated phrase by frames per phoneme character
- Upstream: https://github.com/pnnbao97/VieNeu-TTS@8534432
- Verdict: reject
- Status: rejected
- Reason: a measured loop adds 15-20 % frames to a 120-character chunk, inside the normal spread (p50 0.53, p99 1.10 frames per phoneme character), so no threshold catches it without rejecting good readings; `CHUNK_CHARS = 120` already gave 0 of 20.
- Superseded-by: none

### 2026-10-09 — Whisper verify and automatic re-read inside the server
- Upstream: https://github.com/pnnbao97/VieNeu-TTS@8534432 (and docs/verify-whisper.md here)
- Verdict: reject
- Status: rejected
- Reason: deliberately deferred here before: it adds ~1 GB to the installer and hit NSIS's 2 GB limit; scoring takes belongs to the client (OpenMontage `takes.py`).
- Superseded-by: none

### 2026-10-09 — Expose sampling settings (temperature, top_k...) in the API
- Upstream: https://github.com/pnnbao97/VieNeu-TTS@8534432
- Verdict: reject
- Status: rejected
- Reason: no failure here calls for them; they widen the API and the queue's cost per reading.
- Superseded-by: none

### 2026-10-09 — Codec padding of a cloned voice's reference audio
- Upstream: https://github.com/pnnbao97/VieNeu-TTS@8534432
- Verdict: reject
- Status: rejected
- Reason: the app reads with preset voices only and never clones one.
- Superseded-by: none

### 2026-10-09 — Move to another bilingual model (ZeroTTS, MOSS-TTS, Chatterbox...)
- Upstream: https://github.com/nguyenhungplatform/ZeroTTS (and others, fetched 2026-10-09)
- Verdict: reject
- Status: rejected
- Reason: the faults found were in the text front end, not the model; the alternatives' quality claims are their own, none compared against VieNeu, and most need a GPU this server lacks.
- Superseded-by: none

### 2026-10-09 — Report sea-g2p's unit and number faults upstream
- Upstream: https://github.com/pnnbao97/sea-g2p@e825173
- Verdict: decision-item
- Status: rejected
- Reason: the owner chose to fix them on this side only (mW read as megawatts, µ dropped, 1-2m as a date, 0x as times, "gi" without its vowel, "năm năm" before a number word losing a five).
- Superseded-by: none
