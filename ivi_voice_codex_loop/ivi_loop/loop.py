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
    make_note,
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


def _strict_marker_required(cfg: Dict[str, Any], text: str) -> bool:
    derive_cfg = cfg["instructions"].get("derive", {})
    if str(derive_cfg.get("mode", "")).lower() != "strict":
        return False
    markers = derive_cfg.get("require_explicit_markers", [])
    if not markers:
        return False
    return not any(str(m) in text for m in markers)


def process_utterance(settings: Settings, utt: Utterance) -> LoopResult:
    cfg = read_analysis_config(settings.analysis_config_path)
    qcfg = cfg["instructions"].get("questions", {})
    do_not_loop_questions = bool(qcfg.get("do_not_loop_on_questions", True))
    strict_mode = str(cfg["instructions"].get("derive", {}).get("mode", "")).lower() == "strict"

    utterance_logged = False
    if not strict_mode:
        append_event(settings, {"type": "utterance", "payload": utt.to_dict()})
        utterance_logged = True

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

    if _strict_marker_required(cfg, utt.text):
        note = make_note(
            title="strict_rejected_statement",
            body="Statement excluded from active memory: missing strict derivation marker.",
            prov=utt.provenance,
        )
        append_event(settings, {"type": "analysis_note", "payload": note.to_dict()})
        rebuild_state(settings)
        return LoopResult(
            accepted=[],
            quarantined=[],
            equations=[],
            derivations=[],
            triangles=[],
            skipped=True,
            reason="strict_marker_required",
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
        if c.status == "accepted":
            if strict_mode and not utterance_logged:
                append_event(settings, {"type": "utterance", "payload": utt.to_dict()})
                utterance_logged = True
            append_event(settings, {"type": "logic_claim", "payload": c.to_dict()})
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
            if not strict_mode:
                append_event(settings, {"type": "logic_claim", "payload": c.to_dict()})

    quarantine_view = read_json(settings.quarantine_path, default={"claims": {}})
    for c in quarantined:
        quarantine_view["claims"][c.id] = c.to_dict()
    write_json(settings.quarantine_path, quarantine_view)

    if strict_mode and not accepted:
        note = make_note(
            title="strict_rejected_no_derivation",
            body="Statement excluded from active memory: no accepted derivation reached Lean-compatible form.",
            prov=utt.provenance,
        )
        append_event(settings, {"type": "analysis_note", "payload": note.to_dict()})
        rebuild_state(settings)
        return LoopResult(
            accepted=[],
            quarantined=quarantined,
            equations=[],
            derivations=[],
            triangles=[],
            skipped=True,
            reason="strict_no_accepted_derivation",
        )

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
