"""Core numerical model for Feigenbuam potential-AI experiments.

The repository themes mention:
- critical scaling
- refinement geometry
- nonlinear time processing
- global coherence enforcement

This module implements those ideas as a numerical state-space model and adds
robust iterative tuning over several signal regimes with an explicit success
criterion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple
import math


@dataclass(frozen=True)
class PotentialParams:
    """Model parameters controlling numerical behavior."""

    critical_scale: float = 1.20
    refine_gain: float = 0.55
    time_warp: float = 1.05
    coherence_gain: float = 0.32
    damping: float = 0.09


@dataclass(frozen=True)
class PotentialRun:
    """Outputs from one simulation run."""

    trajectory: List[float]
    potentiality: float
    stability: float
    coherence: float
    responsiveness: float


@dataclass(frozen=True)
class SuccessReport:
    """Aggregated cross-scenario quality report."""

    avg_potentiality: float
    min_potentiality: float
    success: bool
    threshold: float


class PotentialAI:
    """Numerical engine for iterative potentiality development."""

    def __init__(self, params: PotentialParams | None = None) -> None:
        self.params = params or PotentialParams()

    def _step(self, state: float, target: float, t: int) -> float:
        p = self.params

        # 1) Critical scaling: saturating nonlinearity around the current state.
        critical = p.critical_scale * state * (1.0 - abs(state))

        # 2) Refinement geometry: contraction toward target manifold.
        refine = p.refine_gain * (target - state)

        # 3) Nonlinear time processing: moderate adaptive gain over time.
        time_gain = (1.0 + t) ** (p.time_warp - 1.0)

        # 4) Global coherence enforcement through bounded consensus term.
        coherence = p.coherence_gain * math.tanh(target - 0.35 * state)

        # Damping keeps trajectories physically plausible and stable.
        next_state = state + time_gain * (critical + refine + coherence) - p.damping * state
        return max(-1.5, min(1.5, next_state))

    def run(self, signals: Sequence[float], initial_state: float = 0.05) -> PotentialRun:
        """Run simulation on a sequence of scalar signals."""
        if not signals:
            raise ValueError("signals must be non-empty")

        state = initial_state
        trajectory: List[float] = []

        for t, target in enumerate(signals):
            state = self._step(state, target, t)
            trajectory.append(state)

        deviations = [abs(x - y) for x, y in zip(trajectory, signals)]
        mse = sum(d * d for d in deviations) / len(deviations)
        mae = sum(deviations) / len(deviations)
        coherence = 1.0 - min(1.0, mae)

        if len(trajectory) >= 3:
            accel = [
                abs(trajectory[i] - 2 * trajectory[i - 1] + trajectory[i - 2])
                for i in range(2, len(trajectory))
            ]
            stability = 1.0 / (1.0 + sum(accel) / len(accel))
        else:
            stability = 1.0

        drift = abs(trajectory[-1] - trajectory[0])
        responsiveness = math.tanh(1.7 * drift)

        # Composite potentiality score (clipped to [0,1]).
        potentiality = max(
            0.0,
            min(1.0, 0.50 * (1.0 / (1.0 + mse)) + 0.25 * coherence + 0.15 * stability + 0.10 * responsiveness),
        )

        return PotentialRun(
            trajectory=trajectory,
            potentiality=potentiality,
            stability=stability,
            coherence=coherence,
            responsiveness=responsiveness,
        )


def default_signal_suite(length: int = 80) -> List[float]:
    """Construct a deterministic nonlinear benchmark signal."""
    signal = []
    for t in range(length):
        x = t / max(1, length - 1)
        signal.append(0.55 * math.sin(8.0 * x) + 0.35 * math.sin(19.0 * x + 0.4) + 0.25 * (2 * x - 1) ** 3)
    return signal


def regime_signal_suite(length: int = 80) -> Dict[str, List[float]]:
    """Multiple benchmark regimes for robust potentiality evaluation."""
    if length < 8:
        raise ValueError("length must be >= 8")

    base = default_signal_suite(length)
    xvals = [t / max(1, length - 1) for t in range(length)]

    chirp = [0.60 * math.sin((3.0 + 12.0 * x) * x * 4.0) + 0.15 * (2 * x - 1) for x in xvals]
    step = [(-0.65 if x < 0.33 else (0.75 if x < 0.66 else -0.15)) for x in xvals]
    spike = [0.2 * math.sin(11.0 * x) + (0.75 if abs(x - 0.62) < 0.03 else 0.0) for x in xvals]

    return {"mixed": base, "chirp": chirp, "step": step, "spike": spike}


def evaluate_params(params: PotentialParams, signal: Sequence[float] | None = None) -> PotentialRun:
    """Evaluate one parameter set on one benchmark signal."""
    suite = list(signal) if signal is not None else default_signal_suite()
    return PotentialAI(params).run(suite)


def evaluate_across_regimes(params: PotentialParams, length: int = 80) -> Tuple[Dict[str, PotentialRun], SuccessReport]:
    """Evaluate a parameter set on all benchmark regimes."""
    runs: Dict[str, PotentialRun] = {}
    for name, sig in regime_signal_suite(length).items():
        runs[name] = evaluate_params(params, sig)

    scores = [r.potentiality for r in runs.values()]
    avg_score = sum(scores) / len(scores)
    min_score = min(scores)
    threshold = 0.78

    report = SuccessReport(
        avg_potentiality=avg_score,
        min_potentiality=min_score,
        success=(avg_score >= threshold and min_score >= 0.70),
        threshold=threshold,
    )
    return runs, report


def iterative_tune(
    baseline: PotentialParams | None = None,
    rounds: int = 6,
    length: int = 80,
) -> Tuple[PotentialParams, Dict[str, PotentialRun], SuccessReport, List[Tuple[PotentialParams, SuccessReport]]]:
    """Coordinate-search tuner optimizing robust cross-regime potentiality."""
    best_params = baseline or PotentialParams()
    best_runs, best_report = evaluate_across_regimes(best_params, length)
    history: List[Tuple[PotentialParams, SuccessReport]] = [(best_params, best_report)]

    deltas: Dict[str, Iterable[float]] = {
        "critical_scale": (0.88, 0.95, 1.05, 1.12),
        "refine_gain": (0.88, 0.95, 1.05, 1.12),
        "time_warp": (0.92, 0.98, 1.02, 1.08),
        "coherence_gain": (0.88, 0.95, 1.05, 1.12),
        "damping": (0.85, 0.94, 1.06, 1.15),
    }

    def better(candidate: SuccessReport, incumbent: SuccessReport) -> bool:
        return (candidate.avg_potentiality, candidate.min_potentiality) > (
            incumbent.avg_potentiality,
            incumbent.min_potentiality,
        )

    for _ in range(rounds):
        improved = False
        for field_name, scales in deltas.items():
            current_value = getattr(best_params, field_name)
            for scale in scales:
                candidate_value = current_value * scale
                candidate = PotentialParams(**{**best_params.__dict__, field_name: candidate_value})
                candidate_runs, candidate_report = evaluate_across_regimes(candidate, length)
                if better(candidate_report, best_report):
                    best_params, best_runs, best_report = candidate, candidate_runs, candidate_report
                    history.append((best_params, best_report))
                    improved = True
        if best_report.success and len(history) > 1:
            break
        if not improved:
            break

    return best_params, best_runs, best_report, history


if __name__ == "__main__":
    baseline = PotentialParams()
    base_runs, base_report = evaluate_across_regimes(baseline)
    tuned_params, tuned_runs, tuned_report, tuning_history = iterative_tune(baseline=baseline, rounds=8)

    print("Baseline average potentiality:", round(base_report.avg_potentiality, 6))
    print("Tuned average potentiality   :", round(tuned_report.avg_potentiality, 6))
    print("Baseline minimum potentiality:", round(base_report.min_potentiality, 6))
    print("Tuned minimum potentiality   :", round(tuned_report.min_potentiality, 6))
    print("Success threshold            :", tuned_report.threshold)
    print("Success status               :", tuned_report.success)
    print("History improvements         :", len(tuning_history) - 1)
    print("Tuned params                 :", tuned_params)

    for name in sorted(tuned_runs.keys()):
        print(f"{name:>8} potentiality         :", round(tuned_runs[name].potentiality, 6))
