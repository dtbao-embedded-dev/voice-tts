# How the special pronunciation reads technical terms

The `special` pronunciation (`"pronunciation": "special"`, `--pronunciation special`,
*Phát âm → Đặc biệt*) rewrites the text before the engine sees it. `normal` sends the
text as typed.

## Why there is a rewrite at all

VieNeu-TTS does not read text itself: it hands it to its front end,
[sea-g2p](https://github.com/pnnbao97/sea-g2p), which normalizes it and turns it into
phonemes, and the model was trained on those phonemes. sea-g2p reads Vietnamese well,
but for this repo's subject matter it falls short, and it has no way to add words:

- it has tables of English acronyms and acronym-like words compiled into the binary,
  and none of them covers embedded or electronics terms;
- an upper-case token it does not know is spelled with Vietnamese letter names, so
  UART is *u a rờ tê* and RX *rờ ích* - "rờ" sounds like "dờ" in a northern voice;
- several units come out wrong: `5mW` as megawatts, `µA` with the micro sign dropped,
  `3,3V` as *vê*;
- `G2P(db_path)` ignores its argument, so there is no user dictionary.

So `respell.py` runs first and hands sea-g2p only words it already reads right.
`lexicon.py` keeps the whole-word table and the user's own words.

## Order

Outside `<en>...</en>`, in this order:

1. U+2212 MINUS SIGN becomes `-` (sea-g2p drops it: `−40°C` would lose its sign).
2. The lexicon: the user's words and the built-in ones, longest first. What it says
   wins over every rule below.
3. Numbers and units.

Each rewrite is parked behind a placeholder until the end, so a later rule never
rewrites what an earlier one wrote.

## Numbers and units

After a number, with or without a space. The number itself is left to sea-g2p, which
reads it right (`3,3` *ba phẩy ba*, `3.3` *ba chấm ba*, `-5` *âm năm*).

| Written | Read | sea-g2p alone |
| --- | --- | --- |
| `V` `mV` `kV` `µV` | vôn, mi li vôn, ki lô vôn, mi cờ rô vôn | *vê*, English letters |
| `A` `mA` `µA` `nA` | am pe, mi li am pe, mi cờ rô am pe, na nô am pe | *a*, *ma* (a ghost), µ dropped |
| `mW` `mWh` | mi li oát (giờ) | *mê ga oát*: m and M are one key to it |
| `kΩ` `MΩ` `mΩ` | ki lô ôm, mê ga ôm, mi li ôm | *ca ôm*, *mờ ôm* |
| `F` `pF` `nF` `µF` `mF` | pha ra, pi cô / na nô / mi cờ rô / mi li pha ra | *ép*, English letters, µ dropped |
| `µH` `mH` `nH` | mi cờ rô / mi li / na nô hen ri | English letters |
| `µs` `ns` `ps` | mi cờ rô / na nô / pi cô giây | *ét*, English letters |
| `GHz` | di ga héc | *gi ga héc*, and "gi" loses its vowel |
| `dBm` | đê bê em | half Vietnamese, half English |
| `VAC` `VDC` | vôn a xê, vôn đê xê | one syllable, English letters |

The micro prefix is accepted as `µ` (U+00B5 MICRO SIGN), `μ` (U+03BC GREEK MU) or `u`.
"pha ra" and "mi cờ rô" because sea-g2p reads "fa ra" and "micro" as English.

Also:

- **Ranges** `1-2m`, `0–3.3V`, `0~5V`, `0 - 3.3V`, `-40~85°C`: *a đến b* and the unit.
  sea-g2p takes `1-2` for a day and a month and glues the unit on (*một đến haim*), and
  reads `~` as *khoảng*. In a range the units it reads right after one number are
  rewritten too (m, cm, mm, km, s, ms, Hz, kHz, MHz, W, kW, Ω, g, kg, dB, °C, %).
- **Two quantities** `5V2A`, `12V5A` are split; `3V3` (a 3.3 V rail) is not.
  `3.3V/500mA`, `100uF/25V`: the slash becomes a comma. `Vcc/2` and `km/h` keep theirs.
- **Fractions of a watt** `1/4W`: *một phần tư oát*.
- **Resistor codes** `100R`, `0R`: *ôm*; `2R2`: *2,2 ôm*. After *trở* / *điện trở*,
  `1M` is *mê ga ôm*.
- **Capacitors** after *tụ* (also *tụ gốm*, *tụ hóa*...): a three-digit code ending in
  1-6 is read digit by digit (`tụ 104` *một không bốn*; `tụ 470` stays a number),
  and `22p`, `100n`, `1u` are *pi cô*, *na nô*, *mi cờ rô*. A bare `5p` stays
  *năm phút*.
- **Hex** `0x3C`: *không ích ba xi* (sea-g2p reads the x as *nhân*, times).
- **Not a quantity**: after *lớp*, *phòng*, *câu*, *tổ*, *khối*, *khu*, *dãy*, *hạng*,
  *mục*, *bàn* (`lớp 5A`), or glued to letters (`0x5A`, `2N2222A`).

Digits read one by one (`tụ 104`, hex, part numbers) get a comma after a pair of fives
before another number word (`năm năm, năm`): sea-g2p drops the first "năm" of
"năm năm" there, a rule meant for a date's doubled "năm" (`RE_REDUNDANT_NAM`), and
VieNeu normalizes the text twice, so writing them with hyphens does not save it.

## terms.tsv

`terms.tsv` is the list of terms the rewrite must get right, and `python test_cli.py`
checks it (`check_terms`). One row per term, tab-separated:

| Column | Meaning |
| --- | --- |
| `input` | the term as people type it, alone or in a short phrase |
| `expected` | what `respell.special()` must send the engine |
| `domain` | the rule family that handles it: `ok` (nothing to do), `units`, `acronym`, `code`, `lexicon` |
| `lang` | `vi`, `en`, `mixed`, or `en-vi` (spelled with Vietnamese letter names) |
| `state` | `on` (checked), `pending` (not handled yet), `listen` (two spellings, settled by ear), `known-limit` |

Every `on` row must also survive sea-g2p, in a sentence, model-free:

- no spoken punctuation ("gạch dưới", "gạch nối");
- no syllable without a vowel (sea-g2p reads "gi" as a bare /z/, "qui" as /kwj/);
- no unit left as English letters ("pf", "mv", "nf"...).

Lines starting with `# ` are comments.

### A term reads wrong

1. Add a row with the term and the spelling it should have, state `on`.
2. Run `python test_cli.py`: the new row fails.
3. Fix it - a rule in `respell.py` if the term stands for a family, a built-in entry in
   `lexicon.py` if it is one word - and run the test again until it passes.

For a quick fix on one machine, without a release, add the word to your own lexicon
(`voice-tts lexicon add WORD SAY`, *Từ điển* in the window); it wins over every rule.
