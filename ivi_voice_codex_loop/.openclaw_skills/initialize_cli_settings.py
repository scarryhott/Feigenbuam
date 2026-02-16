"""
Skill: initialize_cli_settings
Initializes CLI command settings by ensuring necessary directories and rebuilding states.
"""

def initialize_cli_settings(settings):
    """
    Initialize CLI command settings by ensuring necessary directories and rebuilding states.

    Args:
        settings (Settings): Configuration settings for the CLI.

    Returns:
        int: Status code representing the success of the initialization.
    """
    ensure_dirs(settings)
    rebuild_state(settings)
    return 0