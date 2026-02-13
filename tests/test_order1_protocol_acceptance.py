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
