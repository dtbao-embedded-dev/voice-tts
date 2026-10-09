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
3. Code: identifiers, file names, versions, URLs and paths, ports.
4. Numbers and units.
5. Upper-case acronyms.

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

## Acronyms

An upper-case token of two characters or more (`UART`, `I2C`, `STM32F103`, `CH340C`)
is spelled letter by letter, with one of two sets of letter names, chosen by what the
term is about:

| Letter | A | B | C | D | E | F | G | H | I | J | K | L | M |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| English names | ây | bi | xi | đi | i | ép | di | hát | ai | giây | cây | eo | em |
| Vietnamese names | a | bê | xê | đê | e | ép | gờ | hát | i | giây | ca | lờ | mờ |

| Letter | N | O | P | Q | R | S | T | U | V | W | X | Y | Z |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| English names | en | ô | pi | kiu | ar | ét | ti | iu | vi | đắp bờ liu | ích | oai | dét |
| Vietnamese names | nờ | ô | phê | cu | rờ | ét | tê | u | vê | vê kép | ích | y | dét |

- **English letter names** (the default): MCU, peripherals, buses, protocols,
  software - `UART` *iu ây ar ti*, `RX` *ar ích*, `GPIO` *di pi ai ô*, `MQTT` *em kiu ti
  ti*, `HTTP` *hát ti ti pi*. Like `AP` *ây pi* and `ESP` *i ét pi* in the lexicon.
- **Vietnamese letter names**, the way electronics people spell them:
  - power and ground: GND, AGND, DGND, PGND, VCC, VDD, VSS, VEE, AC, DC, and `V+` / `V-`
    (*vê cộng*, *vê trừ*);
  - analog, power and passive terms: IC, PCB, SMD, THT, LDO, SMPS, ESR, ESL, ESD, TVS,
    EMI, EMC, BJT, NPN, PNP, IGBT, JFET, FET, NTC, PTC, LDR, UPS, VOM;
  - packages: QFN, BGA, TQFP, LQFP, SOIC, SOP, SSOP, TSSOP, SMA, SMB, SMC, SMBJ, and
    TO / DO / SOD before a number (`TO-220`);
  - analog, power and discrete part numbers: LM, NE, AMS, TP, MP, XL, IRF, IRLZ, BC,
    BD, TL, LT, AO, SS, MC, LD, ULN, TIP, HT, CR followed by digits (`LM358` *lờ mờ ba
    năm tám*), and JEDEC numbers (`2N2222` *hai nờ hai hai hai hai*, `1N4007`);
  - reference designators standing alone: R, C, L, U, Q, D, J, F, K, T, SW, TP, BT,
    VR, RV, FB followed by up to three digits (`R1` *rờ một*, `C12` *xê mười hai*).
    After *chân* or *pin* a letter and a number is a board pin instead, English style
    (`chân D4` *đi bốn*).

Vietnamese Q is *cu*: sea-g2p's *qui* comes out with no vowel. English R is *ar*,
which sea-g2p reads as the English letter /ɑːɹ/: *rờ* sounds like *dờ* in a northern
voice (UART was heard as "UAZT", RX as "giờ x") and a bare *a* is heard as A.

Digits inside a name are read one by one (`ESP32` *ba hai*, `RP2040` *hai không bốn
không*), except a peripheral's index, which is a number: GPIO, IO, ADC, DAC, TIM, CH,
PWM, COM, GP, PA-PH, UART, USART, SPI, I2S, CAN, LED, D, A followed by one or two
digits (`GPIO12` *mười hai*, `IO43` *bốn mươi ba*).

Left as they are, or read as words:

- acronyms sea-g2p already reads as words (`LED`, `RAM`, `ROM`, `WIFI`, `MOSFET`,
  `NULL`, `TRUE`, `ON`, `REST`, `JSON`...; its `WORD_LIKE_ACRONYMS`);
- upper-case English words of code and logs, lower-cased so they are read as words:
  INFO, DEBUG, WARN, FAIL, HIGH, LOW, OFF, MAX, MIN, IDLE, NOW, CONFIG, MAIN, LOG,
  DONE, READY, START, STOP, MODE, TASK, CORE, COM, TIM, LAN, WAN, CAN, LIN, BOOT,
  RESET, PIN, NAND, CMOS, BIOS, TODO (*to do*), README (*read me*), also with a number
  (`COM3` *com ba*, `LED1`);
- Roman numerals after *chương*, *phần*, *bài*, *mục*, *quý*, *tập*... (`Chương II`);
- in a Vietnamese sentence written all in capitals (`CON CHIP NÀY DÙNG UART`), the
  words that could be Vietnamese syllables (`CON`, `CHIP`): sea-g2p lower-cases that
  sentence itself.

