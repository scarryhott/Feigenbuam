"""
Skill: dataclass_to_nested_dict
Convert a dataclass to a dictionary, including nested dataclass conversion for fields like Provenance.
"""

from dataclasses import asdict, is_dataclass
from typing import Any, Dict

def dataclass_to_nested_dict(instance: Any) -> Dict[str, Any]:
    """
    Convert a dataclass instance to a dictionary, including handling of nested dataclasses.
    """
    if not is_dataclass(instance):
        raise ValueError("Provided instance is not a dataclass.")
    
    def convert(obj):
        if is_dataclass(obj):
            return {k: convert(v) for k, v in asdict(obj).items()}
        elif isinstance(obj, list):
            return [convert(i) for i in obj]
        elif isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        else:
            return obj

    return convert(instance)