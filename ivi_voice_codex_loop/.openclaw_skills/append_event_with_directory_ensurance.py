"""
Skill: append_event_with_directory_ensurance
Appends an event to a log file while ensuring that necessary directories exist, creating them if they do not.
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

@dataclass
class Event:
    type: str  # "utterance" | "logic_claim" | "analysis_note" | "equation" | "derivation" | "triangle"
    payload: Dict[str, Any]


def ensure_dirs(settings) -> None:
    settings.ivi_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.lean_out_dir.mkdir(parents=True, exist_ok=True)
    (settings.root / "IVI").mkdir(parents=True, exist_ok=True)
    (settings.root / "IVI" / "Derived").mkdir(parents=True, exist_ok=True)


def append_event_with_directory_ensurance(settings, event: Event | Dict[str, Any]) -> None:
    ensure_dirs(settings)
    if isinstance(event, dict):
        record = {"type": event["type"], "payload": event["payload"]}
    else:
        record = {"type": event.type, "payload": event.payload}
    with settings.events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")