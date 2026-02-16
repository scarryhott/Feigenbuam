"""
Skill: append_event_with_directory_creation
Appends an event to a file after ensuring necessary directories exist, checking if the event is a dictionary or Event object, and writes it as a JSON line.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

@dataclass
class Event:
    type: str  # "utterance" | "logic_claim" | "analysis_note" | "equation" | "derivation" | "triangle"
    payload: Dict[str, Any]


def append_event_with_directory_creation(settings: Any, event: Event | Dict[str, Any]) -> None:
    """Appends an event to a file after ensuring directories exist."""
    ensure_dirs(settings)
    if isinstance(event, dict):
        record = {"type": event["type"], "payload": event["payload"]}
    else:
        record = {"type": event.type, "payload": event.payload}
    with settings.events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
