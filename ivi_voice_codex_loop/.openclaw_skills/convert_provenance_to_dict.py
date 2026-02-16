"""
Skill: convert_provenance_to_dict
This function converts a Provenance dataclass instance to a dictionary, ensuring all nested dataclasses are also converted to dictionaries. It handles the nested Provenance conversion explicitly.
"""

from dataclasses import asdict
from typing import Dict, Any

@dataclass
class Provenance:
    source_type: Literal["voice", "text", "chatlog", "import"]
    source_id: str  # e.g. file path, run id, etc.
    span: Optional[str] = None  # optional line/offset span
    depends_on: Optional[List[str]] = None  # ids of other IR items

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# Usage example
provenance_instance = Provenance("voice", "some_source_id")
provenance_dict = provenance_instance.to_dict()