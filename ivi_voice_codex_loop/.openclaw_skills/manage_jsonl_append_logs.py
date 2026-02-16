"""
Skill: manage_jsonl_append_logs
Handles JSONL append-only logging for different node types in a simplicial complex structure, ensuring structured data logging.
"""

import json
from typing import Any, Dict

def append_to_jsonl(file_path: str, data: Dict[str, Any]) -> None:
    """
    Appends a dictionary as a JSON object to a JSONL file.
    :param file_path: Path to the JSONL file.
    :param data: Dictionary to append as a JSON object.
    """
    with open(file_path, 'a') as file:
        json.dump(data, file)
        file.write('\n')

def read_jsonl(file_path: str) -> list:
    """
    Reads a JSONL file and returns a list of dictionaries.
    :param file_path: Path to the JSONL file.
    :return: List of dictionaries.
    """
    with open(file_path, 'r') as file:
        return [json.loads(line) for line in file]