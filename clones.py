"""Voices the user cloned from a clip of their own.

The engine enrolls a clip into a speaker embedding and reference codes once; that
pair is all a reading needs, so it is what is kept - in ``voices.json`` in the
data dir, next to ``lexicon.json`` - and the clip itself is not. A reading passes
the pair to the engine as a ``voice`` dict, which v3 Turbo takes in place of a
preset name.

One list per data dir: on a LAN server everyone who holds the token reads, and
edits, the same one.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import numpy as np

import lexicon

USER_FILE = "voices.json"
MAX_VOICES, MAX_NAME, MAX_DESCRIPTION = 50, 40, 120

_lock = threading.Lock()


def user_path() -> Path:
    return lexicon.data_dir() / USER_FILE


def check_name(name) -> str:
    """``name`` trimmed; ``ValueError`` if it cannot name a voice."""
    name = str(name or "").strip()
    if not 1 <= len(name) <= MAX_NAME:
        raise ValueError(f"Tên giọng phải dài 1-{MAX_NAME} ký tự.")
    if any(ch in name for ch in "/\\") or not name.isprintable():
        raise ValueError("Tên giọng không được chứa /, \\ hay ký tự điều khiển.")
    return name


def _record(raw) -> dict:
    """A stored voice, validated, with its arrays back as numpy."""
    if not isinstance(raw, dict):
        raise ValueError("Mỗi giọng cần name và speaker_emb.")
    emb = raw.get("speaker_emb")
    if not isinstance(emb, list) or not emb:
        raise ValueError(f"Giọng '{raw.get('name')}' thiếu speaker_emb.")
    codes = raw.get("codes")
    return {
        "name": check_name(raw.get("name")),
        "description": str(raw.get("description", ""))[:MAX_DESCRIPTION],
        "speaker_emb": np.asarray(emb, dtype=np.float32),
        "codes": None if codes is None else np.asarray(codes, dtype=np.int64),
    }


def load(path: Path | None = None) -> list[dict]:
    """The cloned voices; none yet is an empty list, a broken file a ``ValueError``."""
    path = path or user_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise ValueError(f"Không đọc được {path}: {exc}") from None
    entries = raw.get("voices") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"Không đọc được {path}: thiếu danh sách voices.")
    return [_record(e) for e in entries]


def find(name: str | None, path: Path | None = None) -> dict | None:
    if not name:
        return None
    return next((v for v in load(path) if v["name"] == name), None)


def _write(voices: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"voices": [
        {
            "name": v["name"],
            "description": v["description"],
            "speaker_emb": [round(float(x), 6) for x in np.asarray(v["speaker_emb"]).reshape(-1)],
            # Frames x codebooks: the shape is part of the voice, keep it.
            "codes": None if v["codes"] is None else np.asarray(v["codes"]).tolist(),
        }
        for v in voices
    ]}
    # Write beside it and swap in: a crash mid-write never leaves half a file.
    staged = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    staged.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(staged, path)


def check_new(name, taken=lambda name: False, path: Path | None = None) -> str:
    """``name`` trimmed, if a new voice may take it; ``taken(name)`` says whether a
    preset already has it. Cheap, so a request can be refused before enrolling."""
    name = check_name(name)
    if taken(name):
        raise ValueError(f"Đã có giọng có sẵn tên '{name}'.")
    voices = load(path)
    if any(v["name"].casefold() == name.casefold() for v in voices):
        raise ValueError(f"Đã có giọng tên '{name}'.")
    if len(voices) >= MAX_VOICES:
        raise ValueError(f"Tối đa {MAX_VOICES} giọng của bạn.")
    return name


def add(name: str, speaker_emb, codes, description: str = "",
        taken=lambda name: False, path: Path | None = None) -> dict:
    """Store a new voice; ``taken`` as for ``check_new``."""
    path = path or user_path()
    with _lock:
        name = check_new(name, taken, path)
        record = _record({
            "name": name,
            "description": description,
            "speaker_emb": np.asarray(speaker_emb, dtype=np.float32).reshape(-1).tolist(),
            "codes": None if codes is None else np.asarray(codes).tolist(),
        })
        _write([*load(path), record], path)
    return record


def remove(name: str, path: Path | None = None) -> bool:
    """Drop a voice; ``False`` if there was none by that name."""
    path = path or user_path()
    with _lock:
        voices = load(path)
        kept = [v for v in voices if v["name"] != name]
        if len(kept) == len(voices):
            return False
        _write(kept, path)
    return True
