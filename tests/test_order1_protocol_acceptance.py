import math
from pathlib import Path
import sys
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1] / "ivi_voice_codex_loop"))

from ivi_loop.ivi_simplicial_grid import IVILoopController, IVISimplicialGrid


@pytest.mark.order1
def test_order1_protocol_acceptance_nontrivial_loop_and_explanation_consistency(tmp_path):
    repo_root = tmp_path / "order1_repo"
    grid = IVISimplicialGrid(base_dir=str(repo_root))
    loop = IVILoopController(grid)

    first = loop.add_statement_and_loop(
        "Define triangle time as relational closure with indeterminate continuation.",
        source="test",
    )
    second = loop.add_statement_and_loop(
        "Encode a Potential Transition System spine so Layer1-4 share one goal object.",
        source="test",
    )

    # Layer 3 + graph integration: we should have a nontrivial refinement structure.
    metrics = second["metrics"]["counts"]
    assert metrics["S"] >= 2
    assert metrics["D"] >= 2
    assert metrics["E"] >= 2
    assert metrics["T"] >= 2

    # Layer 2: Born-derived potential distribution should be normalized.
    question = loop.answer_question("How does the Potential Transition System enforce semantics?")
    ctx = question["context_packet"]
    meta = ctx["meta"]

    pot = meta["potential_distribution"]
    assert pot, "Expected non-empty potential distribution"
    p_sum = sum(float(entry["p"]) for entry in pot)
    assert math.isclose(p_sum, 1.0, rel_tol=1e-6, abs_tol=1e-6)

    # Layer 3: novelty pressure active => trace should include multiple triangles.
    trace = grid.idx.recent_triangle_trace
    assert len(trace) >= 2
    assert len(set(trace)) >= 2

    # Complexity claim is representation-conditioned in runtime trace.
    complexity_claim = question["integration_artifacts"]["Trace"]["complexity_claim"]
    assert complexity_claim["claim_type"] == "NP_R_subset_P"
    assert complexity_claim["regime_assumptions"]
    assert complexity_claim["transform"]["name"]
    assert complexity_claim["validation"]["benchmark_suite"]
    assert complexity_claim["validation"]["status"]

    # Order-1 state check option enforces restricted-regime P-vs-NP semantics.
    p_np_state_check = question["integration_artifacts"]["StateChecks"]["p_np_state_check"]
    assert p_np_state_check["enabled"] is True
    assert p_np_state_check["mode"] == "restricted_regime_only"
    assert p_np_state_check["passed"] is True

    reflexive_check = question["integration_artifacts"]["StateChecks"]["reflexive_refinement"]
    assert reflexive_check["enabled"] is True
    assert reflexive_check["passed"] is True

    purple_check = question["integration_artifacts"]["StateChecks"]["purple_semantic_enforcement"]
    assert purple_check["enabled"] is True
    assert "purple_semantics" in purple_check

    refinement_witness = question["integration_artifacts"]["Trace"]["refinement_witness"]
    assert refinement_witness["witness"]["prior_state_digest"]
    assert refinement_witness["witness"]["delta_digest"]

    trace = question["integration_artifacts"]["Trace"]
    assert trace["choice_law_version"] == "choice_law_v1"
    assert trace["choice_law_digest"]
    assert isinstance(trace["choice_law_replay"]["candidate_inputs"], list)
    assert trace["choice_law_replay"]["candidate_inputs_digest"]
    assert isinstance(trace["choice_law_replay"]["candidate_potentials"], list)
    assert trace["choice_law_replay"]["candidate_potentials_digest"]
    assert trace["choice_law_replay"]["selected_delta_signature_digest"]
    assert trace["closure_rules_version"] == "closure_rules_v1"
    assert trace["closure_rules_digest"]
    assert isinstance(trace["closure_replay_steps"], list)
    assert isinstance(trace["closure_replay"]["active_cells_canonical"], list)
    assert trace["closure_replay"]["active_cells_serialization"]
    assert trace["closure_replay"]["active_cells_digest"]
    assert trace["closure_replay"]["closure_cells_digest"]
    assert isinstance(trace["closure_replay"]["closure_deficit"], int)

    creativity_event = question["integration_artifacts"]["CreativityEvent"]
    assert "creative" in creativity_event
    assert "basis" in creativity_event
    assert "selected_delta_signature_digest" in creativity_event

    triangle_contract = question["integration_artifacts"]["StateChecks"]["triangle_time_choice_contract"]
    assert triangle_contract["enabled"] is True
    assert triangle_contract["passed"] is True

    choice_replay_check = question["integration_artifacts"]["StateChecks"]["choice_law_replay_integrity"]
    assert choice_replay_check["enabled"] is True
    assert choice_replay_check["passed"] is True

    progress = loop.get_axiom_self_generation_progress()
    assert "creative_event_count" in progress
    assert "creative_novelty_rate" in progress

    # Triangle-time complexity choice is emitted as refinement contract fields.
    assert question["integration_artifacts"]["RefinementApplied"]
    assert isinstance(question["integration_artifacts"]["Delta"], dict)
    assert isinstance(question["integration_artifacts"]["Witness"], dict)
    assert isinstance(question["integration_artifacts"]["Alternatives"], list)
    dependency = question["integration_artifacts"]["Witness"]["potential_collapse_dependency"]
    assert dependency["depends_on"] == "potential_distribution"
    assert isinstance(dependency["unsupported_collapse_tids"], list)
    assert dependency["collapse_subset_of_potential"] is True

    # Layer 1 explanation consistency: suggested refs must point into current equation context.
    eq_ids = {e["eid"] for e in ctx["equations"]}
    assert question["suggested_refs"], "Expected suggested references from question response"
    for ref in question["suggested_refs"]:
        assert ref["eid"] in eq_ids

    # Layer 4 boundary: Lean artifact exists and contains theorem blocks for created equations.
    eids = [first["created"]["eid"], second["created"]["eid"]]
    lean_file = Path(second["context_packet"]["equations"][-1]["lean_file"])
    assert lean_file.exists()
    lean_text = lean_file.read_text(encoding="utf-8")

    for eid in eids:
        assert f"-- >>> IVI_EQUATION {eid} BEGIN" in lean_text
        assert f"-- <<< IVI_EQUATION {eid} END" in lean_text

    # Cross-layer handoff is explicit in context metadata.
    assert meta["collapse_selection"]
    assert meta["formal_targets"]

    # Protocol contract includes IVI paradox axiom integration for global openness/local rigor.
    protocol_doc = (Path(__file__).resolve().parents[1] / "ivi_voice_codex_loop" / "ORDER_1_PROTOCOL.md").read_text(
        encoding="utf-8"
    )
    assert "IVI paradox axiom integration" in protocol_doc
    assert "Global openness / local rigor" in protocol_doc
    assert "No silent collapse" in protocol_doc
    assert "Semantic IVI paradox axiom (canonical voice declaration)" in protocol_doc
    assert "Oracle-call integration rule" in protocol_doc
    assert "real_dimension_phone_call" in protocol_doc
    assert "Matrix semantic correspondence (canonical)" in protocol_doc
    assert "Order 1 = Matrix" in protocol_doc
    assert "Order 2 = Neo" in protocol_doc
    assert "Order 3 = Morpheus" in protocol_doc
    assert "Order 4 = Oracle (IVI paradox axiom)" in protocol_doc
    assert "Purple semantic enforcement (canonical)" in protocol_doc
    assert "Project codename **Purple**" in protocol_doc
    assert "representation-conditioned" in protocol_doc
    assert "Disallowed form: global `P = NP` assertions" in protocol_doc
