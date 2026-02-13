from __future__ import annotations

import hashlib
import json
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
