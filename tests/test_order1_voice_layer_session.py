import pytest
import time
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
    trace = insight_out["result"]["integration_artifacts"]["Trace"]
    assert "order_relation" in trace
    assert trace["order_relation"]["mode"] == "continuous_triad_v1"
    assert trace["order_relation"]["order_1_projection"]["class_label"] == trace["class_label"]
    assert "digest" in trace["order_relation"]

    progress_out = loop.voice_turn("/progress")
    assert progress_out["kind"] == "progress"
    assert progress_out["progress"]["counts"]["S"] >= 1
    assert progress_out["progress"]["last_refinement_applied"]
    assert "creative_event_count" in progress_out["progress"]
    assert "creative_novelty_rate" in progress_out["progress"]
    assert 0.0 <= float(progress_out["progress"]["creative_novelty_rate"]) <= 1.0
    assert "latest_creativity_event" in progress_out["progress"]
    assert "class_regime_distribution" in progress_out["progress"]
    class_dist = progress_out["progress"]["class_regime_distribution"]
    assert "alpha_dominant" in class_dist
    assert "beta_dominant" in class_dist


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
    mem = openclaw_root / "memory_notes.md"
    mem.write_text("Order-1 Protocol memory anchor for personalized routing", encoding="utf-8")

    attached = loop.voice_turn(f"/openclaw attach {openclaw_root}")
    assert attached["kind"] == "openclaw_attached"
    assert attached["openclaw"]["agent"] == "openclaw"
    assert Path(attached["openclaw"]["soul_path"]).name.lower() == "soul.md"
    assert attached["voice_mode"] == "integrated"
    assert attached["voice_priority_model"] == "openclaw"
    assert attached["foundation_model"] == "purple_potential_noncollapsing_loop"
    assert attached["semantic_policy"]["principle"]["name"] == "ivi_semantic_skill_policy_v1"
    assert attached["semantic_policy"]["skills_are_semantic"] is True
    assert attached["semantic_policy"]["mcps_are_backends"] is True
    assert "voice_personalization" in attached["semantic_policy"]["enabled_skills"]
    assert "mcp.voice.persona" in attached["semantic_policy"]["skill_backends"]["voice_personalization"]
    assert attached["full_access"] is True
    assert "SYS_AUTOMATION" in attached["permissions_granted"]

    profile = loop.voice_turn("/openclaw profile")
    assert profile["kind"] == "openclaw_profile"
    assert profile["profile"]["enabled"] is True
    assert profile["profile"]["voice_priority_model"] == "openclaw"
    assert profile["profile"]["foundation_model"] == "purple_potential_noncollapsing_loop"
    assert profile["profile"]["semantic_policy"]["principle"]["name"] == "ivi_semantic_skill_policy_v1"
    assert profile["profile"]["openclaw"]["voice_profile"]["anchor"]
    assert profile["profile"]["openclaw"]["voice_profile"]["memory_source_count"] >= 1
    assert profile["profile"]["openclaw"]["memory_profile"]["enabled"] is True

    switched = loop.voice_turn("/openclaw mode passthrough")
    assert switched["kind"] == "openclaw_mode"
    assert switched["voice_mode"] == "integrated"
    assert "prioritized as voice personalization model" in switched["detail"]
    switched_back = loop.voice_turn("/openclaw mode integrated")
    assert switched_back["voice_mode"] == "integrated"

    walked = loop.voice_turn("/walktalk monitor local state and narrate integrity")
    assert walked["kind"] == "walktalk"
    assert walked["envelope"]["mode"] == "walktalk"
    assert walked["result"]["kind"] == "insight"
    assert walked["voice_personalization"]["enabled"] is True
    assert walked["progress"]["turns"] >= 1

    walked_question = loop.voice_turn("/walktalk question: what equations are active?")
    assert walked_question["kind"] == "walktalk"
    assert walked_question["route"] == "question_projection"
    assert walked_question["result"]["kind"] == "question"

    q = loop.voice_turn("What do we know about closure deficit?")
    assert q["kind"] == "question"
    assert q["voice_personalization"]["enabled"] is True
    assert "openclaw_voice_personalization" in q["integration_artifacts"]["Trace"]
    assert "triangle_time_integral" in q["integration_artifacts"]["Trace"]
    assert "purple_semantic_passed" in q["integration_artifacts"]["Trace"]
    assert q["active_order_mode"]
    assert q["integration_artifacts"]["Trace"]["active_order_mode"] == q["active_order_mode"]
    assert "order_mode_selection" in q["integration_artifacts"]["Trace"]
    assert q["integration_artifacts"]["Trace"]["ai_hierarchy"]["voice_priority_model"] == "openclaw"
    assert q["integration_artifacts"]["Trace"]["ai_hierarchy"]["foundation_model"] == "purple_potential_noncollapsing_loop"
    assert q["integration_artifacts"]["Trace"]["ai_hierarchy"]["foundation_controls_order_modes"] is True
    assert q["integration_artifacts"]["Trace"]["ai_hierarchy"]["semantic_policy"]["skills_are_semantic"] is True
    assert q["integration_artifacts"]["Trace"]["ai_hierarchy"]["semantic_policy"]["mcps_are_backends"] is True

    s = loop.voice_turn("This is a voice statement for OpenClaw integrated mode")
    assert s["kind"] == "statement"
    assert s["voice_personalization"]["enabled"] is True
    trace = s["integration_artifacts"]["Trace"]
    assert trace["openclaw_voice_personalization"]["enabled"] is True
    assert trace["openclaw_voice_personalization_digest"]
    assert trace["active_order_mode"] == s["active_order_mode"]
    assert trace["max_order_mode"]

    sync = loop.voice_turn(f"/openclaw sync-run {openclaw_root} :: question: summarize protocol memory")
    assert sync["kind"] == "openclaw_sync_run"
    assert sync["attached"]["openclaw"]["voice_profile"]["memory_source_count"] >= 1
    assert sync["walktalk"]["kind"] == "walktalk"
    assert sync["walktalk"]["result"]["kind"] == "question"

    orch_full = loop.voice_turn("/orchestrator full-access on")
    assert orch_full["kind"] == "orchestrator_full_access"
    assert orch_full["full_access"] is True
    assert "SYS_AUTOMATION" in orch_full["permissions_granted"]

    orch_proactive = loop.voice_turn("/orchestrator proactive on")
    assert orch_proactive["kind"] == "orchestrator_proactive"
    assert orch_proactive["proactive_enabled"] is True

    orch_continuous = loop.voice_turn("/orchestrator continuous on")
    assert orch_continuous["kind"] == "orchestrator_continuous"
    assert orch_continuous["continuous_enabled"] is True

    orch_eternal = loop.voice_turn("/orchestrator eternal on")
    assert orch_eternal["kind"] == "orchestrator_eternal"
    assert orch_eternal["proactive_enabled"] is True
    assert orch_eternal["continuous_enabled"] is True

    scheduled = loop.voice_turn("/orchestrator schedule maintain closure and summarize status")
    assert scheduled["kind"] == "orchestrator_schedule"
    assert scheduled["scheduled_routine_count"] >= 1

    tick = loop.voice_turn("/orchestrator tick")
    assert tick["kind"] == "orchestrator_tick"
    assert len(tick["executed"]) >= 1
    assert tick["status"]["proactive_enabled"] is True

    q2 = loop.voice_turn("What is the active orchestration mode now?")
    assert q2["active_order_mode"] in {"order_3_constrained_write", "order_4_bounded_autonomy"}
    assert "orchestrator_auto_tick" in q2
    assert q2["orchestrator_auto_tick"]["kind"] == "orchestrator_tick"
    assert len(q2["orchestrator_auto_tick"]["executed"]) >= 1

    daemon_on = loop.voice_turn("/orchestrator daemon on 0.1")
    assert daemon_on["kind"] == "orchestrator_daemon"
    assert daemon_on["daemon_enabled"] is True
    assert daemon_on["daemon_running"] is True

    time.sleep(0.25)
    daemon_status = loop.voice_turn("/orchestrator status")
    assert daemon_status["daemon_tick_count"] >= 1
    assert "triangle_time_integral" in daemon_status
    assert "purple_semantic_passed" in daemon_status
    assert daemon_status["voice_priority_model"] == "openclaw"
    assert daemon_status["foundation_model"] == "purple_potential_noncollapsing_loop"
    assert daemon_status["semantic_policy"]["principle"]["name"] == "ivi_semantic_skill_policy_v1"
    assert "bounded_autonomy" in daemon_status["semantic_policy"]["enabled_skills"]

    loop._purple_semantic_passed = False
    gated_tick = loop.voice_turn("/orchestrator tick")
    assert gated_tick["kind"] == "orchestrator_tick"
    assert gated_tick["executed"] == []
    assert gated_tick["detail"] == "purple_or_triangle_time_integral_gate_failed"
    assert gated_tick["autonomy_gate"]["allowed"] is False

    daemon_off = loop.voice_turn("/orchestrator daemon off")
    assert daemon_off["kind"] == "orchestrator_daemon"
    assert daemon_off["daemon_enabled"] is False


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
    assert req["OracleRequest"]["question_template_id"]
    assert req["OracleRequest"]["oracle_template_version"]
    assert req["OracleRequest"]["oracle_template_digest"]
    assert req["OracleRequest"]["oracle_template_inputs_digest"]
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
    assert out["triangle_time_mode"] == "continuous_triad_v1"
    assert len(out["timeline"]) == out["steps_run"]

    step1 = out["timeline"][0]
    assert "monitor_before" in step1
    assert "monitor_after" in step1
    assert "self_generation_progress" in step1["monitor_before"]
    assert "self_generation_progress" in step1["monitor_after"]
    assert step1["selection"]["mode"] == "deterministic_replay"
    assert step1["selection"]["selector"] == "least_action_argmin"
    assert isinstance(step1["selection"]["seed"], int)
    assert "least_action" in step1["selection"]
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
    assert step1["triangle_time_step"]["mode"] == "continuous_triad_v1"
    assert step1["triangle_time_step"]["index"] == 1
    assert step1["alpha_beta"]["mode"] == "continuous_triad_v1"
    assert 0.0 <= float(step1["alpha_beta"]["alpha"]) <= 1.0
    assert 0.0 <= float(step1["alpha_beta"]["beta"]) <= 1.0
    assert step1["alpha_beta"]["digest"]
    assert step1["relift_conditioning"]["mode"] == "continuous_triad_v1"
    assert step1["relift_conditioning"]["conditioning_mode"] in {
        "bias_candidates",
        "reweight_potentials",
        "identity",
    }
    assert step1["relift_conditioning_mode"] in {
        "bias_candidates",
        "reweight_potentials",
        "identity",
    }
    assert int(step1["k_collapse"]) >= 1
    assert isinstance(step1["class_label"], str)
    assert "ivi_invariant" in step1
    assert step1["ivi_invariant"]["version"] == "ivi_invariant_v1"
    assert isinstance(step1["ivi_invariant_value"], float)
    assert step1["relift_conditioning"]["conditioning_digest"]
    assert "order_relation" in step1
    assert step1["order_relation"]["mode"] == "continuous_triad_v1"
    assert step1["order_relation"]["order_coupling"]["k_collapse"] >= 1
    assert step1["order_relation"]["order_4_boundary"]["trigger_class"] == step1["oracle_trigger_class"]["class"]


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
    assert out["triangle_time_mode"] == "continuous_triad_v1"
    assert out["steps_run"] == 1
    step = out["timeline"][0]
    assert step["selection"]["mode"] == "exploration"
    assert step["selection"]["selector"] == "least_action_boltzmann_sample"
    assert isinstance(step["selection"]["seed"], int)
    assert "least_action" in step["selection"]
    assert step["ChoiceWitness"]["choice_law_version"] == "choice_law_v1"
    assert isinstance(step["ChoiceWitness"]["sampling_seed"], int)
    assert step["triangle_time_step"]["mode"] == "continuous_triad_v1"
    assert step["alpha_beta"]["digest"]
    assert step["relift_conditioning"]["used_collapse_tids_digest"]


