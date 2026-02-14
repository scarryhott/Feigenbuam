import pytest

from ivi_loop.ivi_simplicial_grid import (
    build_reflexive_state_from_trace,
    reflexive_step_payload,
    build_triangle_time_choice_artifact,
    evaluate_regime_feature_tests,
    evaluate_p_np_state_check_option,
    evaluate_validation_promotion_level,
    run_reflexive_refinement_step,
    run_complexity_counterexample_search,
    validate_triangle_time_choice_artifact,
    validate_complexity_claim_schema,
    validate_role_exchange_trace_consistency,
    validate_trace_backed_references,
)


@pytest.mark.order1
def test_validate_trace_backed_references_accepts_trace_grounded_refs():
    trace = {
        "formal_targets": [
            {"eid": "E_alpha", "lean_name": "alpha", "lean_file": "A.lean"},
            {"eid": "E_beta", "lean_name": "beta", "lean_file": "B.lean"},
        ]
    }
    refs = [
        {"eid": "E_alpha", "statement": "s1"},
        {"eid": "E_beta", "statement": "s2"},
    ]

    ok, violations = validate_trace_backed_references(trace, refs)

    assert ok is True
    assert violations == []


@pytest.mark.order1
def test_validate_trace_backed_references_rejects_untraceable_refs():
    trace = {
        "formal_targets": [
            {"eid": "E_alpha", "lean_name": "alpha", "lean_file": "A.lean"},
        ]
    }
    refs = [
        {"eid": "E_alpha", "statement": "grounded"},
        {"eid": "E_unknown", "statement": "not grounded"},
        {"statement": "missing eid"},
    ]

    ok, violations = validate_trace_backed_references(trace, refs)

    assert ok is False
    assert len(violations) == 2
    assert any("E_unknown" in v for v in violations)
    assert any("missing eid" in v for v in violations)


@pytest.mark.order1
def test_validate_role_exchange_trace_consistency_accepts_valid_projection():
    trace = {
        "potential_distribution": [
            {"tid": "T_1", "p": 0.6},
            {"tid": "T_2", "p": 0.4},
        ],
        "collapse_selection": ["T_1", "T_2"],
        "role_projection": {
            "subject_tids": ["T_1"],
            "object_tids": ["T_2"],
        },
    }

    ok, violations = validate_role_exchange_trace_consistency(trace)

    assert ok is True
    assert violations == []


@pytest.mark.order1
def test_validate_role_exchange_trace_consistency_rejects_invalid_projection():
    trace = {
        "potential_distribution": [
            {"tid": "T_1", "p": 0.7},
            {"tid": "T_2", "p": 0.3},
        ],
        "collapse_selection": ["T_1", "T_2"],
        "role_projection": {
            "subject_tids": ["T_1", "T_2"],
            "object_tids": [],
        },
    }

    ok, violations = validate_role_exchange_trace_consistency(trace)

    assert ok is False
    assert any("must populate both subject_tids and object_tids" in v for v in violations)


@pytest.mark.order1
def test_validate_complexity_claim_schema_accepts_restricted_claim():
    claim = {
        "claim_type": "NP_R_subset_P",
        "regime_assumptions": {
            "constraints": ["triangle_time_structured_representation"],
            "instance_family": "ivi_triangle_time_v1",
            "feature_tests": ["has_potential_distribution"],
        },
        "transform": {
            "name": "triangle_time_refinement_transform_v1",
            "impl_ref": "ivi_loop.ivi_simplicial_grid.IVILoopController._build_integration_artifacts",
            "digest": "abc123",
        },
        "validation": {"level": "smoke", "benchmark_suite": "ivi_np_structured_v1", "status": "pending"},
    }

    ok, violations = validate_complexity_claim_schema(claim)

    assert ok is True
    assert violations == []


