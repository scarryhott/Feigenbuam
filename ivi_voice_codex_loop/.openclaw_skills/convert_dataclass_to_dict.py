"""
Skill: convert_dataclass_to_dict
Converts a dataclass instance to a dictionary, ensuring nested dataclasses are also converted to dictionaries.
"""

from dataclasses import asdict
from typing import Any, Dict

class Provenance:
    # Assume fields are defined here
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class Utterance:
    # Assume fields are defined here
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d

class Equation:
    # Assume fields are defined here
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d