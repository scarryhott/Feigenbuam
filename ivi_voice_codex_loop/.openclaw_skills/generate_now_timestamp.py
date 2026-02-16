"""
Skill: generate_now_timestamp
Generates the current timestamp in floating point format, representing the current time in seconds since the epoch (January 1, 1970).
"""

def generate_now_timestamp() -> float:
    import time
    return time.time()