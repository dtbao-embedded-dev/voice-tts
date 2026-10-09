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
