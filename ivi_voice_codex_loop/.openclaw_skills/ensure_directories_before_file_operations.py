"""
Skill: ensure_directories_before_file_operations
Ensures directories are created before performing file operations such as appending to a log or data file.
"""

from pathlib import Path
from typing import Any, Dict, Union
from .config import Settings

class Event:
    def __init__(self, type: str, payload: Dict[str, Any]):
        self.type = type
        self.payload = payload


def ensure_dirs(settings: Settings) -> None:
    settings.ivi_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.lean_out_dir.mkdir(parents=True, exist_ok=True)
    (settings.root / "IVI").mkdir(parents=True, exist_ok=True)
    (settings.root / "IVI" / "Derived").mkdir(parents=True, exist_ok=True)


def append_event(settings: Settings, event: Union[Event, Dict[str, Any]]) -> None:
    ensure_dirs(settings)
    if isinstance(event, dict):
        record = {"type": event["type"], "payload": event["payload"]}
    else:
        record = {"type": event.type, "payload": event.payload}
    with settings.events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")