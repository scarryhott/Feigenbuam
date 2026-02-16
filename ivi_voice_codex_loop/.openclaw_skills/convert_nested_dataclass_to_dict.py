"""
Skill: convert_nested_dataclass_to_dict
Converts a dataclass instance to a dictionary, including nested dataclass instances.
"""

from dataclasses import asdict, is_dataclass
from typing import Any, Dict

def convert_nested_dataclass_to_dict(instance: Any) -> Dict[str, Any]:
    """
    Converts a dataclass instance to a dictionary, including nested dataclass instances.
    """
    if not is_dataclass(instance):
        raise ValueError("Provided instance is not a dataclass")
    
    result_dict = asdict(instance)
    for key, value in result_dict.items():
        if is_dataclass(value):
            result_dict[key] = convert_nested_dataclass_to_dict(value)
    
    return result_dict

# Example usage:
# my_instance = MyDataClass(...)
# my_dict = convert_nested_dataclass_to_dict(my_instance)