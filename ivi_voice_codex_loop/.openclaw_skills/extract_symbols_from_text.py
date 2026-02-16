"""
Skill: extract_symbols_from_text
This function extracts symbols from a given text, filtering out stop symbols and short, irrelevant ones.
"""

import re
from typing import List

RE_SYMBOLS = re.compile(r"[A-Za-zΑ-Ωα-ω][A-Za-z0-9_'.]*")
STOP_SYMBOLS = {"If", "Then", "Define", "as", "is", "and", "or", "the", "a", "an"}

def extract_symbols(text: str) -> List[str]:
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