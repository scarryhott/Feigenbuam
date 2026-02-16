"""
Skill: generate_stable_hash
Generates a stable hash for any JSON-serializable object by encoding it and creating a SHA-256 hash, truncated to 16 characters.
"""

import hashlib
import json
from typing import Any

def generate_stable_hash(obj: Any) -> str:
    """
    Generates a stable hash for any JSON-serializable object by encoding it and
    creating a SHA-256 hash, truncated to 16 characters.

    Args:
        obj (Any): The object to hash.

    Returns:
        str: The first 16 characters of the SHA-256 hash.
    """
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]