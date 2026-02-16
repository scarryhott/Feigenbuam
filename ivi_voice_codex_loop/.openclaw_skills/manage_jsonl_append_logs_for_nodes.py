"""
Skill: manage_jsonl_append_logs_for_nodes
Manages JSONL append-only logs for various node types in a simplicial complex system.
"""

import json
import os
from typing import Any, Dict


def append_to_jsonl(file_path: str, data: Dict[str, Any]) -> None:
    """
    Append a dictionary as a JSON object to a JSONL file.

    :param file_path: Path to the JSONL file.
    :param data: Dictionary containing the data to append.
    """
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    with open(file_path, 'a') as f:
        json.dump(data, f)
        f.write('\n')
