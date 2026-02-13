from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

DEFAULT_ROOT = Path(".").resolve()
DEFAULT_IVI_DIR = DEFAULT_ROOT / ".ivi"
DEFAULT_EVENTS = DEFAULT_IVI_DIR / "events.jsonl"
DEFAULT_STATE = DEFAULT_IVI_DIR / "state.json"
DEFAULT_QUARANTINE = DEFAULT_IVI_DIR / "quarantine.json"
DEFAULT_REPORTS = DEFAULT_IVI_DIR / "reports"
DEFAULT_LEAN_OUT = DEFAULT_ROOT / "IVI" / "Derived" / "Phase1"


@dataclass(frozen=True)
class Settings:
    root: Path
    ivi_dir: Path
    events_path: Path
    state_path: Path
    quarantine_path: Path
    reports_dir: Path
    lean_out_dir: Path
    analysis_config_path: Path

    @staticmethod
    def load(root: Path | None = None, analysis_config_path: Path | None = None) -> "Settings":
        r = (root or DEFAULT_ROOT).resolve()
        ivi = r / ".ivi"
        analysis_cfg = (analysis_config_path or (r / "analysis_phase1.json")).resolve()
        return Settings(
            root=r,
            ivi_dir=ivi,
            events_path=ivi / "events.jsonl",
            state_path=ivi / "state.json",
            quarantine_path=ivi / "quarantine.json",
            reports_dir=ivi / "reports",
            lean_out_dir=(r / "IVI" / "Derived" / "Phase1"),
            analysis_config_path=analysis_cfg,
        )


def read_analysis_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing analysis config: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
