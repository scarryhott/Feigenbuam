"""
Skill: load_dotenv_with_check
Loads environment variables from a .env file, ensuring they are loaded only once and handling any potential file read errors.
"""

def load_dotenv_with_check() -> None:
    """
    Load environment variables from a .env file if not already loaded. This prevents reloading
    and potential overwriting of existing environment variables, ensuring efficient resource usage.
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
