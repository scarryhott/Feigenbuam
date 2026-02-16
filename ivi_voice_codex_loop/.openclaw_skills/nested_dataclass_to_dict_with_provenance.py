"""
Skill: nested_dataclass_to_dict_with_provenance
Converts a dataclass instance to a dictionary, handling nested dataclasses like Provenance separately to ensure they are also converted to dictionaries.
"""

from dataclasses import asdict
from typing import Any, Dict

class NestedDataclassWithProvenance:
    @staticmethod
    def to_dict(instance: Any) -> Dict[str, Any]:
        """
        Convert a dataclass instance to a dictionary, ensuring that nested
        dataclasses, especially those with provenance, are also converted properly.
        """
        d = asdict(instance)
        if hasattr(instance, 'provenance'):
            d['provenance'] = instance.provenance.to_dict()
        return d

# Example usage:
# utterance_dict = NestedDataclassWithProvenance.to_dict(utterance_instance)