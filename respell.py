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
# out as a bare /z/, "kây" as English, "zét" split in two. H is the Vietnamese
# "hát": measured 2026-10-09 (Whisper large-v3, 5 takes each), "ếch" was heard as X
# (HAL 0/5 "XAL", DHT22 0/5 "DXT22", HTTP 3/5) and "ết" as S (HAL 0/5, DHT22 0/5),
# "hát" gave HAL 5/5, DHT22 4/5, HTTP 4/5. R is "ar", which sea_g2p reads as the
# English letter /ɑːɹ/: "a" was heard as A (RTC 1/5 "ATC", RTOS 0/5 "ATOS", RP2040 0/5,
# AVR 0/5) and "rờ" as "dờ" (RX 0/5 "giờ x"); "ar" gave RTC 5/5, RTOS 4/5, RP2040 4/5,
# AVR 3/5, FreeRTOS 5/5 and kept UART and RGB at 5/5. RX stays weak: 4 of 10.
EN_LETTERS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (
    "ây", "bi", "xi", "đi", "i", "ép", "di", "hát", "ai", "giây", "cây", "eo", "em", "en",
    "ô", "pi", "kiu", "ar", "ét", "ti", "iu", "vi", "đắp bờ liu", "ích", "oai", "dét")))


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


# ---------------------------------------------------------------- acronyms

# Vietnamese letter names, as electronics people spell power rails, reference
# designators and analog parts (GND gờ nờ đê, R1 rờ một). sea_g2p's own table, but Q
# is "cu": its "qui" comes out /kwj/, with no vowel.
VI_LETTER_NAMES = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (
    "a", "bê", "xê", "đê", "e", "ép", "gờ", "hát", "i", "giây", "ca", "lờ", "mờ", "nờ",
    "ô", "phê", "cu", "rờ", "ét", "tê", "u", "vê", "vê kép", "ích", "y", "dét")))

# Spelled with Vietnamese letter names: power and ground, the analog, power and
# passive side, PCB and package words. Everything digital - MCU, bus, protocol,
# software - takes the English letter names. GND "gờ nờ đê" was heard as GND 11/15
# over three carrier sentences, the English "di en đi" 7/15 ("di" heard as Z).
ELECTRICAL = {
    "GND", "AGND", "DGND", "PGND", "VCC", "VDD", "VSS", "VEE", "AC", "DC",
    "IC", "PCB", "PCBA", "SMD", "THT", "LDO", "SMPS", "ESR", "ESL", "ESD", "TVS", "EMI", "EMC",
    "BJT", "NPN", "PNP", "IGBT", "JFET", "FET", "NTC", "PTC", "LDR", "UPS", "VOM",
    "QFN", "BGA", "TQFP", "LQFP", "SOIC", "SOP", "SSOP", "TSSOP", "SMA", "SMB", "SMC", "SMBJ",
}
# Part numbers of analog, power and discrete parts: LM358, NE555, AMS1117, TP4056...
ELECTRICAL_PARTS = re.compile(
    r"(?:LM|NE|AMS|TP|MP|XL|IRF|IRLZ|BC|BD|TL|LT|AO|SS|MC|LD|ULN|TIP|HT|CR)\d")
# Reference designators standing alone: R1, C12, U3, SW1 (not the C3 of ESP32-C3).
DESIGNATOR = re.compile(r"([RCLUQDJFKT]|SW|TP|BT|VR|RV|FB)(\d{1,3})")
# Through-hole packages, TO-220 and DO-41: Vietnamese letters before the "-number".
_PACKAGES = {"TO", "DO", "SOD"}
_PACKAGE_NUMBER = re.compile(r"-\d")