@pytest.mark.order1
def test_validate_complexity_claim_schema_rejects_global_claim_and_missing_fields():
    claim = {
        "claim_type": "P=NP",
        "regime_assumptions": {},
        "transform": {},
        "validation": {"level": "", "benchmark_suite": "", "status": ""},
    }

    ok, violations = validate_complexity_claim_schema(claim)

    assert ok is False
    assert any("global P=NP" in v for v in violations)
    assert any("regime_assumptions.constraints" in v for v in violations)
    assert any("regime_assumptions.instance_family" in v for v in violations)
    assert any("regime_assumptions.feature_tests" in v for v in violations)
    assert any("transform.name" in v for v in violations)
    assert any("transform.impl_ref" in v for v in violations)
    assert any("transform.digest" in v for v in violations)
    assert any("validation.level" in v for v in violations)
    assert any("validation.benchmark_suite" in v for v in violations)
    assert any("validation.status" in v for v in violations)


@pytest.mark.order1
def test_p_np_state_check_option_accepts_restricted_regime_claim():
    check = evaluate_p_np_state_check_option({"claim_type": "NP_R_subset_P"})

    assert check["name"] == "p_np_state_check"
    assert check["enabled"] is True
    assert check["passed"] is True
    assert check["mode"] == "restricted_regime_only"


@pytest.mark.order1
def test_p_np_state_check_option_rejects_global_claim():
    check = evaluate_p_np_state_check_option({"claim_type": "P=NP"})

    assert check["name"] == "p_np_state_check"
    assert check["enabled"] is True
    assert check["passed"] is False
    assert "Global P=NP claim rejected" in check["detail"]


@pytest.mark.order1
def test_validation_promotion_disallows_downgrade():
    check = evaluate_validation_promotion_level(current_level="smoke", previous_level="benchmark")
    assert check["passed"] is False
    assert "downgrade" in check["detail"]


@pytest.mark.order1
def test_regime_feature_tests_and_counterexample_search_are_callable():
    claim = {
        "claim_type": "NP_R_subset_P",
        "regime_assumptions": {
            "constraints": ["trace_backed_refinement"],
            "instance_family": "ivi_triangle_time_v1",
            "feature_tests": ["has_potential_distribution", "has_collapse_selection", "has_formal_targets"],
        },
    }
    trace = {
        "potential_distribution": [{"tid": "T_1", "p": 1.0}],
        "collapse_selection": ["T_1"],
        "formal_targets": [{"eid": "E_1"}],
    }

    regime_check = evaluate_regime_feature_tests(trace, claim)
    cx_check = run_complexity_counterexample_search(trace, claim)

    assert regime_check["passed"] is True
    assert cx_check["enabled"] is True


@pytest.mark.order1
def test_triangle_time_choice_artifact_build_and_validate():
    trace = {
        "potential_distribution": [
            {"tid": "T_1", "p": 0.7},
            {"tid": "T_2", "p": 0.3},
        ],
        "collapse_selection": ["T_1"],
        "formal_targets": [{"eid": "E_1"}],
        "role_projection": {
            "subject_tids": ["T_1"],
            "object_tids": [],
        },
    }

    artifact = build_triangle_time_choice_artifact(trace)
    ok, violations = validate_triangle_time_choice_artifact(artifact)

    assert artifact["RefinementApplied"]
    assert isinstance(artifact["Delta"], dict)
    assert isinstance(artifact["Witness"], dict)
    assert isinstance(artifact["Alternatives"], list)
    assert ok is True
    assert violations == []


@pytest.mark.order1
def test_reflexive_refinement_step_emits_witness_payload():
    trace = {
        "collapse_selection": ["T_1", "T_2"],
        "formal_targets": [{"eid": "E_1"}, {"eid": "E_2"}],
        "potential_distribution": [{"tid": "T_1", "p": 0.6}, {"tid": "T_2", "p": 0.4}],
    }

    state = build_reflexive_state_from_trace(trace)
    step = run_reflexive_refinement_step(state)
    payload = reflexive_step_payload(step)

    assert payload
    assert payload["witness"]["prior_state_digest"]
    assert payload["witness"]["delta_digest"]
    assert "ok" in payload
    assert "delta" in payload
