"""Rewrite technical text, in the ``special`` pronunciation, into words the engine reads
the way Vietnamese engineers say them.

VieNeu hands the text to its front end, sea_g2p, which has no table for embedded or
electronics terms and no way to add one: an upper-case token it does not know is
spelled with Vietnamese letter names (UART *u a rờ tê*), ``5mW`` comes out as
megawatts and ``µ`` is dropped. This module runs before it and leaves only words
sea_g2p already reads right. ``lexicon.py`` holds the whole-word table and the
user's words; ``terms.tsv`` pins what each rule must produce.

Every rewrite is parked behind a placeholder until the end, so a later pass never
rewrites what an earlier one wrote.

Standard library only, like ``lexicon.py``.
"""

from __future__ import annotations

import re

import lexicon

# Placeholders come from Supplementary Private Use Area-A: never a word character,
# a digit or a space, so no pattern here matches into one.
_KEEP_BASE = 0xF0000
_KEPT = re.compile("[\U000F0000-\U000FFFFD]")


class _Kept:
    """Rewrites parked until the end, each behind one placeholder character."""

    def __init__(self) -> None:
        self.items: list[str] = []

    def __call__(self, said: str) -> str:
        self.items.append(said)
        return chr(_KEEP_BASE + len(self.items) - 1)

    def restore(self, text: str) -> str:
        # A parked rewrite can hold placeholders of its own (a split identifier).
        while _KEPT.search(text):
            text = _KEPT.sub(lambda m: self.items[ord(m.group()) - _KEEP_BASE], text)
        return text


DIGITS = ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín")
# sea_g2p drops the first of "năm năm" before a number word (RE_REDUNDANT_NAM, meant
# for a date's doubled "năm"), so 555 read digit by digit loses a five.
_NUMBER_WORDS = set(DIGITS) | {"mười", "mươi", "mốt", "lăm", "tư", "trăm", "nghìn", "ngàn", "triệu", "tỷ"}

# English letter names written so sea_g2p reads them in Vietnamese: "gi" would come
# out as a bare /z/, "kây" as English, "zét" split in two.
EN_LETTERS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (
    "ây", "bi", "xi", "đi", "i", "ép", "di", "ếch", "ai", "giây", "cây", "eo", "em", "en",
    "ô", "pi", "kiu", "a", "ét", "ti", "iu", "vi", "đắp bờ liu", "ích", "oai", "dét")))


def guard_fives(words: list[str]) -> list[str]:
    """A comma after "năm năm" when a number word follows, where sea_g2p would
    otherwise swallow a five: ``năm năm năm`` -> ``năm năm, năm``."""
    words = list(words)
    for i in range(1, len(words) - 1):
        if words[i - 1] == words[i] == "năm" and words[i + 1] in _NUMBER_WORDS:
            words[i] = "năm,"
    return words


def digit_words(digits: str) -> list[str]:
    """``"555"`` -> ``["năm", "năm,", "năm"]``: one word per digit."""
    return guard_fives([DIGITS[int(d)] for d in digits])


# ---------------------------------------------------------------- numbers and units

NUM = r"\d+(?:[.,]\d+)?"
MICRO = "[µμu]"  # U+00B5 MICRO SIGN, U+03BC GREEK MU, and the ASCII stand-in

# Read on every number. sea_g2p gets each of these wrong: V as the letter "vê", mW as
# megawatts, µ dropped, pF/nF/ns/mV as English letters, kΩ as "ca ôm", GHz's "gi"
# without its vowel, mA as "ma" (a ghost).
UNITS = {
    "V": "vôn", "mV": "mi li vôn", "kV": "ki lô vôn", f"{MICRO}V": "mi cờ rô vôn",
    "A": "am pe", "mA": "mi li am pe", f"{MICRO}A": "mi cờ rô am pe", "nA": "na nô am pe",
    "mW": "mi li oát", "mWh": "mi li oát giờ",
    "kΩ": "ki lô ôm", "MΩ": "mê ga ôm", "mΩ": "mi li ôm",
    "F": "pha ra", "pF": "pi cô pha ra", "nF": "na nô pha ra", f"{MICRO}F": "mi cờ rô pha ra",
    "mF": "mi li pha ra",
    f"{MICRO}H": "mi cờ rô hen ri", "mH": "mi li hen ri", "nH": "na nô hen ri",
    f"{MICRO}s": "mi cờ rô giây", "ns": "na nô giây", "ps": "pi cô giây",
    "GHz": "di ga héc", "dBm": "đê bê em",
    "VAC": "vôn a xê", "VDC": "vôn đê xê",
}
# Read right by sea_g2p after a single number; rewritten only after a range, where
# its date pattern takes "1-2" for a day and month and glues "đến hai" to the unit.
RANGE_UNITS = {
    "m": "mét", "cm": "xen ti mét", "mm": "mi li mét", "km": "ki lô mét",
    "s": "giây", "ms": "mi li giây", "Hz": "héc", "kHz": "ki lô héc", "MHz": "mê ga héc",
    "W": "oát", "kW": "ki lô oát", "Ω": "ôm", "g": "gam", "kg": "ki lô gam",
    "dB": "decibel", "°C": "độ xê", "%": "phần trăm",
}
_UNIT_KEYS = sorted({**UNITS, **RANGE_UNITS}, key=len, reverse=True)
_UNIT_ALT = "|".join(k if k.startswith(MICRO) else re.escape(k) for k in _UNIT_KEYS)
_UNIT_RE = {k: re.compile(k if k.startswith(MICRO) else re.escape(k)) for k in _UNIT_KEYS}


