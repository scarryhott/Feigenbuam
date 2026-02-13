from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .config import Settings, read_analysis_config
from .ir import (
    DerivationStep,
    Equation,
    LogicClaim,
    Triangle,
    Utterance,
    make_derivation_step,
    make_equation_from_claim,
    make_triangle,
)
from .derive import derive_claims_from_text
from .storage import append_event, rebuild_state, read_json, write_json


@dataclass
class LoopResult:
    accepted: List[LogicClaim]
    quarantined: List[LogicClaim]
    equations: List[Equation]
    derivations: List[DerivationStep]
    triangles: List[Triangle]
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
        return LoopResult(
            accepted=[],
            quarantined=[],
            equations=[],
            derivations=[],
            triangles=[],
            skipped=True,
            reason="question_detected",
        )

    raw_claims = derive_claims_from_text(utt.text, prov=utt.provenance)

    accepted: List[LogicClaim] = []
    quarantined: List[LogicClaim] = []
    equations: List[Equation] = []
    derivations: List[DerivationStep] = []
    triangles: List[Triangle] = []

    max_claims = int(cfg["instructions"]["derive"].get("max_claims_per_run", 200))
    for c in raw_claims[:max_claims]:
        c = _apply_thresholds(cfg, c)
        append_event(settings, {"type": "logic_claim", "payload": c.to_dict()})
        if c.status == "accepted":
            accepted.append(c)

            eq = make_equation_from_claim(c, statement_id=utt.id, prov=utt.provenance)
            der = make_derivation_step(
                statement_id=utt.id,
                claim_id=c.id,
                equation_id=eq.id,
                relation="grounds",
                notes="Auto-linked from accepted claim in phase-1 loop.",
                prov=utt.provenance,
            )
            tri = make_triangle(statement_id=utt.id, derivation_id=der.id, equation_id=eq.id, prov=utt.provenance)

            equations.append(eq)
            derivations.append(der)
            triangles.append(tri)

            append_event(settings, {"type": "equation", "payload": eq.to_dict()})
            append_event(settings, {"type": "derivation", "payload": der.to_dict()})
            append_event(settings, {"type": "triangle", "payload": tri.to_dict()})
        else:
            quarantined.append(c)

    quarantine_view = read_json(settings.quarantine_path, default={"claims": {}})
    for c in quarantined:
        quarantine_view["claims"][c.id] = c.to_dict()
    write_json(settings.quarantine_path, quarantine_view)

    rebuild_state(settings)
    return LoopResult(
        accepted=accepted,
        quarantined=quarantined,
        equations=equations,
        derivations=derivations,
        triangles=triangles,
        skipped=False,
        reason="derived",
    )