# Acronyms sea_g2p 0.9.1 already reads as words (WORD_LIKE_ACRONYMS and the
# upper-case TECHNICAL_TERMS in its src/lang/vi/resources.rs, Apache-2.0): left as
# they are, or spelling them would undo it.
SEA_WORDS = {
    "UNESCO", "NASA", "NATO", "ASEAN", "OPEC", "SARS", "FIFA", "UNIC", "RAM", "VRAM", "COVID",
    "IELTS", "STEM", "ROM", "ISO", "SEA", "UEFA", "EURO", "VAR", "ASIAD", "INTERPOL", "UNICEF",
    "TOEFL", "TOEIC", "PISA", "STEAM", "SAT", "GMAT", "EBITDA", "AIDS", "MERS", "ECMO", "LASIK",
    "FED", "NASDAQ", "UPCOM", "FOMO", "YOLO", "ASAP", "RADAR", "LASER", "LIDAR", "SONAR", "SCUBA",
    "GIF", "JPEG", "UNIX", "WIFI", "SIM", "LED", "VIP", "SPA", "GYM", "POS", "SWAT", "SEAL",
    "WASP", "COBOL", "BASIC", "OLED", "COVAX", "BRICS", "APEC", "VUCA", "PERMA", "DINK", "MENA",
    "EPIC", "OASIS", "BASE", "DART", "IDEA", "CHAOS", "SMART", "FANG", "BLEU", "REST", "ERROR",
    "SOTA", "BERT", "RAG", "ONNX", "ELO", "CAPTCHA", "ELISA", "SCADA", "MOSFET", "NEET", "REIT",
    "EBIT", "GINI", "NSAID", "PET", "SELECT", "FROM", "WHERE", "ORDER", "BY", "LIMIT", "OFFSET",
    "GROUP", "HAVING", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON", "AS", "AND", "OR", "NOT",
    "IN", "BETWEEN", "LIKE", "IS", "NULL", "TRUE", "FALSE", "CASE", "WHEN", "THEN", "ELSE", "END",
    "UNION", "INTERSECT", "EXCEPT", "DESC", "JSON", "NVIDIA", "KI",
}
# Not BOM: spelled "bi ô em" it was heard as BOM 5/5, as the word "bom" 0/5. JSON
# stays with sea_g2p: 4/5, against "giây sơn" 0/5 (Whisper large-v3, 2026-10-09).
# Upper-case English words in code and logs, read as the word: sea_g2p would spell
# them with Vietnamese letters (INFO i nờ ép ô).
CAPS_WORDS = {
    "INFO": "info", "DEBUG": "debug", "WARN": "warn", "FAIL": "fail", "HIGH": "high",
    "LOW": "low", "OFF": "off", "MAX": "max", "MIN": "min", "IDLE": "idle", "NOW": "now",
    "CONFIG": "config", "MAIN": "main", "LOG": "log", "DONE": "done", "READY": "ready",
    "START": "start", "STOP": "stop", "MODE": "mode", "TASK": "task", "CORE": "core",
    "COM": "com", "TIM": "tim", "LAN": "lan", "WAN": "wan", "CAN": "can", "LIN": "lin",
    "BOOT": "boot", "RESET": "reset", "PIN": "pin", "NAND": "nand", "CMOS": "cmos",
    "BIOS": "bios", "TODO": "to do", "README": "read me",
}
# A peripheral's index is a number (GPIO12 mười hai); other digits in a name are
# read one by one (ESP32 ba hai, LM358 ba năm tám).
INDEXED = re.compile(
    r"(GPIO|IO|ADC|DAC|TIM|CH|PWM|COM|GP|P[A-H]|UART|USART|SPI|I2S|CAN|LED|D|A)(\d{1,2})")
_ROMAN = re.compile(r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})")
_ROMAN_LEADS = {"chương", "phần", "kỷ", "bài", "mục", "quý", "khóa", "khoá", "tập", "hồi",
                "lần", "số", "đợt", "khu", "vòng"}
_PIN_LEADS = {"chân", "pin", "Pin"}

