"""
Skill: initialize_paths_with_defaults
Initialize paths with optional overrides, providing default values if not specified.
"""

from pathlib import Path
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    root: Path
    config_dir: Path
    log_path: Path
    data_path: Path

    @staticmethod
    def load(root: Path | None = None, config_path: Path | None = None) -> "Config":
        r = (root or Path(".")).resolve()
        cfg = r / "config"
        data_cfg = (config_path or (r / "data.json")).resolve()
        return Config(
            root=r,
            config_dir=cfg,
            log_path=cfg / "logs.jsonl",
            data_path=data_cfg,
        )