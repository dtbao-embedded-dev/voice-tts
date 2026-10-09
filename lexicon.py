"""Respell the words the engine's text front end gets wrong, before it sees them.

VieNeu's normalizer (sea_g2p) spells an upper-case token it does not know as an
English acronym with Vietnamese letter names: ``POST`` becomes *phê ô ét tê*,
``GET`` *gờ e tê*. It lower-cases ``AP`` into the syllable *ap*, and reads
``Board`` as English where a Vietnamese engineer says *bo*. Each entry here
replaces a whole word with a spelling the engine reads the way people say it.

Whole words only - ``POSTMAN``, ``APP`` and ``onboard`` stay as they are - and
nothing inside ``<en>...</en>``, which the caller has already marked as English.

Users add their own words on top (``lexicon.json`` in the data dir). A user
word replaces a built-in one with the same spelling, and at any place the
longest word wins, so ``ESP32 S3`` is read as a whole before ``ESP32`` is.
Standard library only: the CLI edits the file without the backend installed.
"""

from __future__ import annotations

import functools
import json
import os
import re
import sys
import threading
from pathlib import Path

# (word, spoken as, match case). Upper-case-only entries leave the lower-case
# word alone: "post" is already read as English, and "ap" may be something else.
ENTRIES = (
    ("POST", "post", True),
    ("GET", "get", True),
    ("PUT", "put", True),
    ("PATCH", "patch", True),
    ("DELETE", "delete", True),
    # Vietnamese letter names: "<en>a p</en>" reads right too, but its English
    # vowel was heard as "IP" in listening tests (docs/verify-whisper.md).
    ("AP", "ây pi", True),
    ("board", "bo", False),
    # ESP32 came out "e ét phê ba hai", esp32 as the syllable "esp" and "ba mươi
    # hai"; engineers say the letters the English way and the digits one by one.
    ("esp32", "i ét pi ba hai", False),
    # Typed with a space it read "e ét phê ba mươi hai".
    ("esp 32", "i ét pi ba hai", False),
)

ENV_DATA = "VOICE_TTS_DATA"
USER_FILE = "lexicon.json"
MAX_ENTRIES, MAX_WORD, MAX_SAY = 500, 64, 128

_EN_SPAN = re.compile(r"(<en>.*?</en>)", re.IGNORECASE | re.DOTALL)
_save_lock = threading.Lock()


def data_dir() -> Path:
    """Where the app keeps what the user made: ``$VOICE_TTS_DATA``, else the
    platform's per-user data folder."""
    if os.environ.get(ENV_DATA):
        return Path(os.environ[ENV_DATA])
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(base) / "VoiceTTS"
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "voice-tts"


def user_path() -> Path:
    return data_dir() / USER_FILE


def builtin() -> list[dict]:
    return [{"word": w, "say": s, "matchCase": c} for w, s, c in ENTRIES]


def validate(entries) -> list[dict]:
    """Normalized copies of ``entries``; ``ValueError`` names the first bad one."""
    if not isinstance(entries, list):
        raise ValueError("Từ điển phải là một danh sách.")
    if len(entries) > MAX_ENTRIES:
        raise ValueError(f"Từ điển tối đa {MAX_ENTRIES} từ.")
    out, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Mỗi mục cần word và say.")
        word = str(entry.get("word", "")).strip()
        say = str(entry.get("say", "")).strip()
        if not 1 <= len(word) <= MAX_WORD:
            raise ValueError(f"Từ phải dài 1-{MAX_WORD} ký tự: '{word}'.")
        if not 1 <= len(say) <= MAX_SAY:
            raise ValueError(f"Cách đọc của '{word}' phải dài 1-{MAX_SAY} ký tự.")
        if word.casefold() in seen:
            raise ValueError(f"Từ '{word}' bị lặp.")
        seen.add(word.casefold())
        out.append({"word": word, "say": say, "matchCase": bool(entry.get("matchCase", False))})
    return out


def load_user(path: Path | None = None) -> list[dict]:
    """The user's words; none yet is an empty list, a broken file a ``ValueError``."""
    path = path or user_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise ValueError(f"Không đọc được {path}: {exc}") from None
    return validate(raw.get("entries") if isinstance(raw, dict) else raw)


def save_user(entries, path: Path | None = None) -> list[dict]:
    """Validate and store ``entries``; return what was stored."""
    entries = validate(entries)
    path = path or user_path()
    with _save_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write beside it and swap in: a crash mid-write never leaves half a file.
        staged = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        staged.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        os.replace(staged, path)
    return entries


@functools.lru_cache(maxsize=8)
def _matcher(user: tuple[tuple[str, str, bool], ...]):
    """One pattern for every word, longest first, and what each alternative says.

    A single pass, so a spelling one entry produces is never respelled by another.
    Each word is a named group: the match names its own entry, where a casefold
    lookup would miss text the case-insensitive match accepts ("Wıfı" for wifi).
    """
    table = {w.casefold(): (w, s, c) for w, s, c in ENTRIES}
    table.update({w.casefold(): (w, s, c) for w, s, c in user})  # the user's word wins
    words = sorted(table.values(), key=lambda e: len(e[0]), reverse=True)
    alternatives = "|".join(
        f"(?P<w{i}>{re.escape(w) if c else f'(?i:{re.escape(w)})'})"
        for i, (w, _, c) in enumerate(words))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)"), [s for _, s, _ in words]


def apply(text: str, user=()) -> str:
    """``text`` with every lexicon word respelled, ``<en>`` spans untouched.

    ``user`` is a list of ``{"word", "say", "matchCase"}`` laid over the built-ins.
    """
    pattern, says = _matcher(tuple((e["word"], e["say"], e["matchCase"]) for e in user))
    spoken = lambda m: says[int(m.lastgroup[1:])]  # noqa: E731
    parts = _EN_SPAN.split(text)
    for i in range(0, len(parts), 2):  # odd indexes are the <en> spans
        parts[i] = pattern.sub(spoken, parts[i])
    return "".join(parts)
