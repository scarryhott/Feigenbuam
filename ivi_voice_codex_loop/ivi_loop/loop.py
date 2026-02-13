from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .config import Settings, read_analysis_config
from .ir import Utterance, LogicClaim
from .derive import derive_claims_from_text
from .storage import append_event, rebuild_state, read_json, write_json


@dataclass
class LoopResult:
    accepted: List[LogicClaim]
    quarantined: List[LogicClaim]
    skipped: bool
    reason: str


def _apply_thresholds(cfg: Dict[str, Any], claim: LogicClaim) -> LogicClaim:
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


def process_utterance(settings: Settings, utt: Utterance) -> LoopResult:
    cfg = read_analysis_config(settings.analysis_config_path)
    qcfg = cfg["instructions"].get("questions", {})
    do_not_loop_questions = bool(qcfg.get("do_not_loop_on_questions", True))

    append_event(settings, {"type": "utterance", "payload": utt.to_dict()})

    if utt.is_question and do_not_loop_questions:
        rebuild_state(settings)
        return LoopResult(accepted=[], quarantined=[], skipped=True, reason="question_detected")

    raw_claims = derive_claims_from_text(utt.text, prov=utt.provenance)

    accepted: List[LogicClaim] = []
    quarantined: List[LogicClaim] = []

    max_claims = int(cfg["instructions"]["derive"].get("max_claims_per_run", 200))
    for c in raw_claims[:max_claims]:
        c = _apply_thresholds(cfg, c)
        append_event(settings, {"type": "logic_claim", "payload": c.to_dict()})
        if c.status == "accepted":
            accepted.append(c)
        else:
            quarantined.append(c)

    quarantine_view = read_json(settings.quarantine_path, default={"claims": {}})
    for c in quarantined:
        quarantine_view["claims"][c.id] = c.to_dict()
    write_json(settings.quarantine_path, quarantine_view)

    rebuild_state(settings)
    return LoopResult(accepted=accepted, quarantined=quarantined, skipped=False, reason="derived")
