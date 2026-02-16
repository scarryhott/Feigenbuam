"""
Skill: ensure_directories_exist_for_settings
Ensures that all required directories exist as specified in the provided Settings object, creating them if necessary.
"""

from pathlib import Path
from .config import Settings

def ensure_directories_exist_for_settings(settings: Settings) -> None:
    """
    Ensures that all required directories exist as specified in the provided Settings object.
    Creates the directories if they do not exist.

    :param settings: A Settings object containing directory paths.
    """
    settings.ivi_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.lean_out_dir.mkdir(parents=True, exist_ok=True)
    (settings.root / "IVI").mkdir(parents=True, exist_ok=True)
    (settings.root / "IVI" / "Derived").mkdir(parents=True, exist_ok=True)