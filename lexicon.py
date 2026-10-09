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
    # Measured 2026-10-09, Whisper large-v3, two sentences: "ây pi" heard AP
    # 63/70, "ê pi" 61/70, "ế pi" 34/40, "<en>a p</en>" 16/30, "êy pi" 0/30,
    # "a pi" 6/40 (as "API"). The misses left are the engine's sampling, not
    # the spelling.
    ("AP", "ây pi", True),
    ("board", "bo", False),
    # ESP32 came out "e ét phê ba hai", esp32 as the syllable "esp" and "ba mươi
    # hai"; engineers say the letters the English way and the digits one by one.
    ("esp32", "i ét pi ba hai", False),
    # Typed with a space it read "e ét phê ba mươi hai".
    ("esp 32", "i ét pi ba hai", False),
    # On its own ("ESP HTTP client") it read "e ét phê", heard as "ESV" or "es phê".
    ("esp", "i ét pi", False),
    # Glued variants the esp32 entry cannot reach as a whole word.
    ("esp32s3", "i ét pi ba hai ét ba", False),
    ("esp32c3", "i ét pi ba hai xi ba", False),
    ("esp32c6", "i ét pi ba hai xi sáu", False),
    ("esp32h2", "i ét pi ba hai hát hai", False),

    # Upper-case words said as words, which respell.py's acronym rule would spell.
    ("OK", "ô kê", True),
    ("FIFO", "phai phô", False),
    ("LIFO", "lai phô", False),
    ("ASCII", "ascii", True),
    ("YAML", "yaml", True),
    ("SPIFFS", "spiffs", False),
    ("FATFS", "fat ép ét", False),
    # ELF and MAC are left to respell.py's letters: measured 2026-10-09, Whisper
    # large-v3, 5 takes each, "elf" heard ELF 1/5 against "i eo ép" 3/5, "mác" and
    # "<en>mac</en>" MAC 0/5 (both "Mark") against "em ây xi" 5/5.
    ("TAG", "tag", True),
    ("SHA", "sha", True),
    ("SHA256", "sha hai năm sáu", False),
    ("JTAG", "giây tag", False),
    ("ARM", "arm", True),
    ("RISC-V", "risk five", False),
    # The RAM kinds keep "ram" as the word it is.
    ("PSRAM", "pi ét ram", False),
    ("SRAM", "ét ram", False),
    ("DRAM", "đi ram", False),
    ("IRAM", "ai ram", False),
    # "i i pi rom": with "prom" both "i" flip to English /aɪ/.
    ("EEPROM", "i i pi rom", False),

    # Mixed case and joined names the rules do not split.
    ("ESP-NOW", "i ét pi nao", False),
    ("USB-C", "iu ét bi xi", False),
    ("type-C", "type xi", False),
    ("LEDC", "led xi", True),
    ("SoC", "ét ô xi", True),
    ("MicroSD", "micro ét đi", False),
    ("DevKitC", "dev kit xi", False),
    ("FreeRTOS", "free a ti ô ét", False),
    ("PlatformIO", "platform ai ô", False),
    ("OpenOCD", "open ô xi đi", False),
    ("mDNS", "em đi en ét", True),
    ("softAP", "soft ây pi", False),
    ("nRF52840", "en a ép năm hai tám bốn không", False),
    ("ATmega328P", "ây ti mega ba hai tám pi", False),
    ("Raspberry Pi", "raspberry pai", False),
    # "tri" is read /tʃi/ even inside <en>.
    ("tri-state", "try state", False),
    ("8N1", "tám en một", False),

    # Code and tools.
    ("memcpy", "mem copy", True),
    ("printf", "print ép", True),
    ("CMake", "xi make", False),
    ("idf.py", "ai đi ép chấm pai", False),
    ("base64", "base sáu tư", False),
    ("ota", "ô ti ây", False),  # in lower case it is read as an English word
    ("tty", "ti ti oai", True),
    ("Ctrl+C", "control xi", False),
    ("Ctrl+]", "control ngoặc vuông", False),
    ("HTTP/1.1", "hát ti ti pi một chấm một", True),
    ("802.11", "tám không hai chấm một một", False),
    ("b/g/n", "bi di en", False),
    ("panic'ed", "panic", False),

    # Power rails and transistor quantities, with Vietnamese letter names like GND.
    # One entry per spelling in any case: "VOUT" and "Vout" would be one key.
    ("VIN", "vê in", True),  # "Vin" is a brand
    ("VOUT", "vê ao", False),
    ("VREF", "vê rép", False),
    ("VBUS", "vê bớt", False),
    ("VBAT", "vê bát", False),
    ("hFE", "hát ép e", True),
    ("ic", "i xê", False),  # also Ic, the collector current; sea_g2p reads "ic" /aɪk/
    ("Ib", "i bê", True),

    # Loanwords as Vietnamese engineers say them.
    ("module", "mô đun", False),
    ("mass", "mát", False),
    ("Gerber", "gơ bơ", False),
    ("DIP", "đíp", True),
    ("SOT", "sót", True),
    # Package names, digit by digit: "SOT-23-5" reads as the range "23 to 5".
    ("SOT23", "sót hai ba", True),
    ("SOT-23", "sót hai ba", True),
    ("SOT-23-5", "sót hai ba năm", True),
    ("SOT-23-6", "sót hai ba sáu", True),
    ("SOT-223", "sót hai hai ba", True),
    ("SOT-89", "sót tám chín", True),
    ("LiPo", "li pô", False),
    # A cell size, not eighteen thousand: heard 18650 5/5, "một tám sáu năm không" 4/5.
    ("18650", "mười tám sáu năm mươi", False),

    # Vietnamese abbreviations, said in full.
    ("VĐK", "vi điều khiển", True),
    ("VXL", "vi xử lý", True),
    ("HĐH", "hệ điều hành", True),
    ("CSDL", "cơ sở dữ liệu", True),
    ("CTDL", "cấu trúc dữ liệu", True),
    ("ĐTDĐ", "điện thoại di động", True),
    ("KTĐT", "kỹ thuật điện tử", True),
    ("ĐKTĐ", "điều khiển tự động", True),
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


def sub(text: str, user=(), wrap=lambda say: say) -> str:
    """``text`` with every lexicon word replaced by ``wrap(its spelling)``.

    ``<en>`` spans are the caller's business: this sees only the text it is given.
    """
    pattern, says = _matcher(tuple((e["word"], e["say"], e["matchCase"]) for e in user))
    return pattern.sub(lambda m: wrap(says[int(m.lastgroup[1:])]), text)


def apply(text: str, user=()) -> str:
    """``text`` with every lexicon word respelled, ``<en>`` spans untouched.

    ``user`` is a list of ``{"word", "say", "matchCase"}`` laid over the built-ins.
    """
    parts = _EN_SPAN.split(text)
    for i in range(0, len(parts), 2):  # odd indexes are the <en> spans
        parts[i] = sub(parts[i], user)
    return "".join(parts)