@pytest.mark.order1
def test_autoloop_supports_forced_alpha_beta_and_seed_override(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_forced_regime_repo"))
    loop = IVILoopController(grid)

    loop.evaluate_user_insight_need = lambda progress, checks, trace=None: None
    loop.add_statement_and_loop("seed setup for forced regime", source="test_seed")

    forced = {"alpha": 0.9, "beta": 0.1}
    out = loop.run_automated_self_generation_loop(
        max_steps=1,
        source="test_forced",
        selection_mode="deterministic_replay",
        forced_alpha_beta=forced,
        seed_override=7,
    )

    assert out["forced_alpha_beta"] is not None
    assert out["seed_override"] == 7
    step = out["timeline"][0]
    assert float(step["alpha_beta"]["alpha"]) > float(step["alpha_beta"]["beta"])
    assert step["alpha_beta"].get("source") == "forced_override"
    assert step["selection"]["seed"] is not None


@pytest.mark.order1
def test_relift_conditioning_changes_choice_law_candidate_inputs_digest(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_relift_causality_repo"))
    loop = IVILoopController(grid)

    alpha_beta = {"alpha": 0.4, "beta": 0.6}
    selected = {"tid": "T_A"}
    trace_a = {
        "potential_distribution": [{"tid": "T_A", "p": 0.5}, {"tid": "T_B", "p": 0.5}],
        "collapse_selection": ["T_A"],
    }
    trace_b = {
        "potential_distribution": [{"tid": "T_A", "p": 0.5}, {"tid": "T_B", "p": 0.5}],
        "collapse_selection": ["T_B"],
    }

    relift_a = loop._build_relift_conditioning(trace_a, selected, alpha_beta)
    relift_b = loop._build_relift_conditioning(trace_b, selected, alpha_beta)
    assert relift_a["conditioning_digest"] != relift_b["conditioning_digest"]

    loop._last_relift_conditioning = relift_a
    out_a = loop.add_statement_and_loop("relift causality probe A", source="test_relift_a")
    replay_a = out_a["integration_artifacts"]["Trace"]["choice_law_replay"]
    trace_a_out = out_a["integration_artifacts"]["Trace"]
    digest_a = replay_a["candidate_inputs_digest"]

    loop._last_relift_conditioning = relift_b
    out_b = loop.add_statement_and_loop("relift causality probe B", source="test_relift_b")
    replay_b = out_b["integration_artifacts"]["Trace"]["choice_law_replay"]
    trace_b_out = out_b["integration_artifacts"]["Trace"]
    digest_b = replay_b["candidate_inputs_digest"]

    assert replay_a["relift_conditioning_digest"] == relift_a["conditioning_digest"]
    assert replay_b["relift_conditioning_digest"] == relift_b["conditioning_digest"]
    assert trace_a_out["relift_conditioning_mode"] in {"bias_candidates", "reweight_potentials", "identity"}
    assert trace_b_out["relift_conditioning_mode"] in {"bias_candidates", "reweight_potentials", "identity"}
    assert int(trace_a_out["k_collapse"]) >= 1
    assert int(trace_b_out["k_collapse"]) >= 1
    assert isinstance(trace_a_out["class_label"], str) and trace_a_out["class_label"]
    assert isinstance(trace_b_out["class_label"], str) and trace_b_out["class_label"]
    assert trace_a_out["class_digest"] == trace_a_out["class_digest_potential"]
    assert trace_b_out["class_digest"] == trace_b_out["class_digest_potential"]
    assert trace_a_out["class_digest_actuated"]
    assert trace_b_out["class_digest_actuated"]
    assert trace_a_out["class_features_potential"] == trace_a_out["class_features"]
    assert trace_b_out["class_features_potential"] == trace_b_out["class_features"]
    assert digest_a != digest_b


@pytest.mark.order1
def test_regime_ab_experiment_is_reproducible_with_seed_override(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_regime_ab_repo"))
    loop = IVILoopController(grid)
    loop.evaluate_user_insight_need = lambda progress, checks, trace=None: None

    loop.add_statement_and_loop("regime harness baseline", source="test_regime_baseline")

    out1 = loop.run_regime_ab_experiment(max_steps=2, seed_override=11)
    out2 = loop.run_regime_ab_experiment(max_steps=2, seed_override=11)

    assert out1["kind"] == "regime_ab_experiment"
    assert out1["seed_override"] == 11
    assert "alpha_dominant" in out1["regimes"]
    assert "beta_dominant" in out1["regimes"]
    assert out1["regimes"]["alpha_dominant"]["forced_alpha_beta"]["alpha"] > out1["regimes"]["alpha_dominant"]["forced_alpha_beta"]["beta"]
    assert out1["regimes"]["beta_dominant"]["forced_alpha_beta"]["beta"] > out1["regimes"]["beta_dominant"]["forced_alpha_beta"]["alpha"]
    assert out1["regimes"]["alpha_dominant"]["timeline_class_labels"] == out2["regimes"]["alpha_dominant"]["timeline_class_labels"]
    assert out1["regimes"]["beta_dominant"]["timeline_class_labels"] == out2["regimes"]["beta_dominant"]["timeline_class_labels"]
    assert "measure_stats" in out1["regimes"]["alpha_dominant"]
    assert "entropy_bits" in out1["regimes"]["alpha_dominant"]["measure_stats"]
    assert "top1_mass" in out1["regimes"]["alpha_dominant"]["measure_stats"]
    assert "top5_mass" in out1["regimes"]["alpha_dominant"]["measure_stats"]
    assert "measure_divergence" in out1["comparison"]
    assert "js_divergence" in out1["comparison"]["measure_divergence"]
    assert "l1_distance" in out1["comparison"]["measure_divergence"]
    assert "beta_kcollapse_conditional" in out1["comparison"]
    assert "by_k_bin" in out1["comparison"]["beta_kcollapse_conditional"]
    assert "ivi_invariant_series" in out1["regimes"]["alpha_dominant"]
    assert "ivi_invariant_delta" in out1["regimes"]["beta_dominant"]
    assert "ivi_invariant_regime_trend" in out1["comparison"]
    assert "alpha_leq_beta_delta" in out1["comparison"]["ivi_invariant_regime_trend"]


@pytest.mark.order1
def test_class_digest_potential_invariant_under_redescription_actions(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_class_invariance_repo"))
    loop = IVILoopController(grid)

    relift = {
        "conditioning_mode": "bias_candidates",
        "k_collapse": 2,
        "alpha": 0.4,
        "beta": 0.6,
    }
    trace_a = {
        "potential_distribution": [{"tid": "T1", "p": 0.6}, {"tid": "T2", "p": 0.4}],
        "collapse_selection": ["T2", "T1"],
        "formal_targets": [{"eid": "E1"}, {"eid": "E2"}],
        "role_projection": {"subject_tids": ["T1"], "object_tids": ["T2"]},
        "timestamp": 1.0,
    }
    trace_b = {
        "potential_distribution": [{"tid": "T2", "p": 0.4}, {"tid": "T1", "p": 0.6}],
        "collapse_selection": ["T1", "T2"],
        "formal_targets": [{"eid": "E2"}, {"eid": "E1"}],
        "role_projection": {"subject_tids": ["T1"], "object_tids": ["T2"]},
        "timestamp": 9999.0,
        "non_semantic_note": "metadata only perturbation",
    }

    a = loop._derive_topological_class_label(trace_a, relift)
    b = loop._derive_topological_class_label(trace_b, relift)

    assert a["class_digest_potential"] == b["class_digest_potential"]
    assert a["class_features_potential"] == b["class_features_potential"]
    assert a["class_digest_actuated"] == b["class_digest_actuated"]


@pytest.mark.order1
def test_ivi_invariant_is_quotient_stable_for_redescription_actions(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_invariant_quotient_repo"))
    loop = IVILoopController(grid)

    relift = {
        "conditioning_mode": "identity",
        "k_collapse": 1,
        "alpha": 0.5,
        "beta": 0.5,
    }
    trace_a = {
        "potential_distribution": [{"tid": "T1", "p": 0.7}, {"tid": "T2", "p": 0.3}],
        "collapse_selection": ["T1"],
        "formal_targets": [{"eid": "E1"}],
        "role_projection": {"subject_tids": ["T1"], "object_tids": []},
    }
    trace_b = {
        "potential_distribution": [{"tid": "T2", "p": 0.3}, {"tid": "T1", "p": 0.7}],
        "collapse_selection": ["T1"],
        "formal_targets": [{"eid": "E1"}],
        "role_projection": {"subject_tids": ["T1"], "object_tids": []},
        "non_semantic": "metadata perturbation",
    }

    class_a = loop._derive_topological_class_label(trace_a, relift)
    class_b = loop._derive_topological_class_label(trace_b, relift)
    trace_a["class_digest_potential"] = class_a["class_digest_potential"]
    trace_b["class_digest_potential"] = class_b["class_digest_potential"]

    builder_payload = {
        "canonical_action_summary": {"expected_informational_action": 0.75},
        "gating_summary": {"samples_total": 4, "samples_hard_gated": 1},
    }
    inv_a = loop._extract_ivi_invariant_components(trace_a, builder_derivation=builder_payload)
    inv_b = loop._extract_ivi_invariant_components(trace_b, builder_derivation=builder_payload)

    assert class_a["class_digest_potential"] == class_b["class_digest_potential"]
    assert inv_a["value"] == inv_b["value"]
    assert inv_a["components"] == inv_b["components"]
    assert inv_a["quotient_anchor"]["class_digest_potential"] == inv_b["quotient_anchor"]["class_digest_potential"]


@pytest.mark.order1
def test_ivi_invariant_dynamics_law_regime_monotone_and_invariant_modes(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_invariant_dynamics_repo"))
    loop = IVILoopController(grid)

    prev = {
        "regime_label": "alpha_dominant",
        "class_digest_potential": "cls_digest",
        "potential_distribution_digest": "pot_digest",
        "builderbuldozer_model_spec_digest": "spec_digest",
        "ivi_invariant": {"version": "ivi_invariant_v1", "value": 2.0, "digest": "d_prev"},
    }

    cur_alpha = {
        "regime_label": "alpha_dominant",
        "class_digest_potential": "cls_digest_2",
        "potential_distribution_digest": "pot_digest_2",
        "builderbuldozer_model_spec_digest": "spec_digest_2",
        "ivi_invariant": {"version": "ivi_invariant_v1", "value": 1.5, "digest": "d_cur"},
    }
    alpha_check = loop._evaluate_ivi_invariant_dynamics_law(cur_alpha, previous_trace=prev)
    assert alpha_check["enabled"] is True
    assert alpha_check["admissible_update"] is True
    assert alpha_check["passed"] is True
    assert alpha_check["law_kind"] == "monotone_nonincreasing"

    cur_canonical_same = {
        "regime_label": "beta_dominant",
        "class_digest_potential": "cls_digest",
        "potential_distribution_digest": "pot_digest",
        "builderbuldozer_model_spec_digest": "spec_digest",
        "ivi_invariant": {"version": "ivi_invariant_v1", "value": 2.0, "digest": "d_cur2"},
    }
    inv_check = loop._evaluate_ivi_invariant_dynamics_law(cur_canonical_same, previous_trace=prev)
    assert inv_check["enabled"] is True
    assert inv_check["admissible_update"] is True
    assert inv_check["passed"] is True
    assert inv_check["law_kind"] == "invariant_under_canonical_equivalence"


@pytest.mark.order1
def test_ivi_invariant_dynamics_law_is_emitted_in_state_checks(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_invariant_statecheck_repo"))
    loop = IVILoopController(grid)
    loop.evaluate_user_insight_need = lambda progress, checks, trace=None: None

    loop.add_statement_and_loop("seed invariant dynamics", source="test_seed")
    out = loop.add_statement_and_loop("second invariant dynamics", source="test_next")
    checks = out["integration_artifacts"]["StateChecks"]

    assert "ivi_invariant_dynamics_law" in checks
    dyn = checks["ivi_invariant_dynamics_law"]
    assert "enabled" in dyn
    assert "passed" in dyn
    assert "admissible_update" in dyn


@pytest.mark.order1
def test_least_action_components_hard_rejects_and_support_constraint(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_least_action_repo"))
    loop = IVILoopController(grid)

    failed = loop._least_action_components(
        deficit_before=2,
        deficit_after=1,
        pot_before=[0.6, 0.4],
        collapsed_indices=[0],
        oracle_triggered=False,
        novelty=0.0,
        integrity_ok=False,
    )
    assert failed["valid"] is False
    assert failed["hard_reject_reason"] == "integrity_failed"

    outside_support = loop._least_action_components(
        deficit_before=2,
        deficit_after=1,
        pot_before=[1.0, 0.0],
        collapsed_indices=[1],
        oracle_triggered=False,
        novelty=0.0,
        integrity_ok=True,
    )
    assert outside_support["valid"] is False
    assert outside_support["hard_reject_reason"] == "collapse_outside_support"


@pytest.mark.order1
def test_least_action_selection_prefers_lower_action(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_least_action_select_repo"))
    loop = IVILoopController(grid)

    trace = {
        "potential_distribution": [
            {"tid": "T_keep", "p": 0.9},
            {"tid": "T_drop", "p": 0.1},
        ],
        "collapse_selection": [],
        "integrity_ok": True,
    }
    progress = {"latest_creativity_event": {"novel_selected_digest": False}}
    candidates = [
        {
            "tid": "T_keep",
            "weight": 0.9,
            "closure_gain": 0,
            "projected_deficit": 0,
            "symmetry_class": "neutral",
            "delta_signature_digest": "aaa0000000000001",
        },
        {
            "tid": "T_drop",
            "weight": 0.1,
            "closure_gain": 0,
            "projected_deficit": 0,
            "symmetry_class": "neutral",
            "delta_signature_digest": "bbb0000000000002",
        },
    ]

    selected, meta = loop._select_autoloop_candidate(
        candidates,
        trace,
        progress,
        step=1,
        selection_mode="deterministic_replay",
        relift_conditioning={"conditioning_mode": "identity", "alpha": 0.5, "beta": 0.5},
        seed_override=1,
    )
    assert meta["selector"] == "least_action_argmin"
    assert selected["tid"] == "T_drop"


@pytest.mark.order1
def test_least_action_calibration_report_shape(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_least_action_calibration_repo"))
    loop = IVILoopController(grid)
    loop.evaluate_user_insight_need = lambda progress, checks, trace=None: None

    out = loop.run_least_action_calibration(max_steps=1, trials=4, seed_start=3)

    assert out["kind"] == "least_action_calibration"
    assert out["max_steps"] == 1
    assert out["trials"] == 4
    assert out["seed_start"] == 3
    assert out["steps_observed"] >= 1
    assert "predicted_distribution" in out
    assert "observed_distribution" in out
    assert "comparison" in out
    assert out["comparison"]["js_divergence"] >= 0.0
    assert out["comparison"]["l1_distance"] >= 0.0
    assert isinstance(out["trial_reports"], list)
    assert len(out["trial_reports"]) == 4


@pytest.mark.order1
def test_builderbuldozer_derive_command_emits_closure_and_spec_lock_checks(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_builderbuldozer_repo"))
    loop = IVILoopController(grid)

    expected_version = loop.BUILDERBULDOZER_SPEC_VERSION
    expected_digest = loop._builderbuldozer_spec_digest()
    born_distribution = {
        "num_classes": 1,
        "class_probabilities": {"cls_A": 1.0},
        "class_amplitudes": {"cls_A": {"re": 1.0, "im": 0.0}},
    }
    born_distribution_digest = loop._expected_builderbuldozer_distribution_digest(4, 7)

    stub_payload = {
        "enabled": True,
        "module_path": "/tmp/vortex_cone_sim.py",
        "model_spec_version": expected_version,
        "model_spec_digest": expected_digest,
        "inputs": {"num_trials": 4, "seed_start": 7},
        "intermediate_presence": {
            "canon_link_matrix_register": True,
            "canon_braid_word_register_conjugacy_rep": True,
            "canon_ivi_action_terms": True,
            "canon_ivi_potential_amplitude": True,
            "canon_hard_gated": True,
        },
        "gating_summary": {
            "samples_total": 3,
            "samples_hard_gated": 1,
            "samples_included": 2,
            "hard_gate_semantics_defined": True,
            "born_excludes_hard_gated": True,
        },
        "born_distribution": born_distribution,
        "born_distribution_digest": born_distribution_digest,
        "reference_distribution_digest_expected": born_distribution_digest,
        "reference_distribution_digest_locked": True,
        "reference_distribution_digest_match": True,
        "canonical_action_summary": {
            "expected_informational_action": 0.25,
            "class_mean_action": {"cls_A": 0.25},
        },
        "closed_engineering": True,
        "closed_final_theory": True,
    }

    loop._compute_builderbuldozer_derivation = lambda trials=4, seed_start=0: {
        **stub_payload,
        "inputs": {"num_trials": int(trials), "seed_start": int(seed_start)},
    }
    loop._evaluate_ivi_invariant_dynamics_law = lambda trace, previous_trace=None: {
        "name": "ivi_invariant_dynamics_law",
        "enabled": True,
        "passed": True,
        "admissible_update": True,
        "law_kind": "monotone_nonincreasing",
    }

    loop.voice_turn("/builderbuldozer-derive 4 7")
    out = loop.voice_turn("/builderbuldozer-derive 4 7")

    assert out["kind"] == "builderbuldozer_derivation"
    assert out["trials"] == 4
    assert out["seed_start"] == 7
    assert out["derivation"]["enabled"] is True
    assert out["derivation"]["model_spec_version"] == expected_version
    assert out["derivation"]["model_spec_digest"] == expected_digest
    assert "canonical_action_summary" in out["derivation"]
    assert "expected_informational_action" in out["derivation"]["canonical_action_summary"]

    artifacts = out["integration_artifacts"]
    trace = artifacts["Trace"]
    checks = artifacts["StateChecks"]

    assert "builderbuldozer_derivation" in trace
    assert trace["builderbuldozer_model_spec_version"] == expected_version
    assert trace["builderbuldozer_model_spec_digest"] == expected_digest
    assert checks["builderbuldozer_ivi_closure_contract"]["enabled"] is True
    assert checks["builderbuldozer_ivi_closure_contract"]["passed"] is True
    assert checks["builderbuldozer_spec_immutability_gate"]["enabled"] is True
    assert checks["builderbuldozer_spec_immutability_gate"]["passed"] is True
    assert checks["builderbuldozer_reference_distribution_digest_lock"]["enabled"] is True
    assert checks["builderbuldozer_reference_distribution_digest_lock"]["passed"] is True
    assert checks["builderbuldozer_theory_closure_contract"]["enabled"] is True
    assert checks["builderbuldozer_theory_closure_contract"]["passed"] is True
    assert checks["builderbuldozer_theory_closure_contract"]["requirements"]["ivi_invariant_dynamics_law_enabled"] is True
    assert "ivi_invariant" in trace
    assert trace["ivi_invariant"]["version"] == "ivi_invariant_v1"
    assert checks["ivi_invariant_payload_integrity"]["passed"] is True


@pytest.mark.order1
def test_builderbuldozer_reference_digest_lock_detects_mismatch(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_builderbuldozer_ref_lock_repo"))
    loop = IVILoopController(grid)

    check = loop._evaluate_builderbuldozer_reference_digest_lock(
        {
            "enabled": True,
            "inputs": {"num_trials": 4, "seed_start": 0},
            "born_distribution_digest": "wrong_digest",
        }
    )

    assert check["enabled"] is True
    assert check["passed"] is False
    assert check["case_key"] == "4:0"


@pytest.mark.order1
def test_builderbuldozer_spec_immutability_gate_detects_mismatch(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_builderbuldozer_spec_repo"))
    loop = IVILoopController(grid)

    check = loop._evaluate_builderbuldozer_spec_immutability(
        {
            "model_spec_version": "wrong_spec",
            "model_spec_digest": "wrong_digest",
        }
    )

    assert check["enabled"] is True
    assert check["passed"] is False
    assert "builderbuldozer_spec_version_mismatch" in check["violations"]
    assert "builderbuldozer_spec_digest_mismatch" in check["violations"]


@pytest.mark.order1
def test_voice_turn_supports_autoloop_regime_command(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_regime_cmd_repo"))
    loop = IVILoopController(grid)
    loop.evaluate_user_insight_need = lambda progress, checks, trace=None: None

    loop.add_statement_and_loop("regime command baseline", source="test_regime_cmd")
    out = loop.voice_turn("/autoloop-regime 1 5")

    assert out["kind"] == "regime_ab_experiment"
    assert out["seed_override"] == 5
    assert "alpha_dominant" in out["regimes"]
    assert "beta_dominant" in out["regimes"]


@pytest.mark.order1
def test_order_relation_contract_has_all_four_orders(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_order_relation_repo"))
    loop = IVILoopController(grid)

    loop.evaluate_user_insight_need = lambda progress, checks, trace=None: None
    out = loop.add_statement_and_loop("order relation integration probe", source="test_order_relation")
    trace = out["integration_artifacts"]["Trace"]
    relation = trace["order_relation"]

    assert relation["mode"] == "continuous_triad_v1"
    assert "order_1_projection" in relation
    assert "order_2_potential" in relation
    assert "order_3_contact" in relation
    assert "order_4_boundary" in relation
    assert "order_coupling" in relation
    assert relation["order_1_projection"]["class_label"] == trace["class_label"]
    assert relation["order_coupling"]["relift_conditioning_mode"] == trace["relift_conditioning_mode"]
    assert isinstance(relation["digest"], str) and relation["digest"]


@pytest.mark.order1
def test_progress_reports_class_distribution_by_regime(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_class_distribution_repo"))
    loop = IVILoopController(grid)

    loop._append_integration_artifacts(
        {
            "Trace": {"class_label": "cls_A", "regime_label": "alpha_dominant"},
            "Gap": [],
            "CreativityEvent": {"creative": False, "basis": "none", "novel_selected_digest": False},
            "RefinementApplied": {"action": "noop"},
        }
    )
    loop._append_integration_artifacts(
        {
            "Trace": {"class_label": "cls_B", "regime_label": "alpha_dominant"},
            "Gap": [],
            "CreativityEvent": {"creative": False, "basis": "none", "novel_selected_digest": False},
            "RefinementApplied": {"action": "noop"},
        }
    )
    loop._append_integration_artifacts(
        {
            "Trace": {"class_label": "cls_A", "regime_label": "beta_dominant"},
            "Gap": [],
            "CreativityEvent": {"creative": False, "basis": "none", "novel_selected_digest": False},
            "RefinementApplied": {"action": "noop"},
        }
    )

    progress = loop.get_axiom_self_generation_progress()
    dist = progress["class_regime_distribution"]
    inv = progress["ivi_invariant_by_regime"]

    assert dist["alpha_dominant"]["total"] == 2
    assert dist["beta_dominant"]["total"] == 1
    assert dist["balanced"]["total"] == 0
    alpha_classes = {entry["class_label"]: entry["count"] for entry in dist["alpha_dominant"]["by_class"]}
    beta_classes = {entry["class_label"]: entry["count"] for entry in dist["beta_dominant"]["by_class"]}
    assert alpha_classes == {"cls_A": 1, "cls_B": 1}
    assert beta_classes == {"cls_A": 1}
    assert "alpha_dominant" in inv
    assert "beta_dominant" in inv


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
    assert req["OracleRequest"]["question_template_id"] == "oracle_template_branch_point_v1"
    assert req["OracleRequest"]["oracle_template_version"] == "oracle_template_branch_point_v1"
    assert req["OracleRequest"]["oracle_template_digest"]
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
    assert req["OracleRequest"]["question_template_id"] == "oracle_template_stagnation_v1"
    assert req["OracleRequest"]["oracle_template_version"] == "oracle_template_stagnation_v1"
    assert req["OracleRequest"]["oracle_template_digest"]


@pytest.mark.order1
def test_insight_parses_branch_point_and_stagnation_answer_contracts(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_oracle_answer_repo"))
    loop = IVILoopController(grid)

    branch_req = loop._attach_oracle_template_metadata(
        {
            "trigger_reason": "conflicting_admissible_refinements",
            "trigger_class": "non_dominated_candidate_set",
            "impasse_description": "test",
            "candidate_actions": ["T_A", "T_B"],
            "missing_information": "select one signature",
            "recommended_question": "STATE IMPASSE DETECTED",
            "minimal_question": "STATE IMPASSE DETECTED",
            "trigger_evidence": {},
            "expected_impact": "inject_external_constraint_to_resume_refinement",
        },
        template_id="oracle_template_branch_point_v1",
        template_inputs={"candidate_actions": ["T_A", "T_B"]},
    )
    loop._set_active_oracle_request({"OracleRequest": branch_req})
    branch_out = loop.voice_turn("/insight opt_1")

    assert branch_out["kind"] == "insight"
    assert branch_out["oracle_answer"]["applied"] is True
    assert branch_out["oracle_answer"]["template_id"] == "oracle_template_branch_point_v1"
    assert branch_out["oracle_answer"]["schema_ok"] is True
    assert branch_out["oracle_answer"]["parsed"]["option_id"] == "opt_1"
    assert branch_out["oracle_commitment"]["schema_ok"] is True
    assert branch_out["oracle_commitment"]["parsed_digest"]

    stag_req = loop._attach_oracle_template_metadata(
        {
            "trigger_reason": "stagnation",
            "trigger_class": "stagnation",
            "impasse_description": "test",
            "candidate_actions": ["T_A"],
            "missing_information": "new constraint",
            "recommended_question": "STATE STAGNATION DETECTED",
            "minimal_question": "STATE STAGNATION DETECTED",
            "trigger_evidence": {},
            "expected_impact": "inject_external_constraint_to_resume_refinement",
        },
        template_id="oracle_template_stagnation_v1",
        template_inputs={"candidate_actions": ["T_A"]},
    )
    loop._set_active_oracle_request({"OracleRequest": stag_req})
    stag_out = loop.voice_turn("/insight new_constraint=use objective projection")

    assert stag_out["oracle_answer"]["template_id"] == "oracle_template_stagnation_v1"
    assert stag_out["oracle_answer"]["schema_ok"] is True
    assert stag_out["oracle_answer"]["parsed"]["new_constraint"] == "use objective projection"
    assert stag_out["oracle_answer"]["parsed"]["priority"] == "intent_constraint"


@pytest.mark.order1
def test_oracle_minimal_question_template_fixed_point(tmp_path):
    grid = IVISimplicialGrid(base_dir=str(tmp_path / "voice_layer_fixed_point_template_repo"))
    loop = IVILoopController(grid)

    question = loop._oracle_minimal_question_template(
        trigger_class="fixed_point",
        reasons=["fixed_point"],
        candidate_actions=["T_alpha"],
        missing_information="new objective or boundary extension",
        trigger_evidence={"closure_deficit": 0, "max_closure_gain": 0},
    )

    assert "STATE BOUNDARY REACHED" in question
    assert "Class: fixed_point" in question
    assert "/insight <constraint>" in question
