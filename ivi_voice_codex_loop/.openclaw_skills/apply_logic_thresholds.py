"""
Skill: apply_logic_thresholds
Evaluates a LogicClaim's confidence against predefined thresholds to set its status and apply quarantine tags if necessary.
"""

from typing import Dict, Any

class LogicClaim:
    def __init__(self, confidence: float, status: str = '', tags: List[str] = None):
        self.confidence = confidence
        self.status = status
        self.tags = tags if tags is not None else []

def apply_logic_thresholds(cfg: Dict[str, Any], claim: LogicClaim) -> LogicClaim:
    derive_cfg = cfg["instructions"]["derive"]
    kb_cfg = cfg["instructions"]["kb"]
    min_accept = float(derive_cfg.get("min_confidence_to_accept", 0.6))
    min_quarantine = float(derive_cfg.get("min_confidence_to_quarantine", 0.35))

    if claim.confidence >= min_accept:
        claim.status = "accepted"
    elif claim.confidence >= min_quarantine:
        claim.status = "quarantined"
    else:
        claim.status = "quarantined"

    if claim.status == "quarantined":
        qtag = kb_cfg.get("quarantine_tag", "needs_review")
        if qtag not in claim.tags:
            claim.tags.append(qtag)

    return claim