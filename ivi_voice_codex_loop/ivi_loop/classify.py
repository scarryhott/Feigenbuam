from __future__ import annotations

import re

QUESTION_PREFIXES = (
    "what",
    "why",
    "how",
    "when",
    "where",
    "who",
    "which",
    "can",
    "could",
    "should",
    "would",
    "is",
    "are",
    "do",
    "does",
    "did",
    "will",
    "may",
)


def is_question(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if t.endswith("?"):
        return True
    low = t.lower()
    first = re.split(r"\s+", low, maxsplit=1)[0]
    if first in QUESTION_PREFIXES and len(re.split(r"\s+", t)) >= 2:
        return True
    return False
