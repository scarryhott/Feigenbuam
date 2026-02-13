from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

Role = Literal["human", "assistant", "system"]
ItemType = Literal["utterance", "logic_claim", "analysis_note"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


@dataclass
class Provenance:
    source_type: Literal["voice", "text", "chatlog", "import"]
    source_id: str  # e.g. file path, run id, etc.
    span: Optional[str] = None  # optional line/offset span
    depends_on: Optional[List[str]] = None  # ids of other IR items

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Utterance:
    id: str
    created_at: str
    role: Role
    text: str
    is_question: bool
    provenance: Provenance

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d


@dataclass
class Equation:
    id: str
    created_at: str
    claim_id: str
    statement_id: str
    lean_name: str
    expression: str
    tags: List[str]
    provenance: Provenance

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d


@dataclass
class DerivationStep:
    id: str
    created_at: str
    statement_id: str
    claim_id: str
    equation_id: str
    relation: Literal["grounds", "realizes", "interprets"]
    notes: str
    provenance: Provenance

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d


@dataclass
class Triangle:
    id: str
    created_at: str
    statement_id: str
    derivation_id: str
    equation_id: str
    provenance: Provenance

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d


@dataclass
class LogicClaim:
    id: str
    created_at: str
    text: str                 # normalized logic statement
    kind: Literal["definition", "rule", "fact", "hypothesis"]
    symbols: List[str]
    confidence: float
    status: Literal["accepted", "quarantined", "deprecated"]
    tags: List[str]
    provenance: Provenance

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d


@dataclass
class AnalysisNote:
    id: str
    created_at: str
    title: str
    body: str
    provenance: Provenance

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d


def make_utterance(role: Role, text: str, is_question: bool, prov: Provenance) -> Utterance:
    base = {"role": role, "text": text, "is_question": is_question, "prov": prov.to_dict(), "t": now_iso()}
    return Utterance(
        id=f"U-{stable_hash(base)}",
        created_at=base["t"],
        role=role,
        text=text,
        is_question=is_question,
        provenance=prov,
    )


def make_claim(
    text: str,
    kind: Literal["definition", "rule", "fact", "hypothesis"],
    symbols: List[str],
    confidence: float,
    status: Literal["accepted", "quarantined", "deprecated"],
    tags: List[str],
    prov: Provenance,
) -> LogicClaim:
    base = {
        "text": text,
        "kind": kind,
        "symbols": symbols,
        "confidence": round(float(confidence), 6),
        "status": status,
        "tags": tags,
        "prov": prov.to_dict(),
        "t": now_iso(),
    }
    return LogicClaim(
        id=f"C-{stable_hash(base)}",
        created_at=base["t"],
        text=text,
        kind=kind,
        symbols=symbols,
        confidence=float(base["confidence"]),
        status=status,
        tags=tags,
        provenance=prov,
    )


def make_note(title: str, body: str, prov: Provenance) -> AnalysisNote:
    base = {"title": title, "body": body, "prov": prov.to_dict(), "t": now_iso()}
    return AnalysisNote(
        id=f"N-{stable_hash(base)}",
        created_at=base["t"],
        title=title,
        body=body,
        provenance=prov,
    )


def _sanitize_ident(s: str) -> str:
    out = re.sub(r"[^A-Za-z0-9_']", "_", s.strip())
    if not out:
        return "x"
    if out[0].isdigit():
        out = f"x_{out}"
    return out


def make_equation_from_claim(claim: LogicClaim, statement_id: str, prov: Provenance) -> Equation:
    text = claim.text.strip()
    if claim.kind == "definition" and text.startswith("def ") and ":=" in text:
        lhs = text[4:].split(":=", 1)[0].strip()
        lean_name = _sanitize_ident(lhs)
    else:
        lean_name = _sanitize_ident(f"eq_{claim.id}")

    base = {
        "claim_id": claim.id,
        "statement_id": statement_id,
        "lean_name": lean_name,
        "expression": text,
        "t": now_iso(),
    }
    return Equation(
        id=f"E-{stable_hash(base)}",
        created_at=base["t"],
        claim_id=claim.id,
        statement_id=statement_id,
        lean_name=lean_name,
        expression=text,
        tags=["phase1", "equation", claim.kind],
        provenance=prov,
    )


def make_derivation_step(
    statement_id: str,
    claim_id: str,
    equation_id: str,
    relation: Literal["grounds", "realizes", "interprets"],
    notes: str,
    prov: Provenance,
) -> DerivationStep:
    base = {
        "statement_id": statement_id,
        "claim_id": claim_id,
        "equation_id": equation_id,
        "relation": relation,
        "notes": notes,
        "t": now_iso(),
    }
    return DerivationStep(
        id=f"D-{stable_hash(base)}",
        created_at=base["t"],
        statement_id=statement_id,
        claim_id=claim_id,
        equation_id=equation_id,
        relation=relation,
        notes=notes,
        provenance=prov,
    )


def make_triangle(statement_id: str, derivation_id: str, equation_id: str, prov: Provenance) -> Triangle:
    base = {
        "statement_id": statement_id,
        "derivation_id": derivation_id,
        "equation_id": equation_id,
        "t": now_iso(),
    }
    return Triangle(
        id=f"T-{stable_hash(base)}",
        created_at=base["t"],
        statement_id=statement_id,
        derivation_id=derivation_id,
        equation_id=equation_id,
        provenance=prov,
    )
