"""
Skill: initialize_voice_environment
Initializes the voice environment by ensuring necessary directories exist and rebuilding the system state using the provided settings.
"""

from pathlib import Path
from .storage import ensure_dirs, rebuild_state
from .config import Settings

def initialize_voice_environment(settings: Settings) -> int:
    """
    Initializes the voice environment by ensuring necessary directories exist and rebuilding the system state.

    Args:
        settings (Settings): The configuration settings for initializing the environment.

    Returns:
        int: A status code indicating success (0) or failure.
    """
    ensure_dirs(settings)
    rebuild_state(settings)
    return 0