"""Respell the words the engine's text front end gets wrong, before it sees them.

VieNeu's normalizer (sea_g2p) spells an upper-case token it does not know as an
English acronym with Vietnamese letter names: ``POST`` becomes *phê ô ét tê*,
``GET`` *gờ e tê*. It lower-cases ``AP`` into the syllable *ap*, and reads
``Board`` as English where a Vietnamese engineer says *bo*. Each entry here
replaces a whole word with a spelling the engine reads the way people say it.

Whole words only - ``POSTMAN``, ``APP`` and ``onboard`` stay as they are - and
nothing inside ``<en>...</en>``, which the caller has already marked as English.
"""

from __future__ import annotations

import re

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

_EN_SPAN = re.compile(r"(<en>.*?</en>)", re.IGNORECASE | re.DOTALL)


def _compile(word: str, case: bool) -> re.Pattern:
    return re.compile(rf"(?<!\w){re.escape(word)}(?!\w)", 0 if case else re.IGNORECASE)


_RULES = [(_compile(word, case), spoken) for word, spoken, case in ENTRIES]


def apply(text: str) -> str:
    """``text`` with every lexicon word respelled, ``<en>`` spans untouched."""
    parts = _EN_SPAN.split(text)
    for i in range(0, len(parts), 2):  # odd indexes are the <en> spans
        for pattern, spoken in _RULES:
            parts[i] = pattern.sub(spoken, parts[i])
    return "".join(parts)
