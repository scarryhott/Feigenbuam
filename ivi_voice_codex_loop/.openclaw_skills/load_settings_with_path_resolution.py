"""
Skill: load_settings_with_path_resolution
This skill initializes a Settings dataclass with resolved paths and provides static loading with default fallbacks.
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict

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