from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Settings


@dataclass
class Event:
    type: str  # "utterance" | "logic_claim" | "analysis_note" | "equation" | "derivation" | "triangle" | "intent" | "attest"
    payload: Dict[str, Any]


# Active branch for event enrichment (set by IVI Semantic Enforcement Duality)
_active_branch_id: str = "main"
_active_parent_branch_id: str = ""


def set_branch(branch_id: str, parent_branch_id: str = "") -> None:
    global _active_branch_id, _active_parent_branch_id
    _active_branch_id = branch_id
    _active_parent_branch_id = parent_branch_id


def ensure_dirs(settings: Settings) -> None:
    settings.ivi_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.lean_out_dir.mkdir(parents=True, exist_ok=True)
    (settings.root / "IVI").mkdir(parents=True, exist_ok=True)
    (settings.root / "IVI" / "Derived").mkdir(parents=True, exist_ok=True)


def append_event(settings: Settings, event: Event | Dict[str, Any]) -> None:
    ensure_dirs(settings)
    if isinstance(event, dict):
        record = {"type": event["type"], "payload": event["payload"]}
    else:
        record = {"type": event.type, "payload": event.payload}
    # Enrich with branch metadata (IVI Semantic Enforcement Duality)
    record["branch_id"] = _active_branch_id
    record["parent_branch_id"] = _active_parent_branch_id
    with settings.events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_events(settings: Settings) -> List[Event]:
    if not settings.events_path.exists():
        return []
    out: List[Event] = []
    with settings.events_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            out.append(Event(type=obj["type"], payload=obj["payload"]))
    return out


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, sort_keys=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def rebuild_state(settings: Settings) -> Dict[str, Any]:
    """
    Compute the current view from the append-only event log.
    """
    events = read_events(settings)
    utterances: Dict[str, Dict[str, Any]] = {}
    claims: Dict[str, Dict[str, Any]] = {}
    quarantined_claims: Dict[str, Dict[str, Any]] = {}
    notes: Dict[str, Dict[str, Any]] = {}
    equations: Dict[str, Dict[str, Any]] = {}
    derivations: Dict[str, Dict[str, Any]] = {}
    triangles: Dict[str, Dict[str, Any]] = {}

    for ev in events:
        p = ev.payload
        if ev.type == "utterance":
            utterances[p["id"]] = p
        elif ev.type == "logic_claim":
            if p.get("status") == "accepted":
                claims[p["id"]] = p
            else:
                quarantined_claims[p["id"]] = p
        elif ev.type == "analysis_note":
            notes[p["id"]] = p
        elif ev.type == "equation":
            equations[p["id"]] = p
        elif ev.type == "derivation":
            derivations[p["id"]] = p
        elif ev.type == "triangle":
            triangles[p["id"]] = p

    state = {
        "utterances": utterances,
        "logic_claims": claims,
        "quarantined_claims": quarantined_claims,
        "analysis_notes": notes,
        "equations": equations,
        "derivations": derivations,
        "triangles": triangles,
        "counts": {
            "utterances": len(utterances),
            "logic_claims": len(claims),
            "quarantined_claims": len(quarantined_claims),
            "analysis_notes": len(notes),
            "equations": len(equations),
            "derivations": len(derivations),
            "triangles": len(triangles),
            "events_total": len(events),
        },
    }
    write_json(settings.state_path, state)
    return state


def load_state(settings: Settings) -> Dict[str, Any]:
    if settings.state_path.exists():
        return read_json(settings.state_path, default={})
    return rebuild_state(settings)


# ---------------------------------------------------------------------------
# Intent / Attest co-signature helpers (IVI Gateway)
# ---------------------------------------------------------------------------

def append_intent(
    settings: Settings,
    intent_id: str,
    actor: str,
    channel: str,
    action_class: str,
    requested_tools: Optional[List[str]] = None,
    requested_paths: Optional[List[str]] = None,
    network: Optional[str] = None,
    consent_scope: Optional[str] = None,
    skill_ctx: Optional[str] = None,
    order_mode: str = "order_1_projection_safe",
) -> Dict[str, Any]:
    """Write an intent event BEFORE any effectful action.
    Returns the intent payload for later reference by attest."""
    payload = {
        "intent_id": intent_id,
        "actor": actor,
        "channel": channel,
        "action_class": action_class,
        "requested_tools": requested_tools or [],
        "requested_paths": requested_paths or [],
        "network": network or "",
        "consent_scope": consent_scope or "",
        "skill_ctx": (skill_ctx or "")[:200],
        "order_mode": order_mode,
        "domain": "imaginary",  # 0-side: staged, no external effects yet
        "ts": time.time(),
    }
    append_event(settings, {"type": "intent", "payload": payload})
    return payload


def append_attest(
    settings: Settings,
    intent_id: str,
    verifier_results: Optional[Dict[str, Any]] = None,
    diff_stats: Optional[Dict[str, Any]] = None,
    lean_result: Optional[str] = None,
    reason_codes: Optional[List[str]] = None,
    commit_hash: str = "",
    committed: bool = True,
) -> Dict[str, Any]:
    """Write an attest event AFTER verification/execution.
    Must reference exactly one intent_id."""
    # Domain promotion: committed attest = real (∞-side), rejected = stays imaginary (0-side)
    domain = "real" if committed else "imaginary"
    payload = {
        "intent_id": intent_id,
        "verifier_results": verifier_results or {},
        "diff_stats": diff_stats or {},
        "lean_result": lean_result or "skipped",
        "reason_codes": reason_codes or [],
        "commit_hash": commit_hash,
        "committed": committed,
        "domain": domain,
        "ts": time.time(),
    }
    append_event(settings, {"type": "attest", "payload": payload})
    return payload


def validate_intent_attest_pairs(settings: Settings) -> Dict[str, Any]:
    """Check that every attest references a valid intent.
    Returns {valid: bool, orphan_attests: [...], unattested_intents: [...]}."""
    events = read_events(settings)
    intent_ids = set()
    attested_ids = set()
    orphan_attests = []

    for ev in events:
        if ev.type == "intent":
            intent_ids.add(ev.payload.get("intent_id", ""))
        elif ev.type == "attest":
            ref = ev.payload.get("intent_id", "")
            attested_ids.add(ref)
            if ref not in intent_ids:
                orphan_attests.append(ref)

    unattested = intent_ids - attested_ids
    return {
        "valid": len(orphan_attests) == 0,
        "orphan_attests": orphan_attests,
        "unattested_intents": list(unattested),
        "intent_count": len(intent_ids),
        "attest_count": len(attested_ids),
    }
