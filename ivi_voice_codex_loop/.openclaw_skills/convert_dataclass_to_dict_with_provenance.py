"""
Skill: convert_dataclass_to_dict_with_provenance
Converts a dataclass instance with provenance attribute to a dictionary, ensuring nested dataclasses are converted as well.
"""

from dataclasses import asdict
from typing import Any, Dict

class DataclassWithProvenance:
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["provenance"] = self.provenance.to_dict()
        return d
