import math

from ivi_ai_from_BK import (
    PotentialAI,
    PotentialParams,
    compare_against_normal_baselines,
    born_weight_summary,
    derive_duality_schema,
    derive_interface_rules,
    derive_potential_layer_spec,
    default_signal_suite,
    default_baseline_suite,
    evaluate_across_regimes,
    evaluate_params,
    iterative_tune,
    regime_signal_suite,
)


def test_signal_suite_shape_and_bounds():
    signal = default_signal_suite(length=60)
    assert len(signal) == 60
    assert max(signal) <= 1.2
    assert min(signal) >= -1.2


def test_regime_suite_has_expected_regimes():
    regimes = regime_signal_suite(length=80)
    assert set(regimes.keys()) == {"mixed", "chirp", "step", "spike"}
    assert all(len(v) == 80 for v in regimes.values())


def test_run_produces_valid_metrics():
    signal = default_signal_suite(length=50)
    run = PotentialAI(PotentialParams()).run(signal)

    assert len(run.trajectory) == len(signal)
    assert 0.0 <= run.potentiality <= 1.0
    assert 0.0 <= run.stability <= 1.0
    assert -1.0 <= run.coherence <= 1.0
    assert 0.0 <= run.responsiveness <= 1.0


def test_iterative_tune_improves_cross_regime_scores_and_reaches_success():
    baseline = PotentialParams()
    base_runs, base_report = evaluate_across_regimes(baseline, length=80)
    tuned_params, tuned_runs, tuned_report, history = iterative_tune(baseline=baseline, rounds=8, length=80)

    assert tuned_report.avg_potentiality >= base_report.avg_potentiality
    assert tuned_report.min_potentiality >= base_report.min_potentiality
    assert tuned_report.success
    assert len(history) >= 2

    for run in base_runs.values():
        assert 0.0 <= run.potentiality <= 1.0

    for run in tuned_runs.values():
        assert 0.0 <= run.potentiality <= 1.0

    for value in tuned_params.__dict__.values():
        assert math.isfinite(value)


def test_compare_against_normal_baselines_returns_expected_models_and_stats():
    contexts, summary = compare_against_normal_baselines(length=40)

    assert set(summary.keys()) >= {"ivi", "persistence", "ewma", "linear_trend"}
    assert set(contexts.keys()) == {"mixed", "chirp", "step", "spike"}

    for regime_name, context in contexts.items():
        assert context.length == 40
        assert regime_name == context.name
        assert set(context.runs.keys()) >= {"ivi", "persistence"}

    for model_stats in summary.values():
        assert 0.0 <= model_stats["min"] <= model_stats["avg"] <= 1.0


def test_default_baseline_suite_has_callable_entries():
    suite = default_baseline_suite()
    assert {"persistence", "ewma", "linear_trend"} <= set(suite.keys())

    signal = default_signal_suite(length=12)
    for runner in suite.values():
        run = runner(signal)
        assert 0.0 <= run.potentiality <= 1.0


def test_duality_schema_derivations_remain_consistent():
    spec, runs, report = derive_potential_layer_spec(length=32)
    assert spec.params == PotentialParams()
    assert spec.duality_condition.startswith("D_s J")
    assert len(spec.invariants) == 3
    assert math.isclose(spec.invariants[0].value, report.avg_potentiality)
    assert set(runs.keys()) == {"mixed", "chirp", "step", "spike"}

    rules = derive_interface_rules(length=32)
    assert set(rules.keys()) == {"mixed", "chirp", "step", "spike"}
    for rule in rules.values():
        assert rule.functor_name.startswith("F_")
        assert math.isclose(sum(rule.weights.values()), 1.0, rel_tol=1e-6)

    spec2, interface_rules, contexts = derive_duality_schema(length=32)
    assert spec2 == spec
    assert interface_rules.keys() == rules.keys()
    assert contexts.keys() == runs.keys()


def test_born_weight_summary_matches_model_counts():
    contexts, _ = compare_against_normal_baselines(length=20)
    summary = born_weight_summary(contexts)

    assert summary.keys() == contexts.keys()
    for ctx_name, weights in summary.items():
        assert set(weights.keys()) == set(contexts[ctx_name].runs.keys())
        total = sum(weights.values())
        assert 0.99 <= total <= 1.01


def test_single_signal_evaluation_remains_available():
    run = evaluate_params(PotentialParams(), default_signal_suite(32))
    assert 0.0 <= run.potentiality <= 1.0
