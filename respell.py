"""Rewrite technical text, in the ``special`` pronunciation, into words the engine reads
the way Vietnamese engineers say them.

VieNeu hands the text to its front end, sea_g2p, which has no table for embedded or
electronics terms and no way to add one: an upper-case token it does not know is
spelled with Vietnamese letter names (UART *u a rờ tê*), ``5mW`` comes out as
megawatts and ``µ`` is dropped. This module runs before it and leaves only words
sea_g2p already reads right. ``lexicon.py`` holds the whole-word table and the
user's words; ``terms.tsv`` pins what each rule must produce.

Standard library only, like ``lexicon.py``.
"""

from __future__ import annotations

import lexicon


def special(text: str, user=()) -> str:
    """``text`` as the ``special`` pronunciation sends it to the engine.

    ``user`` is the user's lexicon, a list of ``{"word", "say", "matchCase"}``.
    """
    return lexicon.apply(text, user)
