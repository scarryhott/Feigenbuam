"""
Skill: dataclass_to_dict_with_nested_handling
Converts a dataclass to a dictionary, ensuring nested Provenance objects are also converted.
"""

from dataclasses import asdict
from typing import Any, Dict

class Provenance:
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class Utterance:
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d

class Equation:
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d

# Usage example
# utterance = Utterance(...)
# print(utterance.to_dict())