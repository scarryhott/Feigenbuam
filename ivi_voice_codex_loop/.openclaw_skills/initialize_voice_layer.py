"""
Skill: initialize_voice_layer
Initializes the directory and state for the voice layer in a given settings context by ensuring directories and rebuilding state.
"""

from typing import Any
from pathlib import Path
from .storage import ensure_dirs, rebuild_state
from .config import Settings

VOICE_LAYER_DIRNAME = ".ivi_voice_layer"
VOICE_STATE_FILENAME = "voice_state.json"

def initialize_voice_layer(settings: Settings) -> int:
    """
    Initialize the directory and state for the voice layer using the provided settings.

    Args:
        settings (Settings): The settings object containing configuration.

    Returns:
        int: Status code, 0 indicates success.
    """
    ensure_dirs(settings)
    rebuild_state(settings)
    return 0