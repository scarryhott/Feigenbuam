"""
Skill: load_dotenv_once_with_fallback
Loads environment variables from a .env file only once, ensuring the environment is configured correctly without redundancy.
"""

from pathlib import Path
import os

def load_dotenv_once_with_fallback() -> None:
    """
    Load environment variables from a .env file if not already loaded.
    Looks in the current directory and the parent directory of the current file.
    """
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