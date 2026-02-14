import json

import pytest

from ivi_loop.config import Settings
from ivi_loop.ir import Provenance, make_utterance
from ivi_loop.loop import process_utterance
from ivi_loop.report import format_status
from ivi_loop.storage import load_state


def _write_analysis_config(root):
    cfg = {
        "instructions": {
            "derive": {
                "mode": "strict",
                "min_confidence_to_accept": 0.6,
                "min_confidence_to_quarantine": 0.35,
                "require_explicit_markers": ["Define", "IF", "THEN", "iff", "→", "↔", ":"],
                "max_claims_per_run": 200,
            },
            "kb": {
                "definition_policy": "single_active",
                "conflict_policy": "quarantine",
                "quarantine_tag": "needs_review",
            },
            "lean": {
                "emit_axioms_only_if_confidence_ge": 0.7,
                "emit_theorem_stubs_for_rules": True,
                "namespace": "IVI.Derived.Phase1",
            },
            "questions": {"do_not_loop_on_questions": True},
        }
    }
    (root / "analysis_phase1.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")


@pytest.mark.order1
def test_strict_mode_excludes_non_derived_statements_from_active_memory(tmp_path):
    root = tmp_path / "strict_repo"
    root.mkdir(parents=True, exist_ok=True)
    _write_analysis_config(root)

    settings = Settings.load(root=root)
    prov = Provenance(source_type="text", source_id="test")

    rejected = make_utterance(role="human", text="this is free prose without explicit marker", is_question=False, prov=prov)
    res_reject = process_utterance(settings, rejected)
    assert res_reject.skipped
    assert res_reject.reason == "strict_marker_required"

    state_after_reject = load_state(settings)
    assert state_after_reject.get("counts", {}).get("utterances", 0) == 0
    assert state_after_reject.get("counts", {}).get("logic_claims", 0) == 0
    assert state_after_reject.get("counts", {}).get("analysis_notes", 0) >= 1

    accepted = make_utterance(role="human", text="Define TriangleTime as relational closure", is_question=False, prov=prov)
    res_accept = process_utterance(settings, accepted)
    assert not res_accept.skipped
    assert res_accept.reason == "derived"
    assert len(res_accept.accepted) == 1

    state_after_accept = load_state(settings)
    counts = state_after_accept.get("counts", {})
    assert counts.get("utterances", 0) == 1
    assert counts.get("logic_claims", 0) == 1
    assert counts.get("quarantined_claims", 0) == 0
    assert counts.get("equations", 0) == 1
    assert counts.get("derivations", 0) == 1
    assert counts.get("triangles", 0) == 1

    status = format_status(settings)
    assert "active_memory_mode: strict_derived_only" in status
    assert "claims_active:1" in status
    assert "claims_quarantine_state: 0" in status