_ACRONYM = re.compile(r"(?<!\w)[A-Z][A-Z0-9]*[A-Z0-9](?!\w)")
# A discrete semiconductor's JEDEC number: 2N2222, 1N4007 (sea_g2p reads 2222 as a
# quantity).
_JEDEC = re.compile(r"(?<!\w)([1-4])N(\d{3,4})([A-Z]?)(?!\w)")
_RAIL_SIGN = re.compile(r"(?<!\w)V([+-])(?![\w+-])")
_VI_SYLLABLE = re.compile(
    r"(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdghklmnpqrstvx])?[aeiouy]+(?:ng|nh|ch|[cmnpt])?")
_NEXT_WORD = re.compile(r"\s+([^\W\d_]+)")
_SENTENCE_END = re.compile(r"[.!?\n]")


def _english(word: str) -> bool:
    """Looks like an English word, not a Vietnamese syllable written without marks."""
    return word.isascii() and len(word) > 1 and not _VI_SYLLABLE.fullmatch(word.lower())


def _spell(token: str, names: dict[str, str]) -> list[str]:
    words = []
    for run in re.findall(r"[A-Z]+|\d+", token):
        words.extend(digit_words(run) if run.isdigit() else [names[c] for c in run])
    return guard_fives(words)


def _caps_sentences(text: str) -> list[tuple[int, int]]:
    """Spans of Vietnamese sentences written all in capitals ("CON CHIP NÀY DÙNG
    UART"): sea_g2p lower-cases those, so their words without marks (CON, CHIP)
    are left to it."""
    spans, start = [], 0
    for end in [m.start() for m in _SENTENCE_END.finditer(text)] + [len(text)]:
        words = re.findall(r"[^\W\d_]+", text[start:end])
        if (len(words) > 1 and all(w.isupper() for w in words)
                and any(not w.isascii() for w in words)):
            spans.append((start, end))
        start = end + 1
    return spans


def _acronyms(text: str, keep: _Kept) -> str:
    text = _JEDEC.sub(lambda m: keep(" ".join(
        digit_words(m[1]) + ["nờ"] + digit_words(m[2]) + [VI_LETTER_NAMES[c] for c in m[3]])),
        text)
    text = _RAIL_SIGN.sub(lambda m: keep("vê cộng" if m[1] == "+" else "vê trừ"), text)
    caps = _caps_sentences(text)

    def acronym(m: re.Match) -> str:
        token, at = m[0], m.start()
        if token in SEA_WORDS:
            return token
        if token in CAPS_WORDS:
            return keep(CAPS_WORDS[token])
        word = re.fullmatch(r"([A-Z]+)(\d+)", token)
        if word and (word[1] in CAPS_WORDS or word[1] in SEA_WORDS):  # COM3, LED1
            return f"{keep(CAPS_WORDS.get(word[1], word[1].lower()))} {word[2]}"
        before = _LAST_WORD.search(m.string, max(0, at - 24), at)
        lead = before[1] if before and m.string[before.end():at].strip() == "" else ""
        if lead.lower() in _ROMAN_LEADS and _ROMAN.fullmatch(token):
            return token
        if any(s <= at < e for s, e in caps) and _VI_SYLLABLE.fullmatch(token.lower()):
            return token
        standalone = at == 0 or m.string[at - 1].isspace()
        # "chân D4" is a board pin, Arduino style; a lone D4 is a diode.
        designator = standalone and lead not in _PIN_LEADS and DESIGNATOR.fullmatch(token)
        if (re.match(r"[A-Z]+", token)[0] in ELECTRICAL or ELECTRICAL_PARTS.match(token)
                or designator
                or (token in _PACKAGES and _PACKAGE_NUMBER.match(m.string, m.end()))):
            names = VI_LETTER_NAMES
        else:
            names = EN_LETTERS
        index = designator if names is VI_LETTER_NAMES and designator else INDEXED.fullmatch(token)
        if index:
            return f"{keep(' '.join(names[c] for c in index[1]))} {index[2]}"
        words = _spell(token, names)
        # A last E or R right before an English word: sea_g2p reads a bare "i" there as
        # English /aɪ/ ("BLE server" bi eo í: 4/5, "i" 0/5), and "ISR handler" was
        # heard right with "à" 5/10, with "ar" 1/5.
        after = _NEXT_WORD.match(m.string, m.end())
        if names is EN_LETTERS and after and _english(after[1]) and words[-1] in ("i", "ar"):
            words[-1] = {"i": "í", "ar": "à"}[words[-1]]
        return keep(" ".join(words))

    return _ACRONYM.sub(acronym, text)


