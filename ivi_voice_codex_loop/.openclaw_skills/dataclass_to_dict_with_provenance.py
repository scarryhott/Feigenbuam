"""
Skill: dataclass_to_dict_with_provenance
Converts a dataclass instance to a dictionary, handling nested Provenance dataclasses specifically.
"""

from dataclasses import asdict
from typing import Any, Dict

class Provenance:
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class GenericClassWithProvenance:
    provenance: Provenance

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['provenance'] = self.provenance.to_dict()
        return d

# Example usage:
# instance = GenericClassWithProvenance(...)
# instance_dict = instance.to_dict()