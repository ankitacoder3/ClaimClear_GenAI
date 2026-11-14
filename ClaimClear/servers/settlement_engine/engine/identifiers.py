"""Policy numbers as printed versus as filed.

A bill or letter may print a policy number with characters that look like Latin
letters but are not: Cyrillic ``А`` and ``Ѕ``, Greek ``Ο``, full-width digits, an
en dash for the hyphen. Some are honest typesetting; some are parser attacks
(ADV-05). ``canonical_policy_no`` gives the form to compare and look up with;
the printed form is kept, and the engine warns when the two differ.
"""

from __future__ import annotations

import re
import unicodedata

# Cyrillic and Greek letters that look like Latin capitals (and a few lower-case ones).
_LOOKALIKES = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "І": "I", "Ј": "J", "К": "K", "М": "M", "О": "O",
    "Р": "P", "Ѕ": "S", "Т": "T", "Х": "X", "У": "Y", "а": "a", "с": "c", "е": "e", "о": "o", "р": "p",
    "х": "x", "у": "y", "і": "i", "ј": "j", "ѕ": "s",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "ο": "o",
})
_DASHES = re.compile(r"[‐-―−﹘﹣－]")


def canonical_policy_no(printed: str) -> str:
    """The policy number to compare and look up: look-alikes mapped to Latin, one hyphen, no spaces, upper case."""
    text = unicodedata.normalize("NFKC", printed or "").translate(_LOOKALIKES)
    text = _DASHES.sub("-", text)
    return re.sub(r"\s+", "", text).upper()


def has_lookalikes(printed: str) -> bool:
    """True when the printed number only matches after mapping look-alike characters."""
    return canonical_policy_no(printed) != re.sub(r"\s+", "", printed or "").upper()


def same_policy(a: str, b: str) -> bool:
    return canonical_policy_no(a) == canonical_policy_no(b)
