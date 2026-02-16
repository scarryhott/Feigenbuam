"""
Skill: load_config_paths
Loads configuration paths based on a root directory, providing a structured way to manage file and directory paths for configuration purposes.
"""

from pathlib import Path
from dataclasses import dataclass

@dataclass(frozen=True)
class ConfigPaths:
    root: Path
    config_dir: Path
    events_path: Path
    state_path: Path
    quarantine_path: Path
    reports_dir: Path
    derived_dir: Path
    analysis_config_path: Path

    @staticmethod
    def load(root: Path | None = None, analysis_config_path: Path | None = None) -> "ConfigPaths":
        r = (root or Path(".").resolve()).resolve()
        config_dir = r / "config"
        analysis_cfg = (analysis_config_path or (r / "analysis.json")).resolve()
        return ConfigPaths(
            root=r,
            config_dir=config_dir,
            events_path=config_dir / "events.jsonl",
            state_path=config_dir / "state.json",
            quarantine_path=config_dir / "quarantine.json",
            reports_dir=config_dir / "reports",
            derived_dir=(r / "Derived"),
            analysis_config_path=analysis_cfg,
        )