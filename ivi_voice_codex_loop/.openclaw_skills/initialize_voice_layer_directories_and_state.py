"""
Skill: initialize_voice_layer_directories_and_state
Ensures required directories exist and initializes or rebuilds the voice layer state with the provided settings.
"""

from pathlib import Path
from .storage import ensure_dirs, rebuild_state


def initialize_voice_layer_directories_and_state(settings):
    """
    Ensures that the necessary directories for the voice layer exist and rebuilds the state.

    :param settings: Settings object containing configuration.
    :return: None
    """
    ensure_dirs(settings)
    rebuild_state(settings)