"""
Skill: convert_nested_dataclass_to_dict_v2
Converts dataclass instances to dictionaries, including nested dataclasses by calling their own to_dict method if available.
"""

from dataclasses import asdict
from typing import Any, Dict

class NestedDataclassMixin:
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for key, value in d.items():
            if hasattr(value, 'to_dict'):
                d[key] = value.to_dict()
        return d

@dataclass
class Example(NestedDataclassMixin):
    id: str
    nested: Any

# Usage:
# example = Example(id='123', nested=AnotherDataclass(...))
# example_dict = example.to_dict()