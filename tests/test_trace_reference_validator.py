import pytest

from ivi_loop.ivi_simplicial_grid import (
    IVILoopController,
    IVISimplicialGrid,
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
    dependency = artifact["Witness"]["potential_collapse_dependency"]
    assert dependency["depends_on"] == "potential_distribution"
    assert dependency["collapse_subset_of_potential"] is True
    assert dependency["unsupported_collapse_tids"] == []
    assert dependency["potential_distribution_digest"]
    assert dependency["collapse_set_digest"]
    assert dependency["supported_collapse_set_digest"]
    assert "choice_sampling_seed" in dependency
    assert ok is True
    assert violations == []


@pytest.mark.order1
def test_triangle_time_choice_artifact_rejects_inconsistent_potential_collapse_dependency():
    canonical_tids = ["T_1"]
    artifact = {
        "RefinementApplied": "triangle_time_refinement_transform_v1",
        "Delta": {
            "added_triangle_tids": ["T_1"],
            "added_triangle_count": 1,
            "potential_triangle_count": 1,
            "potential_collapse_dependency": {
                "depends_on": "potential_distribution",
                "potential_count": 1,
                "collapse_count": 1,
                "supported_collapse_count": 0,
                "potential_tids_canonical": canonical_tids,
                "collapse_tids_canonical": canonical_tids,
                "supported_collapse_tids_canonical": canonical_tids,
                "potential_distribution_digest": "dd3373f4ee1aa0ef1f8f6ff5b47ca3404f96f4036e50f651f414cf5ab74f64bc",
                "collapse_set_digest": "dd3373f4ee1aa0ef1f8f6ff5b47ca3404f96f4036e50f651f414cf5ab74f64bc",
                "supported_collapse_set_digest": "dd3373f4ee1aa0ef1f8f6ff5b47ca3404f96f4036e50f651f414cf5ab74f64bc",
                "choice_sampling_seed": None,
                "unsupported_collapse_tids": ["T_1"],
                "collapse_subset_of_potential": False,
            },
        },
        "Witness": {
            "integrity_checks": {
                "has_potential_distribution": True,
                "has_collapse_selection": True,
                "has_formal_targets": True,
                "role_exchange_consistent": True,
                "potential_collapse_dependency_valid": True,
            },
            "potential_collapse_dependency": {
                "depends_on": "potential_distribution",
                "potential_count": 1,
                "collapse_count": 1,
                "supported_collapse_count": 1,
                "potential_tids_canonical": canonical_tids,
                "collapse_tids_canonical": canonical_tids,
                "supported_collapse_tids_canonical": canonical_tids,
                "potential_distribution_digest": "dd3373f4ee1aa0ef1f8f6ff5b47ca3404f96f4036e50f651f414cf5ab74f64bc",
                "collapse_set_digest": "dd3373f4ee1aa0ef1f8f6ff5b47ca3404f96f4036e50f651f414cf5ab74f64bc",
                "supported_collapse_set_digest": "dd3373f4ee1aa0ef1f8f6ff5b47ca3404f96f4036e50f651f414cf5ab74f64bc",
                "choice_sampling_seed": None,
                "unsupported_collapse_tids": ["T_1"],
                "collapse_subset_of_potential": True,
            },
            "violations": [],
        },
        "Alternatives": [],
    }

    ok, violations = validate_triangle_time_choice_artifact(artifact)

    assert ok is False
    assert "Witness.potential_collapse_dependency integrity mismatch" in violations


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


@pytest.mark.order1
def test_closure_replay_payload_is_deterministic(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "closure_replay_deterministic_repo"))
    loop = IVILoopController(grid)

    trace = {
        "potential_distribution": [{"tid": "T_1", "p": 1.0}],
        "collapse_selection": ["T_1"],
        "formal_targets": [{"eid": "E_1"}],
        "role_projection": {"subject_tids": ["T_1"], "object_tids": []},
    }
    payload_1 = loop._closure_replay_payload(trace)
    payload_2 = loop._closure_replay_payload(trace)

    assert payload_1["closure_rules_version"] == "closure_rules_v1"
    assert payload_1["closure_rules_digest"] == payload_2["closure_rules_digest"]
    assert payload_1["active_cells_canonical"] == payload_2["active_cells_canonical"]
    assert payload_1["active_cells_serialization"] == payload_2["active_cells_serialization"]
    assert payload_1["active_cells_digest"] == payload_2["active_cells_digest"]
    assert payload_1["closure_cells_digest"] == payload_2["closure_cells_digest"]
    assert payload_1["closure_deficit_digest"] == payload_2["closure_deficit_digest"]


