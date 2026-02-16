"""
Skill: initialize_directories_and_state
This function initializes the application by ensuring necessary directories exist and rebuilding the state based on provided settings.
"""

def initialize_directories_and_state(settings: Settings) -> int:
    ensure_dirs(settings)
    rebuild_state(settings)
    return 0