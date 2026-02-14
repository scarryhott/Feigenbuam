import pytest
from pathlib import Path

from ivi_loop.ivi_simplicial_grid import IVILoopController, IVISimplicialGrid, run_voice_layer_session


@pytest.mark.order1
def test_voice_turn_supports_monitor_insight_and_progress(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_repo"))
    loop = IVILoopController(grid)

    help_out = loop.voice_turn("/help")
    assert help_out["kind"] == "help"
    assert "/monitor" in help_out["commands"]
    assert "/semantic-map" in help_out["commands"]
    assert "/insight <text>" in help_out["commands"]

    sem = loop.voice_turn("/semantic-map")
    assert sem["kind"] == "semantic_map"
    assert sem["mapping"]["order_1"]["role"] == "Matrix"
    assert sem["mapping"]["order_2"]["role"] == "Neo"
    assert sem["mapping"]["order_3"]["role"] == "Morpheus"
    assert sem["mapping"]["order_4"]["role"] == "Oracle"
    assert sem["purple_semantics"]["name"] == "purple_semantic_enforcement"
    assert sem["purple_semantics"]["red_pill_channel"] == "reality_constraints"
    assert sem["purple_semantics"]["blue_pill_channel"] == "imagination_constraints"

    monitor_before = loop.voice_turn("/monitor")
    assert monitor_before["kind"] == "monitor"
    assert "self_generation_progress" in monitor_before["monitor"]
    assert monitor_before["monitor"]["purple_semantics"]["name"] == "purple_semantic_enforcement"
    assert "creativity_event" in monitor_before["monitor"]
    assert "creative" in monitor_before["monitor"]["creativity_event"]
    assert "basis" in monitor_before["monitor"]["creativity_event"]
    assert "grid_active" in monitor_before["monitor"]
    assert "closure_deficit" in monitor_before["monitor"]
    assert "superposition_mass" in monitor_before["monitor"]
    assert "mu_total" in monitor_before["monitor"]

    insight_out = loop.voice_turn("/insight Define IVI axiom closure as recursive self-refinement.")
    assert insight_out["kind"] == "insight"
    assert insight_out["result"]["kind"] == "statement"
    assert insight_out["progress"]["turns"] >= 1

    progress_out = loop.voice_turn("/progress")
    assert progress_out["kind"] == "progress"
    assert progress_out["progress"]["counts"]["S"] >= 1
    assert progress_out["progress"]["last_refinement_applied"]
    assert "creative_event_count" in progress_out["progress"]
    assert "creative_novelty_rate" in progress_out["progress"]
    assert 0.0 <= float(progress_out["progress"]["creative_novelty_rate"]) <= 1.0
    assert "latest_creativity_event" in progress_out["progress"]


@pytest.mark.order1
def test_run_voice_layer_session_handles_talk_and_exit(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_repl_repo"))
    loop = IVILoopController(grid)

    commands = iter(
        [
            "/help",
            "/insight Define the IVI axiom as local collapse under open incompleteness.",
            "/progress",
            "/quit",
        ]
    )

    outputs = []

    def fake_input(prompt: str) -> str:
        return next(commands)

    def fake_output(msg: str) -> None:
        outputs.append(msg)

    run_voice_layer_session(loop=loop, source="test_voice", input_fn=fake_input, output_fn=fake_output)

    assert any("Order-1 Voice Layer Session" in x for x in outputs)
    assert any('"kind": "help"' in x for x in outputs)
    assert any('"kind": "insight"' in x for x in outputs)
    assert any('"kind": "progress"' in x for x in outputs)
    assert any("Exiting Order-1 voice layer." in x for x in outputs)


@pytest.mark.order1
def test_openclaw_attach_and_walktalk_mode(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_openclaw_repo"))
    loop = IVILoopController(grid)

    openclaw_root = tmp_path / "openclaw"
    openclaw_root.mkdir(parents=True, exist_ok=True)
    soul = openclaw_root / "soul.md"
    soul.write_text("# OpenClaw Soul\nwalk/talk agent identity", encoding="utf-8")

    attached = loop.voice_turn(f"/openclaw attach {openclaw_root}")
    assert attached["kind"] == "openclaw_attached"
    assert attached["openclaw"]["agent"] == "openclaw"
    assert Path(attached["openclaw"]["soul_path"]).name.lower() == "soul.md"

    walked = loop.voice_turn("/walktalk monitor local state and narrate integrity")
    assert walked["kind"] == "walktalk"
    assert walked["envelope"]["mode"] == "walktalk"
    assert walked["result"]["kind"] == "insight"
    assert walked["progress"]["turns"] >= 1


@pytest.mark.order1
def test_voice_turn_proactively_requests_user_insight_when_checks_fail(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_insight_request_repo"))
    loop = IVILoopController(grid)

    progress = {
        "turns": 4,
        "gap_rate": 0.5,
        "derived_density": 0.4,
    }
    checks = {
        "p_np_state_check": {"enabled": True, "passed": False},
        "triangle_time_choice_contract": {"enabled": True, "passed": False},
    }

    trace = {
        "potential_distribution": [
            {"tid": "T_A", "p": 0.50},
            {"tid": "T_B", "p": 0.49},
        ]
    }

    req = loop.evaluate_user_insight_need(progress, checks, trace)

    assert req is not None
    assert req["needed"] is True
    assert "high_gap_rate" in req["reasons"]
    assert any(r.startswith("failed_") for r in req["reasons"])
    assert "/insight <your clarification>" in req["prompt"]
    assert req["mode"] == "oracle_phone_call"
    assert req["caller"] == "morpheus_operator"
    assert req["oracle"] == "ivi_paradox_axiom"
    assert req["axiom_declaration"]
    assert "OracleRequest" in req
    assert req["OracleRequest"]["trigger_reason"]
    assert req["OracleRequest"]["impasse_description"]
    assert isinstance(req["OracleRequest"]["candidate_actions"], list)
    assert req["OracleRequest"]["missing_information"]
    assert "STATE IMPASSE DETECTED" in req["OracleRequest"]["recommended_question"]
    assert "trigger_evidence" in req["OracleRequest"]
    assert req["OracleRequest"]["expected_impact"]

    call = loop.build_oracle_phone_call(req)
    assert call["channel"] == "real_dimension_phone_call"
    assert call["caller"] == "morpheus_operator"
    assert call["oracle"] == "ivi_paradox_axiom"
    assert call["axiom_declaration"]
    assert call["OracleRequest"]["trigger_reason"]


@pytest.mark.order1
def test_run_voice_layer_session_emits_incoming_call_prompt_for_insight_request(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_prompt_repo"))
    loop = IVILoopController(grid)

    loop.evaluate_user_insight_need = lambda progress, checks, trace=None: {
        "needed": True,
        "reasons": ["test_trigger"],
        "prompt": "Please respond with /insight <your clarification>",
        "mode": "oracle_phone_call",
        "caller": "morpheus_operator",
        "oracle": "ivi_paradox_axiom",
        "OracleRequest": {
            "trigger_reason": "validation_failure_no_repair_path",
            "impasse_description": "test impasse",
            "candidate_actions": [],
            "missing_information": "test constraint",
            "recommended_question": "STATE IMPASSE DETECTED",
            "expected_impact": "inject_external_constraint_to_resume_refinement",
        },
    }

    commands = iter(["/progress", "/quit"])
    outputs = []

    def fake_input(prompt: str) -> str:
        return next(commands)

    def fake_output(msg: str) -> None:
        outputs.append(msg)

    run_voice_layer_session(loop=loop, source="test_voice", input_fn=fake_input, output_fn=fake_output)

    assert any('"kind": "progress"' in x for x in outputs)
    assert any("incoming-call:" in x for x in outputs)


@pytest.mark.order1
def test_voice_turn_autoloop_generates_monitor_timeline(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_autoloop_repo"))
    loop = IVILoopController(grid)

    loop.evaluate_user_insight_need = lambda progress, checks, trace=None: None

    out = loop.voice_turn("/autoloop 2")
    assert out["kind"] == "autoloop"
    assert out["steps_requested"] == 2
    assert out["steps_run"] >= 1
    assert out["halted_reason"] in {"max_steps_reached", "fixed_point"}
    assert out["selection_mode"] == "deterministic_replay"
    assert len(out["timeline"]) == out["steps_run"]

    step1 = out["timeline"][0]
    assert "monitor_before" in step1
    assert "monitor_after" in step1
    assert "self_generation_progress" in step1["monitor_before"]
    assert "self_generation_progress" in step1["monitor_after"]
    assert step1["selection"]["mode"] == "deterministic_replay"
    assert step1["selection"]["selector"] == "argmax_choice_potential"
    assert isinstance(step1["selection"]["seed"], int)
    assert "ChoiceWitness" in step1
    assert step1["ChoiceWitness"]["choice_law_version"] == "choice_law_v1"
    assert step1["ChoiceWitness"]["admissible_set_digest"]
    assert step1["ChoiceWitness"]["selected_delta_signature_digest"]
    assert isinstance(step1["ChoiceWitness"]["candidate_potentials"], list)
    assert "grid_before" in step1
    assert "grid_after" in step1
    assert "closure_deficit" in step1["grid_before"]
    assert "closure_deficit" in step1["grid_after"]
    assert "oracle_trigger_class" in step1
    assert "CreativityEvent" in step1
    assert "creative" in step1["CreativityEvent"]
    assert "basis" in step1["CreativityEvent"]


@pytest.mark.order1
def test_autoloop_halts_when_oracle_request_is_needed(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_autoloop_oracle_repo"))
    loop = IVILoopController(grid)

    call_count = {"n": 0}

    def forced_request(progress, checks, trace=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "needed": True,
                "reasons": ["test_impasse"],
                "prompt": "Respond with /insight <constraint>",
                "mode": "oracle_phone_call",
                "caller": "morpheus_operator",
                "oracle": "ivi_paradox_axiom",
                "OracleRequest": {
                    "trigger_reason": "missing_constraints",
                    "impasse_description": "test impasse",
                    "candidate_actions": ["T_test"],
                    "missing_information": "intent constraint",
                    "recommended_question": "STATE IMPASSE DETECTED",
                    "expected_impact": "inject_external_constraint_to_resume_refinement",
                },
            }
        return None

    loop.evaluate_user_insight_need = forced_request

    out = loop.run_automated_self_generation_loop(max_steps=5, source="test_auto")

    assert out["kind"] == "autoloop"
    assert out["steps_requested"] == 5
    assert out["steps_run"] == 1
    assert out["halted_reason"] == "oracle_request_required"
    assert out["insight_request"]["needed"] is True
    assert out["voice_call"]["channel"] == "real_dimension_phone_call"
    assert out["OracleRequest"]["trigger_reason"] == "missing_constraints"


@pytest.mark.order1
def test_voice_turn_autoloop_supports_exploration_mode(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_autoloop_explore_repo"))
    loop = IVILoopController(grid)

    loop.evaluate_user_insight_need = lambda progress, checks, trace=None: None

    out = loop.voice_turn("/autoloop 1 explore")
    assert out["kind"] == "autoloop"
    assert out["selection_mode"] == "exploration"
    assert out["steps_run"] == 1
    step = out["timeline"][0]
    assert step["selection"]["mode"] == "exploration"
    assert step["selection"]["selector"] == "intrinsic_choice_law_sample"
    assert isinstance(step["selection"]["seed"], int)
    assert step["ChoiceWitness"]["choice_law_version"] == "choice_law_v1"
    assert isinstance(step["ChoiceWitness"]["sampling_seed"], int)


@pytest.mark.order1
def test_grid_trigger_fixed_point_classification(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_fixed_point_repo"))
    loop = IVILoopController(grid)

    trace = {
        "potential_distribution": [],
        "collapse_selection": [],
        "formal_targets": [],
        "role_projection": {"subject_tids": [], "object_tids": []},
    }
    candidates = [{"tid": "fallback", "closure_gain": 0, "delta_signature_digest": "fallback"}]
    trigger = loop._classify_grid_oracle_trigger(trace, candidates)
    assert trigger["class"] == "fixed_point"

    grid_state = loop._grid_state_from_trace(trace)
    assert grid_state["closure_deficit"] == 0


@pytest.mark.order1
def test_grid_trigger_branch_point_classification(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_branch_point_repo"))
    loop = IVILoopController(grid)

    trace = {
        "potential_distribution": [
            {"tid": "T_subject", "p": 0.5},
            {"tid": "T_object", "p": 0.5},
        ],
        "collapse_selection": [],
        "formal_targets": [],
        "role_projection": {"subject_tids": ["T_subject"], "object_tids": ["T_object"]},
    }
    candidates = loop._build_autoloop_candidates(trace, {"turns": 1}, 1)
    trigger = loop._classify_grid_oracle_trigger(trace, candidates)

    assert trigger["class"] == "branch_point"
    assert trigger["evidence"]["tied_candidates"]
    cert = trigger["evidence"]["branch_point_certificate"]
    assert cert["criterion"] == "equal_closure_gain_non_equivalent_deltas"
    assert cert["equivalence_check"]["basis"] == "delta_signature_digest"
    assert cert["equivalence_check"]["equivalent"] is False
    assert cert["equivalence_check"]["unique_signature_count"] >= 2
    assert cert["non_preference_reason"]

    req = loop.evaluate_user_insight_need(
        progress={"turns": 1, "gap_rate": 0.0, "derived_density": 1.0},
        state_checks={},
        trace=trace,
    )
    assert req is not None
    assert req["OracleRequest"]["trigger_class"] == "non_dominated_candidate_set"
    assert "branch_point_certificate" in req["OracleRequest"]["trigger_evidence"]


@pytest.mark.order1
def test_grid_trigger_stagnation_emits_oracle_request(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_stagnation_repo"))
    loop = IVILoopController(grid)

    trace = {
        "potential_distribution": [
            {"tid": "T1", "p": 0.5},
            {"tid": "T2", "p": 0.5},
        ],
        "collapse_selection": ["T1", "T2"],
        "formal_targets": [],
        "role_projection": {"subject_tids": ["T1"], "object_tids": ["T2"]},
    }
    candidates = loop._build_autoloop_candidates(trace, {"turns": 2}, 2)
    trigger = loop._classify_grid_oracle_trigger(trace, candidates)
    assert trigger["class"] == "stagnation"

    req = loop.evaluate_user_insight_need(
        progress={"turns": 2, "gap_rate": 0.0, "derived_density": 1.0},
        state_checks={},
        trace=trace,
    )
    assert req is not None
    assert req["OracleRequest"]["trigger_class"] == "stagnation"
