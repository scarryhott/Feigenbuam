from __future__ import annotations

import re
from typing import List

from .ir import LogicClaim, Provenance, make_claim

RE_IF_THEN = re.compile(r"^\s*(if|IF)\s+(.+?)\s+(then|THEN)\s+(.+?)\s*$")
RE_DEFINE = re.compile(r"^\s*(define|Define)\s+(.+?)(?:\s+as|\s*:=|\s*:)\s*(.+?)\s*$")
RE_IS = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_\-]*)\s+is\s+(.+?)\s*$")
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


def derive_claims_from_text(text: str, prov: Provenance) -> List[LogicClaim]:
    t = text.strip()
    if not t:
        return []

    claims: List[LogicClaim] = []

    if m := RE_DEFINE.match(t):
        name = m.group(2).strip()
        rhs = m.group(3).strip()
        ctext = f"def {name} := {rhs}"
        claims.append(
            make_claim(
                text=ctext,
                kind="definition",
                symbols=extract_symbols(ctext),
                confidence=0.85,
                status="accepted",
                tags=["phase1", "definition"],
                prov=prov,
            )
        )
        return claims

    if m := RE_IF_THEN.match(t):
        cond = m.group(2).strip()
        concl = m.group(4).strip()
        ctext = f"{cond} -> {concl}"
        claims.append(
            make_claim(
                text=ctext,
                kind="rule",
                symbols=extract_symbols(ctext),
                confidence=0.75,
                status="accepted",
                tags=["phase1", "rule"],
                prov=prov,
            )
        )
        return claims

    if m := RE_IS.match(t):
        lhs = m.group(1).strip()
        rhs = m.group(2).strip()
        ctext = f"{lhs} = {rhs}"
        claims.append(
            make_claim(
                text=ctext,
                kind="fact",
                symbols=extract_symbols(ctext),
                confidence=0.55,
                status="accepted",
                tags=["phase1", "fact"],
                prov=prov,
            )
        )
        return claims

    claims.append(
        make_claim(
            text=t,
            kind="hypothesis",
            symbols=extract_symbols(t),
            confidence=0.35,
            status="quarantined",
            tags=["phase1", "hypothesis", "needs_review"],
            prov=prov,
        )
    )
    return claims
