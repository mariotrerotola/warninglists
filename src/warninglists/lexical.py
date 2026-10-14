"""Lexical similarity helpers for domain labels and entity names.

Domain labels are compared with a bounded Levenshtein distance, token-bounded
combosquat detection, and an ASCII skeleton that folds punycode and visually
confusable characters.
"""

from __future__ import annotations

import re
import unicodedata

import idna

# Roots shorter than this produce too much noise as combosquat tokens
# (n26, ing, ...): only exact matches are considered for them.
COMBO_MIN_ROOT_LEN = 5

_CONFUSABLES = str.maketrans(
    {
        # Cyrillic letters identical to Latin ones
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "і": "i",
        "ѕ": "s",
        "ј": "j",
        "ԁ": "d",
        "ѡ": "w",
        # Greek letters identical to Latin ones
        "α": "a",
        "ο": "o",
        "ν": "v",
        "υ": "u",
        "κ": "k",
        "ρ": "p",
        "τ": "t",
        "ι": "i",
        # digit <-> letter swaps typical of typosquats
        "0": "o",
        "1": "l",
        "3": "e",
        "5": "s",
        "8": "b",
    }
)

# Legal-form tokens removed before comparing entity names. Only legal forms:
# words such as "capital", "group" or "trade" carry the identity of these
# entities and stay.
_LEGAL_FORMS = frozenset(
    """
    ltd limited llc llp lp inc incorporated corp corporation co company plc
    sa sas sarl srl srls spa sapa snc sas ag gmbh kg ug bv nv oy ab as asa aps
    pte pty sl slu oü ou kft zrt sro doo ood eood se pvt sdn bhd
    """.split()
)


def bounded_levenshtein(a: str, b: str, max_distance: int) -> int | None:
    """Levenshtein distance, or ``None`` if it exceeds ``max_distance``."""
    if abs(len(a) - len(b)) > max_distance:
        return None
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        row_min = i
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            row_min = min(row_min, cur[j])
        if row_min > max_distance:
            return None
        prev = cur
    d = prev[-1]
    return d if d <= max_distance else None


def is_token_bounded(text: str, root: str) -> bool:
    """True if ``root`` appears in ``text`` as a delimited token.

    ``login-etoro`` and ``etoro-wallet`` contain the token ``etoro``;
    ``myetorotrading`` contains the substring but not the token.
    """
    if len(root) < COMBO_MIN_ROOT_LEN:
        return False
    start = text.find(root)
    while start != -1:
        end = start + len(root)
        before_ok = start == 0 or not text[start - 1].isalnum()
        after_ok = end == len(text) or not text[end].isalnum()
        if before_ok and after_ok:
            return True
        start = text.find(root, start + 1)
    return False


def skeleton(label: str) -> str:
    """ASCII skeleton of a domain label: punycode decoded, confusables folded."""
    lower = label.lower()
    if "xn--" in lower:
        try:
            lower = idna.decode(lower)
        except idna.IDNAError:
            pass
    return lower.translate(_CONFUSABLES)


def default_max_distance(root: str) -> int:
    """Maximum edit distance accepted for a root of this length.

    Below 5 characters only exact matches; 1 edit up to 6; 2 beyond.
    """
    n = len(root)
    if n <= 4:
        return 0
    if n <= 6:
        return 1
    return 2


def name_tokens(name: str) -> list[str]:
    """Casefolded, accent-free tokens of an entity name, legal forms removed."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    # "s.r.l." / "s.p.a." -> "srl" / "spa" before splitting on punctuation
    text = re.sub(r"\b((?:[a-z]\.){2,})", lambda m: m.group(1).replace(".", ""), text)
    tokens = re.findall(r"[^\W_]+", text)
    kept = [t for t in tokens if t not in _LEGAL_FORMS]
    return kept or tokens


def compact_name(name: str) -> str:
    """Single string used for name equality and fuzzy comparison."""
    return "".join(name_tokens(name))
