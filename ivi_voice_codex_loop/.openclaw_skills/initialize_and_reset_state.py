"""
Skill: initialize_and_reset_state
Initializes directories and resets the application state using provided configuration settings.
"""

def initialize_and_reset_state(settings: Settings) -> int:
    """
    Initializes directories and resets the application state.

    Args:
        settings (Settings): Configuration settings for the application.

    Returns:
        int: Status code, 0 for success.
    """
    ensure_dirs(settings)
    rebuild_state(settings)
    return 0