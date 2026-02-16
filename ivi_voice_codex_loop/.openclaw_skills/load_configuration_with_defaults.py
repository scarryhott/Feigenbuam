"""
Skill: load_configuration_with_defaults
Loads configuration paths using default values and optional overrides, encapsulated in a dataclass for structured and type-safe management.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

@dataclass(frozen=True)
class Config:
    root: Path
    config_dir: Path
    config_file: Path
    log_dir: Path
    backup_dir: Path

    @staticmethod
    def load(root: Path | None = None, config_file: Path | None = None) -> "Config":
        r = (root or Path(".").resolve()).resolve()
        config_dir = r / "config"
        cfg_file = (config_file or (config_dir / "settings.json")).resolve()
        return Config(
            root=r,
            config_dir=config_dir,
            config_file=cfg_file,
            log_dir=r / "logs",
            backup_dir=r / "backups",
        )