# ---------------------------------------------------------------- code tokens

# Digital acronyms that turn up in lower case inside identifiers (gpio_set_level,
# adc_cali_raw_to_voltage): spelled like their upper-case form.
CODE_ACRONYMS = {
    "UART", "USART", "SPI", "I2C", "I2S", "GPIO", "ADC", "DAC", "PWM", "LEDC", "MCPWM", "DMA",
    "RTC", "WDT", "NVS", "OTA", "MQTT", "HTTP", "HTTPS", "TCP", "UDP", "IP", "DNS", "MDNS", "DHCP",
    "SNTP", "NTP", "TLS", "SSL", "BLE", "GATT", "GAP", "USB", "CDC", "JTAG", "SDIO", "SDMMC",
    "SD", "LCD", "TFT", "ISR", "IRQ", "CPU", "NVIC", "PLL", "ULP", "VFS", "CRC", "AES", "SHA",
    "RSA", "URL", "API", "SDK", "TWAI", "RMT", "PCNT", "CAM", "IO", "ESP", "IDF", "MAC", "STA",
}
# Parts of identifiers read their own way: ESP_LOGI is "log ai", CONFIG_..._HZ "héc".
CODE_PARTS = {"uint": "iu int", "HZ": "héc", "ATTR": "attribute"}
_LOG_LEVEL = re.compile(r"LOG([IEWDV])")
# FreeRTOS names its functions with a type prefix: vTaskDelay, xQueueSend, pdMS_TO_TICKS.
_HUNGARIAN = r"(?:v|x|ux|pv|pd|prv|ul|us|uc)(?=[A-Z])"
_IDENTIFIER = re.compile(rf"(?<![\w.])(?:[A-Za-z]\w*_\w*|{_HUNGARIAN}\w+)(?![\w.])")
_IDENT_PARTS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_NO_VOWEL = re.compile(r"[^aeiouyAEIOUY]+")

_URL = re.compile(r"(?i)(?<![\w.])(https?|ftp|mqtts?|wss?)://([^\s\"'<>()]+)")
_PATH = re.compile(r"(?<![\w/.])(/[\w.\-]+(?:/[\w.\-]+)*)/?(?![\w/])")
_DIR = re.compile(r"(?<![\w/])([\w.\-]+)/(?=\s|$)")
# File extensions said as a word, or their own way; any other is spelled with English
# letter names (.c xi, .cpp xi pi pi).
_EXT_WORDS = {"bin", "elf", "json", "yaml", "log", "hex", "map", "ini", "conf", "bat",
              "defaults", "html"}
_EXT_SAY = {"py": "pai", "txt": "ti ích ti", "exe": "i ích i", "ino": "i nô", "cmake": "xi make"}
_FILE = re.compile(
    r"(?<![\w.])([\w\-]*)\.(c|h|cpp|hpp|cc|py|sh|txt|bin|elf|json|yaml|yml|md|csv|ino|ld|mk|"
    r"cmake|ini|cfg|conf|log|hex|uf2|map|so|dll|exe|bat|ps1|js|ts|html|css|xml|defaults)(?![\w.])")
