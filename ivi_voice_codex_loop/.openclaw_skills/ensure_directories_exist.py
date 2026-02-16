"""
Skill: ensure_directories_exist
Ensures that necessary directories specified in the settings exist by creating them if they don't.
"""

def ensure_directories_exist(settings: Settings) -> None:
    settings.ivi_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.lean_out_dir.mkdir(parents=True, exist_ok=True)
    (settings.root / "IVI").mkdir(parents=True, exist_ok=True)
    (settings.root / "IVI" / "Derived").mkdir(parents=True, exist_ok=True)