@pytest.mark.order1
def test_closure_replay_tamper_detection_fails_integrity_check(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "closure_replay_tamper_repo"))
    loop = IVILoopController(grid)

    trace = {
        "potential_distribution": [{"tid": "T_1", "p": 1.0}],
        "collapse_selection": ["T_1"],
        "formal_targets": [{"eid": "E_1"}],
        "role_projection": {"subject_tids": ["T_1"], "object_tids": []},
    }
    replay = loop._closure_replay_payload(trace)
    trace["closure_rules_version"] = replay["closure_rules_version"]
    trace["closure_rules_digest"] = replay["closure_rules_digest"]
    trace["closure_replay"] = {
        "active_cells_digest": replay["active_cells_digest"],
        "closure_cells_digest": replay["closure_cells_digest"],
        "closure_deficit_digest": "tampered_digest",
    }

    check = loop._evaluate_closure_replay_integrity(trace)
    assert check["passed"] is False
    assert "closure_deficit_digest_mismatch" in check["violations"]


@pytest.mark.order1
def test_closure_replay_integrity_detects_noncanonical_active_digest_source(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "closure_replay_noncanonical_repo"))
    loop = IVILoopController(grid)

    trace = {
        "potential_distribution": [{"tid": "T_1", "p": 1.0}],
        "collapse_selection": ["T_1"],
        "formal_targets": [{"eid": "E_1"}],
        "role_projection": {"subject_tids": ["T_1"], "object_tids": []},
    }
    replay = loop._closure_replay_payload(trace)
    trace["closure_rules_version"] = replay["closure_rules_version"]
    trace["closure_rules_digest"] = replay["closure_rules_digest"]
    trace["closure_replay"] = {
        "active_cells_canonical": replay["active_cells_canonical"],
        "active_cells_serialization": replay["active_cells_serialization"] + " ",
        "active_cells_digest": replay["active_cells_digest"],
        "closure_cells_digest": replay["closure_cells_digest"],
        "closure_deficit_digest": replay["closure_deficit_digest"],
    }

    check = loop._evaluate_closure_replay_integrity(trace)
    assert check["passed"] is False
    assert "active_cells_digest_noncanonical_source" in check["violations"]


@pytest.mark.order1
def test_closure_rules_version_immutability_gate_rejects_unapproved_change(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "closure_rules_immutability_repo"))
    loop = IVILoopController(grid)

    trace = {
        "closure_rules_version": "closure_rules_v2",
        "closure_rules_digest": "not_approved_digest",
    }
    check = loop._evaluate_closure_rules_immutability(trace)

    assert check["enabled"] is True
    assert check["passed"] is False
    assert "closure_rules_version_not_approved" in check["violations"]
    assert "closure_rules_digest_not_approved" in check["violations"]


@pytest.mark.order1
def test_choice_law_replay_payload_is_deterministic(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "choice_law_replay_deterministic_repo"))
    loop = IVILoopController(grid)

    trace = {
        "choice_law_version": "choice_law_v1",
        "choice_law_digest": "",
        "potential_distribution": [{"tid": "T_1", "p": 0.6}, {"tid": "T_2", "p": 0.4}],
        "collapse_selection": ["T_1"],
        "formal_targets": [{"eid": "E_1"}],
        "role_projection": {"subject_tids": ["T_1"], "object_tids": ["T_2"]},
    }
    payload_1 = loop._choice_law_replay_payload(trace)
    payload_2 = loop._choice_law_replay_payload(trace)

    assert payload_1["choice_law_version"] == "choice_law_v1"
    assert payload_1["choice_law_digest"] == payload_2["choice_law_digest"]
    assert payload_1["candidate_inputs_digest"] == payload_2["candidate_inputs_digest"]
    assert payload_1["candidate_potentials_digest"] == payload_2["candidate_potentials_digest"]
    assert payload_1["selected_delta_signature_digest"] == payload_2["selected_delta_signature_digest"]


@pytest.mark.order1
def test_choice_law_replay_tamper_detection_on_candidate_feature_flip(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "choice_law_replay_tamper_repo"))
    loop = IVILoopController(grid)

    trace = {
        "potential_distribution": [{"tid": "T_1", "p": 0.6}, {"tid": "T_2", "p": 0.4}],
        "collapse_selection": ["T_1"],
        "formal_targets": [{"eid": "E_1"}],
        "role_projection": {"subject_tids": ["T_1"], "object_tids": ["T_2"]},
    }
    replay = loop._choice_law_replay_payload(trace)
    trace["choice_law_version"] = str(replay.get("choice_law_version", "choice_law_v1"))
    trace["choice_law_digest"] = str(replay.get("choice_law_digest", ""))
    tampered_inputs = list(replay.get("candidate_inputs", []))
    if tampered_inputs:
        tampered = dict(tampered_inputs[0])
        tampered["projected_deficit"] = int(tampered.get("projected_deficit", 0)) + 1
        tampered_inputs[0] = tampered
    trace["choice_law_replay"] = {
        "candidate_inputs": tampered_inputs,
        "candidate_inputs_digest": replay.get("candidate_inputs_digest", ""),
        "candidate_potentials": replay.get("candidate_potentials", []),
        "candidate_potentials_digest": replay.get("candidate_potentials_digest", ""),
        "selected_delta_signature_digest": replay.get("selected_delta_signature_digest", ""),
    }

    check = loop._evaluate_choice_law_replay_integrity(trace)
    assert check["passed"] is False
    assert "choice_law_candidate_inputs_mismatch" in check["violations"]
