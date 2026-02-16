"""
Skill: manage_jsonl_append_logs_with_structure
Appends entries to a JSONL file while ensuring the necessary directory structure exists.
"""

import os
import json

def manage_jsonl_append_logs_with_structure(file_path: str, entry: dict) -> None:
    """
    Append an entry to a JSONL file, ensuring the directory structure exists.

    :param file_path: Path to the JSONL file.
    :param entry: A dictionary entry to append.
    """
    # Ensure the directory exists
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    # Append the entry as a JSON line
    with open(file_path, 'a') as f:
        f.write(json.dumps(entry) + '\n')