def _unit_word(unit: str, ranged: bool) -> str | None:
    for key in _UNIT_KEYS:
        if _UNIT_RE[key].fullmatch(unit):
            return UNITS.get(key) or (RANGE_UNITS[key] if ranged else None)
    return None


# "lớp 5A", "phòng 2A": a class or a room, not amperes.
_NOT_A_QUANTITY = {"lớp", "phòng", "câu", "tổ", "khối", "khu", "dãy", "hạng", "mục", "bàn"}
_LAST_WORD = re.compile(r"(\w+)\s*$")

_QUANTITY = re.compile(
    rf"(?<![\w.,])(?P<num>[-+±]?{NUM})"
    rf"(?:\s*(?:-|–|~)\s*(?P<to>[-+]?{NUM}))?"
    rf"\s?(?P<unit>{_UNIT_ALT})(?!\w)")
# "5V2A", "12V5A": two quantities run together; "3V3" (a 3.3 V rail) is not one.
_GLUED = re.compile(rf"(?<=\d)(V|A)(?={NUM}(?:m?A|V)(?!\w))")
# "3.3V/500mA": a slash between two quantities lists them, "Vcc/2" divides.
_SLASH = re.compile(rf"({NUM}\s?(?:{_UNIT_ALT}))\s*/\s*(?={NUM}\s?(?:{_UNIT_ALT})(?!\w))")
_FRACTION_W = re.compile(r"(?<![\w.,/])1/([2348])\s?W(?!\w)")
_FRACTIONS = {"2": "một phần hai", "3": "một phần ba", "4": "một phần tư", "8": "một phần tám"}
# Resistor value codes: 100R, 0R, 2R2 (R marks the ohms and the decimal point).
_OHM_CODE = re.compile(r"(?<![\w.,])(\d+)R(\d*)(?!\w)")
_MEGOHM = re.compile(rf"\b((?:điện )?trở)\s+({NUM})M(?!\w)")
_CAP = r"(tụ(?:\s+(?:gốm|hóa|hoá|mica|điện|lọc|tantan))?)"
# Ceramic capacitor codes: 104 is 10 x 10^4 pF, said digit by digit. 470 and 220 end
# in 0, so they are values (µF), read as numbers.
_CAP_CODE = re.compile(rf"{_CAP}\s+(\d\d[1-6])(?![\w.,])")
_CAP_PREFIX = re.compile(rf"{_CAP}\s+({NUM})\s?([pnuµμ])(?!\w)")
_CAP_PREFIXES = {"p": "pi cô", "n": "na nô", "u": "mi cờ rô", "µ": "mi cờ rô", "μ": "mi cờ rô"}
_HEX = re.compile(r"(?<![\w.,])0[xX]([0-9A-Fa-f]+)(?!\w)")


def _spell_chars(chars: str) -> str:
    return " ".join(guard_fives([DIGITS[int(c)] if c.isdigit() else EN_LETTERS[c.upper()]
                                 for c in chars]))


def _units(text: str, keep: _Kept) -> str:
    text = _GLUED.sub(r"\1 ", text)
    text = _SLASH.sub(r"\1, ", text)
    text = _FRACTION_W.sub(lambda m: keep(f"{_FRACTIONS[m[1]]} oát"), text)
    text = _CAP_CODE.sub(lambda m: f"{m[1]} {keep(' '.join(digit_words(m[2])))}", text)
    text = _CAP_PREFIX.sub(lambda m: f"{m[1]} {m[2]} {keep(_CAP_PREFIXES[m[3]])}", text)
    text = _MEGOHM.sub(lambda m: f"{m[1]} {m[2]} {keep('mê ga ôm')}", text)
    text = _OHM_CODE.sub(
        lambda m: f"{m[1]},{m[2]} {keep('ôm')}" if m[2] else f"{m[1]} {keep('ôm')}", text)
    text = _HEX.sub(lambda m: keep(f"không ích {_spell_chars(m[1])}"), text)

    def quantity(m: re.Match) -> str:
        before = _LAST_WORD.search(m.string, max(0, m.start() - 24), m.start())
        if before and before[1].lower() in _NOT_A_QUANTITY:
            return m[0]
        word = _unit_word(m["unit"], ranged=m["to"] is not None)
        if word is None:
            return m[0]
        amount = f"{m['num']} {keep('đến')} {m['to']}" if m["to"] else m["num"]
        return f"{amount} {keep(word)}"

    return _QUANTITY.sub(quantity, text)


# ---------------------------------------------------------------- entry point

def _unicode(text: str) -> str:
    # U+2212 MINUS SIGN: sea_g2p drops it, so −40°C would lose its sign.
    return text.replace("−", "-")


def _rewrite(text: str, user) -> str:
    keep = _Kept()
    text = _unicode(text)
    text = lexicon.sub(text, user, keep)
    text = _units(text, keep)
    return keep.restore(text)


def special(text: str, user=()) -> str:
    """``text`` as the ``special`` pronunciation sends it to the engine.

    ``user`` is the user's lexicon, a list of ``{"word", "say", "matchCase"}``; what
    the user and the built-in lexicon say wins over every rule. ``<en>`` spans are
    left as they are.
    """
    parts = lexicon._EN_SPAN.split(text)
    for i in range(0, len(parts), 2):  # odd indexes are the <en> spans
        parts[i] = _rewrite(parts[i], user)
    return "".join(parts)
