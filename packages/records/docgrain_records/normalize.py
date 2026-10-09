"""Formatting-only value equality (WP111). Conflicts are asked, never guessed.

Two candidate values are the *same value* when they differ only in spelling: Unicode width and
dashes, whitespace, letter case (Turkish İ/ı included), punctuation that does not sit between two
digits, clock spelling ("10.00" / "10:00"), a slash or dash between two clock times
("10:00 / 18:00" / "10:00-18:00") and a unit spelling ("m 2" / "m²"). Different numbers,
different times and different dates never compare equal. Long free text may additionally be
*near-identical* (an OCR or typing slip such as "konsantre" / "konsanire"); that is a separate,
stricter test and the caller keeps the other spelling as a recorded variant.
"""

import json
import re
import unicodedata
from difflib import SequenceMatcher

from docgrain_eval.scoring import normalized_value

from .verify import _value_spans, normalize_quote

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹘﹣－"), "-")
_CLOCK = r"\d{1,2}[:.]\d{2}"
# Prose punctuation only. Symbols that carry meaning (%, +, #, &, @, currencies) are kept.
_PUNCTUATION = set(".,;:!?'\"()[]{}«»‹›“”‘’„‚/\\-…·¿¡")
LONG_TEXT = 40
NEAR_RATIO = 0.95


def _prepare(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_DASHES)
    # A lost superscript: "25-27 m 2" is "25–27 m²".
    text = re.sub(r"(?<=\d)\s*m\s+([23])(?!\w)", r" m\1", text)
    # Opening/closing hours written with a slash are the same range as with a dash.
    return re.sub(rf"(?<![\w.:])({_CLOCK})\s*/\s*({_CLOCK})(?![\w:]|\.\d)", r"\1-\2", text)


def _strip(text: str) -> str:
    """Drop prose punctuation, keeping it only between two digits (25-27, 10:00, 1/2, 7.5)."""
    chars = []
    for index, char in enumerate(text):
        between_digits = (0 < index < len(text) - 1 and text[index - 1].isdigit()
                          and text[index + 1].isdigit())
        chars.append(" " if char in _PUNCTUATION and not between_digits else char)
    return " ".join("".join(chars).split())


def _canonical(key):
    if isinstance(key, list) and len(key) == 2 and key[0] == "text":
        return ["text", _strip(key[1])]
    if isinstance(key, list) and len(key) == 2 and key[0] == "list":
        return ["list", sorted({_strip(item) for item in key[1]} - {""})]
    if isinstance(key, list) and len(key) == 2 and key[0] == "object":
        return ["object", {name: _canonical(item) for name, item in key[1].items()}]
    return key


def _prepared(value):
    if isinstance(value, str):
        return _prepare(value)
    if isinstance(value, list):
        return [_prepared(item) for item in value]
    return value


def format_key(value, field: str = "") -> str:
    """Comparison key only; the stored value and its evidence keep the source spelling."""
    key = _canonical(normalized_value(_prepared(value), field))
    return json.dumps(key, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def same_value(left, right, field: str = "") -> bool:
    return format_key(left, field) == format_key(right, field)


def fold(text: str) -> str:
    """Folded plain text used for near-identity and quote mentions."""
    key = normalized_value(_prepare(text))
    return _strip(key[1]) if key[0] == "text" else json.dumps(key, ensure_ascii=False)


def near_identical(left, right) -> bool:
    """Long free text with a few one-to-one word slips; numbers and short words must match.

    Required: both at least LONG_TEXT folded characters, the same digit sequence, the same
    number of words, character similarity >= NEAR_RATIO, at most one changed word per ten,
    and each changed word pair a single-letter slip (see ``_slip``). "edilir" / "edilmez",
    "ücretsiz" / "ücretli", "free" / "fee" or "included" / "excluded" therefore stay different
    values (a question).
    """
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    a, b = fold(left), fold(right)
    if a == b or min(len(a), len(b)) < LONG_TEXT:
        return False
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    if SequenceMatcher(None, a, b, autojunk=False).ratio() < NEAR_RATIO:
        return False
    words_a, words_b = a.split(), b.split()
    if len(words_a) != len(words_b):
        return False
    changed = [(x, y) for x, y in zip(words_a, words_b, strict=True) if x != y]
    if not changed or len(changed) > max(1, len(words_a) // 10):
        return False
    return all(_slip(x, y) for x, y in changed)


def _slip(x: str, y: str) -> bool:
    """Words of five or more letters, no digits, one substituted, added or dropped letter.

    "konsantre" / "konsanire" qualifies. Negation and other suffixes or prefixes ("-siz"/"-li",
    "-mez", "un-", "in-"/"ex-") change at least two letters and never qualify.
    """
    if min(len(x), len(y)) < 5 or any(c.isdigit() for c in x + y):
        return False
    if len(x) == len(y):
        return sum(a != b for a, b in zip(x, y, strict=True)) == 1
    if abs(len(x) - len(y)) != 1:
        return False
    short, long = sorted((x, y), key=len)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def mentions(quote: str, value, field: str = "") -> bool:
    """The quotation states this value literally or in a formatting-equal spelling."""
    text = normalize_quote(quote)
    if not text:
        return False
    if isinstance(value, bool):
        return True  # verify.py accepts a written field label for a boolean.
    if isinstance(value, list):
        return bool(value) and all(mentions(quote, item, field) for item in value)
    if _value_spans(text, value):
        return True
    if isinstance(value, str):
        needle = fold(value)
        return bool(needle) and f" {needle} " in f" {fold(text)} "
    return False
