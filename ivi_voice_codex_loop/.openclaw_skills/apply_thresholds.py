"""
Skill: apply_thresholds
Categorizes a LogicClaim based on confidence thresholds, updating its status and tags accordingly.
"""

def apply_thresholds(cfg: Dict[str, Any], claim: LogicClaim) -> LogicClaim:
    derive_cfg = cfg['instructions']['derive']
    kb_cfg = cfg['instructions']['kb']
    min_accept = float(derive_cfg.get('min_confidence_to_accept', 0.6))
    min_quarantine = float(derive_cfg.get('min_confidence_to_quarantine', 0.35))

    if claim.confidence >= min_accept:
        claim.status = 'accepted'
    elif claim.confidence >= min_quarantine:
        claim.status = 'quarantined'
    else:
        claim.status = 'quarantined'

    if claim.status == 'quarantined':
        qtag = kb_cfg.get('quarantine_tag', 'needs_review')
        if qtag not in claim.tags:
            claim.tags.append(qtag)

    return claim