"""
Skill: load_dotenv_once
Ensures that dotenv files are loaded only once into the environment variables to prevent redundant operations.
"""

from pathlib import Path
import os

def load_dotenv_once() -> None:
    """Load dotenv files into os.environ only once."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    for candidate in [
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
    ]:
        if candidate.is_file():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if key and val and key not in os.environ:
                        os.environ[key] = val
            except OSError:
                pass
            break