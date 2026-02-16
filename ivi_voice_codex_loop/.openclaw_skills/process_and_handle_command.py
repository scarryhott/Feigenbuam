"""
Skill: process_and_handle_command
This skill processes a command by stripping whitespace, checking its format, and handling it with a function. It includes error handling with context-specific hints.
"""

def process_and_handle_command(settings, text, handler_function):
    stripped = text.strip()
    if stripped.startswith("/"):
        try:
            result = handler_function(settings, stripped)
        except Exception as exc:
            detail = str(exc)
            hint = ""
            if stripped.startswith("/openclaw attach"):
                hint = (
                    "Use a real local path that contains soul.md. "
                    "Example: /openclaw attach /Users/<you>/path/to/openclaw_repo"
                )
                if "<" in stripped or ">" in stripped:
                    hint = (
                        "Detected placeholder in path. Please replace with actual path."
                    )
            print(f"Error: {detail} {hint}")
            return -1
        return result
    else:
        print("Command does not start with '/', ignoring.")
        return -1