_VERSION = re.compile(r"(?<![\w.])[vV](\d+(?:\.\d+)+)(?![\w.])")
_PORT = re.compile(r"(?i)\b(port|cổng)\s+(\d{4,5})(?![\w.,])")
_NOT_EQUAL = re.compile(r"\s*!=\s*")
_ASCII_WORD = re.compile(r"\b[A-Za-z]+\b")
# A whole number, not part of a name or of a decimal: 2048 in "(task, 2048, NULL)".
_INTEGER = re.compile(r"(?<!\w)(?<!\d[.,])\d+(?!\w|[.,]\d)")


def _spell_lower(part: str) -> str:
    return " ".join(EN_LETTERS[c.upper()] for c in part)


def _code_part(part: str, user, keep: _Kept) -> str:
    said = lexicon.sub(part, user, keep)
    if said != part:
        return said
    if part in CODE_PARTS:
        return keep(CODE_PARTS[part])
    level = _LOG_LEVEL.fullmatch(part)
    if level:
        return keep(f"log {EN_LETTERS[level[1]]}")
    if part.isdigit():
        return keep(" ".join(digit_words(part)))
    if len(part) == 1 and part.isupper():
        return keep(EN_LETTERS[part])  # the C of CMakeLists
    if part.upper() in CODE_ACRONYMS or part in ELECTRICAL:
        return part.upper()  # spelled by the acronym pass
    if part.islower() and (len(part) == 1 or _NO_VOWEL.fullmatch(part)):
        return keep(_spell_lower(part))  # t, x, nvs, pd
    if part.isupper() and _NO_VOWEL.fullmatch(part):
        return part  # MS: the acronym pass spells it
    return keep(part.lower())  # TO, TICKS, Handle: the English word


def _code_name(name: str, user, keep: _Kept) -> str:
    """An identifier, a file name or a path segment, one part at a time."""
    return " ".join(_code_part(p, user, keep) for p in _IDENT_PARTS.findall(name))


def _code(text: str, user, keep: _Kept) -> str:
    # A line of code or log with no Vietnamese in it puts sea_g2p in English mode,
    # where 2048 is "two thousand forty eight": its numbers are said digit by digit.
    # Vietnamese typed without marks ("thanh ghi 32 bit") is not such a line.
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.isascii() and sum(map(_english, _ASCII_WORD.findall(line))) >= 2:
            lines[i] = _INTEGER.sub(lambda m: keep(" ".join(digit_words(m[0]))), line)
    text = "\n".join(lines)

    def url(m: re.Match) -> str:
        rest = " gạch chéo ".join(p for p in m[2].rstrip("/.").split("/") if p)
        return f"{keep(_spell_lower(m[1].lower()))} {rest}"

    text = _URL.sub(url, text)
    text = _PATH.sub(lambda m: " ".join(
        f"{keep('gạch chéo')} {_code_name(p, user, keep)}" for p in m[1].split("/") if p), text)
    text = _DIR.sub(r"\1", text)

    def file(m: re.Match) -> str:
        ext = m[2].lower()
        say = _EXT_SAY.get(ext) or (ext if ext in _EXT_WORDS else _spell_lower(ext))
        name = f"{_code_name(m[1], user, keep)} " if m[1] else ""
        return f"{name}{keep(f'chấm {say}')}"

    text = _FILE.sub(file, text)
    text = _VERSION.sub(lambda m: f"{keep('vi')} {m[1]}", text)
    text = _PORT.sub(lambda m: f"{m[1]} {keep(' '.join(digit_words(m[2])))}", text)
    text = _NOT_EQUAL.sub(lambda m: f" {keep('khác')} ", text)
    return _IDENTIFIER.sub(lambda m: _code_name(m[0], user, keep), text)


# ---------------------------------------------------------------- entry point

def _unicode(text: str) -> str:
    # U+2212 MINUS SIGN: sea_g2p drops it, so −40°C would lose its sign.
    return text.replace("−", "-")


def _rewrite(text: str, user) -> str:
    keep = _Kept()
    text = _unicode(text)
    text = lexicon.sub(text, user, keep)
    text = _code(text, user, keep)
    text = _units(text, keep)
    text = _acronyms(text, keep)
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
