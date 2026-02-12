import math

from ivi_ai_from_BK import (
    PotentialAI,
    PotentialParams,
    default_signal_suite,
    evaluate_params,
    iterative_tune,
)


def test_signal_suite_shape_and_bounds():
    signal = default_signal_suite(length=60)
    assert len(signal) == 60
    assert max(signal) <= 1.2
    assert min(signal) >= -1.2


def test_run_produces_valid_metrics():
    signal = default_signal_suite(length=50)
    run = PotentialAI(PotentialParams()).run(signal)

    assert len(run.trajectory) == len(signal)
    assert 0.0 <= run.potentiality <= 1.0
    assert 0.0 <= run.stability <= 1.0
    assert -1.0 <= run.coherence <= 1.0
    assert 0.0 <= run.responsiveness <= 1.0


def test_iterative_tune_does_not_degrade_baseline():
    baseline = PotentialParams()
    signal = default_signal_suite(length=80)
    base_run = evaluate_params(baseline, signal)
    tuned_params, tuned_run, history = iterative_tune(baseline=baseline, signal=signal, rounds=5)

    assert tuned_run.potentiality >= base_run.potentiality
    assert len(history) >= 1

    # Ensure output remains finite and numerically stable.
    for value in tuned_params.__dict__.values():
        assert math.isfinite(value)
