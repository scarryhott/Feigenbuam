from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .config import Settings


@dataclass
class Event:
    type: str  # "utterance" | "logic_claim" | "analysis_note" | "equation" | "derivation" | "triangle"
    payload: Dict[str, Any]


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
