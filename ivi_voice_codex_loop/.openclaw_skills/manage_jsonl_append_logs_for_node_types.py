"""
Skill: manage_jsonl_append_logs_for_node_types
Manages JSONL append-only logs for different node types ('S', 'D', 'E', 'T') to ensure efficient and organized storage.
"""

import json
import os
from typing import Any, Dict

class JSONLLogManager:
    def __init__(self, base_directory: str):
        self.base_directory = base_directory
        os.makedirs(base_directory, exist_ok=True)

    def _get_log_file_path(self, node_type: str) -> str:
        return os.path.join(self.base_directory, f'{node_type}.jsonl')

    def append_to_log(self, node_type: str, data: Dict[str, Any]):
        log_file_path = self._get_log_file_path(node_type)
        with open(log_file_path, 'a') as log_file:
            log_file.write(json.dumps(data) + '\n')

    def read_log(self, node_type: str) -> list:
        log_file_path = self._get_log_file_path(node_type)
        if not os.path.exists(log_file_path):
            return []
        with open(log_file_path, 'r') as log_file:
            return [json.loads(line) for line in log_file]