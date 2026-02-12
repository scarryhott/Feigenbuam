import math

from ivi_ai_from_BK import (
    PotentialAI,
    PotentialParams,
    default_signal_suite,
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


def test_single_signal_evaluation_remains_available():
    run = evaluate_params(PotentialParams(), default_signal_suite(32))
    assert 0.0 <= run.potentiality <= 1.0
