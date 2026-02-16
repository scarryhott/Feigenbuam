"""
Skill: initialize_application_settings
Initializes the application settings by ensuring necessary directories exist and rebuilding the application state.
"""

def initialize_application_settings(settings: Settings) -> int:
    """Initialize the application settings by ensuring directories exist and rebuilding the state."""
    ensure_dirs(settings)
    rebuild_state(settings)
    return 0