A last E or R right before an English word is written *í* / *à* (`BLE server` *bi eo
í*, `ISR handler` *ai ét à*): next to an English word sea-g2p reads a bare *i* as
English /aɪ/, and *à* was heard right more often than *ar* there (5/10 against 1/5).

## Code

- **Identifiers** with an underscore (`ESP_LOGI`, `nvs_flash_init`, `uint8_t`,
  `CONFIG_FREERTOS_HZ`) or a FreeRTOS type prefix (`vTaskDelay`, `xQueueSend`,
  `pdMS_TO_TICKS`) are cut at the underscores and the case changes, and each part is
  read on its own - never *gạch dưới*:
  - a lexicon word: `ESP` *i ét pi*, `OK` *ô kê*, `IRAM` *ai ram*;
  - a digital acronym, in any case: `gpio`, `adc`, `nvs`... spelled as above;
  - a single letter or a run without a vowel: English letter names (`t` *ti*, `x`
    *ích*, `pd` *pi đi*);
  - digits one by one (`uint32_t` *iu int ba hai ti*);
  - `ESP_LOGI` / `LOGE` / `LOGW`... is *log ai* / *log i*..., `HZ` *héc*, `ATTR`
    *attribute*, `uint` *iu int*;
  - anything else is the English word, in lower case (`TO`, `TICKS`, `Handle`).

  Other camelCase words are left whole (`LoRa`, `GitHub` and `eFuse` read right).
- **File names** `main.c`, `app.cpp`, `CMakeLists.txt`: *main chấm xi*, the name cut
  like an identifier; the extension is a word (`bin`, `json`, `yaml`, `log`...) or
  spelled (`c` *xi*, `cpp` *xi pi pi*, `py` *pai*, `txt` *ti ích ti*). sea-g2p reads
  the dot as the end of a sentence.
- **Versions** `v5.3`, `v1.0.2`: *vi năm chấm ba* (sea-g2p: *vê năm. ba*).
- **URLs and paths**: the scheme spelled (`https` *hát ti ti pi ét*), `/` *gạch chéo*
  (sea-g2p: *trên*, divided by), a trailing `/` dropped.
- **Ports** of four or five digits after *port* / *cổng*: digit by digit (`port 8080`
  *tám không tám không*). Baud rates stay numbers.
- `!=` is *khác*.
- **A line of code or log with no Vietnamese in it** and at least two English-looking
  words (`stack size 2048`, `xTaskCreate(task, "name", 2048, NULL, 5, NULL)`): its
  whole numbers are read digit by digit in Vietnamese. On such a line sea-g2p
  switches to English and reads 2048 as *two thousand forty eight*. Vietnamese typed
  without marks (`thanh ghi 32 bit`) does not count as English.

## Built-in words

`ENTRIES` in `lexicon.py`, one per spelling in any case (the table is keyed by the
casefolded word, so `VOUT` and `Vout` are one entry):

| Kind | Words |
| --- | --- |
| Said as words | OK *ô kê*, FIFO *phai phô*, LIFO, ASCII, YAML, SPIFFS, FATFS, TAG, SHA, SHA256, JTAG *giây tag*, ARM, RISC-V *risk five*, PSRAM / SRAM / DRAM / IRAM *... ram*, EEPROM *i i pi rom* |
| Names | ESP-NOW *i ét pi nao*, USB-C, type-C, LEDC *led xi*, SoC, MicroSD, DevKitC, FreeRTOS *free a ti ô ét*, PlatformIO, OpenOCD, mDNS, softAP, esp32s3 / c3 / c6 / h2, nRF52840, ATmega328P, Raspberry Pi *raspberry pai*, tri-state, 8N1 |
| Code and tools | memcpy *mem copy*, printf *print ép*, CMake *xi make*, idf.py, base64 *base sáu tư*, ota, tty, Ctrl+C *control xi*, Ctrl+], HTTP/1.1, 802.11, b/g/n, panic'ed |
| Power and transistors | VIN *vê in*, VOUT *vê ao*, VREF *vê rép*, VBUS *vê bớt*, VBAT *vê bát*, hFE, ic / Ic *i xê*, Ib |
| Loanwords | board *bo*, module *mô đun*, mass *mát*, Gerber *gơ bơ*, DIP *đíp*, SOT *sót* (SOT23, SOT-23, SOT-23-5, SOT-23-6, SOT-223, SOT-89 digit by digit), LiPo *li pô*, 18650 *mười tám sáu năm mươi* |
| Vietnamese abbreviations | VĐK, VXL, HĐH, CSDL, CTDL, ĐTDĐ, KTĐT, ĐKTĐ, said in full |

