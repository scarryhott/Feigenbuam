"""
Skill: extract_symbols_excluding_stops
Extracts unique symbols from a text string, excluding specific stop symbols and filtering out certain single-character symbols.
"""

import re
from typing import List

RE_SYMBOLS = re.compile(r"[A-Za-zΑ-Ωα-ω][A-Za-z0-9_'.]*")

STOP_SYMBOLS = {"If", "Then", "Define", "as", "is", "and", "or", "the", "a", "an"}


def extract_symbols_excluding_stops(text: str) -> List[str]:
    syms = []
    for m in RE_SYMBOLS.finditer(text):
        s = m.group(0)
        if s in STOP_SYMBOLS:
            continue
        if len(s) == 1 and s.lower() in {"a", "i"}:
            continue
        syms.append(s)
    seen = set()
    out = []
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:64]