KTS, ĐK, CB and LT are left out: each stands for more than one thing. Add the one you
mean to your own lexicon.

## Limits

- *pin* meaning a battery is read like the English *pin* (/pɪn/): sea-g2p's dictionary
  has the word as English only, and no spelling reaches the Vietnamese /pin/.

## Measured

Where two spellings both came out of sea-g2p clean, the choice was made by ear, the
way `AP` *ây pi* was: each candidate read 5 times in "ở bước này, ta dùng ... cho
mạch." by the local engine (v3 Turbo, fp32, voice Hải Đăng), transcribed by
faster-whisper large-v3 (`vi`, beam 5, no prompt), counted right when the transcript
has the term. 2026-10-09, on a desktop CPU, never on the LAN server.

| Term | Kept | Others |
| --- | --- | --- |
| UART | *iu ây ar ti* 4/5 | *u a rờ tê* (sea-g2p) 1/5, `<en>u a r t</en>` 3/5 |
| GPIO | *di pi ai ô* 5/5 | `<en>g p i o</en>` 4/5, *gờ phê i ô* (sea-g2p) 1/5 |
| MQTT | *em kiu ti ti* 5/5 | *mờ qui tê tê* 5/5 |
| I2C | *ai hai xi* 5/5 | *ai tu xi* 5/5, *i hai xê* (sea-g2p) 3/5 |
| ISR handler | *ai ét à handler* 4/5 | *ai ét a handler* 0/5 |
| BLE server | *bi eo í server* 4/5 | *bi eo i server* 0/5 |
| HAL, DHT22, HTTP | H *hát*: 5/5, 4/5, 4/5 | H *ếch* 0/5, 0/5, 3/5 (heard as X); *ết* 0/5, 0/5, 5/5 (heard as S) |
| MAC | *em ây xi* 5/5 | *mác*, `<en>mac</en>` 0/5 (heard "Mark") |
| BOM | *bi ô em* 5/5 | *bom* 0/5 |
| ELF | *i eo ép* 3/5 | *elf* 1/5 |
| JSON | as typed, sea-g2p's own 4/5 | *giây sơn* 0/5 |
| printf | *print ép* 4/5 | as typed 0/5 |
| 2R2 | *2,2 ôm* 5/5 | *hai rờ hai* 0/5 |
| 18650 | *mười tám sáu năm mươi* 5/5 | *một tám sáu năm không* 4/5 |
| base64 | *base sáu tư* 3/5 | *base sáu mươi bốn* 3/5 |
| 10µF | *mi cờ rô* 4/5 | *micro* 4/5 |
| EN | *i en* 2/5 | *en* 0/5 |

**The letter R** took two more rounds. English *a* is heard as A, Vietnamese *rờ* as
*dờ*; bare *ar*, read by sea-g2p as the English letter /ɑːɹ/, won or tied every term:

| Term | R *ar* | R *a* | Other spellings |
| --- | --- | --- | --- |
| RX | 4/10 | 0/10 | *rờ ích* 0/5 ("giờ x"), *a rờ ích* 0/10, `<en>r x</en>` 0/5 |
| RTC | 5/5 | 3/10 | *rờ tê xê* 1/5 |
| RS485 | 2/5 | 0/10 | *a rờ ét...* 2/5, *rờ ét...* 0/5 |
| RTS | 1/5 | 0/10 | *a rờ ti ét* 0/5 |
| RTOS | 4/5 | 0/10 | *a rờ ti ô ét* 3/5, *rờ tốt* 0/5 |
| FreeRTOS | 5/5 | 5/10 | *free a rờ ti ô ét* 0/5 |
| UART | 5/5 | 9/10 | |
| IRQ | 3/5 | 2/5 | |
| RP2040 | 4/5 | 0/5 | |
| RGB | 5/5 | 5/5 | |
| AVR | 3/5 | 0/5 | |
| ISR handler | 1/5 | *à* 5/10 | (a last R before an English word) |

RX and RTS stay weak whatever the spelling: a short acronym whose letters are all
sounds Vietnamese lacks.

**End to end**, the narration of OpenMontage's UART video (7 sections, 36 upper-case
terms: UART, TX, RX, GND, ESP32 S3...), read whole by the local engine through
`respell.special()` and transcribed the same way: 31/36 and 30/36 terms heard, against
18-23/36 for the four takes the 0.8.2 server read. What was still missed, over both
takes: TX 3 of 18, GND as *gờ nờ đê* 3 of 6 (heard "GN để"), RX 2 of 14, UART 2 of 16,
ESP32 S3 1 of 8.
