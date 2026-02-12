"""Core numerical model for Feigenbuam potential-AI experiments.

The repository themes mention:
- critical scaling
- refinement geometry
- nonlinear time processing
- global coherence enforcement

This module provides a compact, testable implementation of these ideas using a
numerical state-space simulation and a potentiality score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple
import math


@dataclass(frozen=True)
class PotentialParams:
    """Model parameters controlling numerical behavior.

    Attributes:
        critical_scale: nonlinearity coefficient for critical scaling.
        refine_gain: strength of geometric refinement pull.
        time_warp: exponent controlling nonlinear time processing.
        coherence_gain: strength of global coherence enforcement.
        damping: stabilizer that limits oscillation blow-up.
    """

    critical_scale: float = 1.35
    refine_gain: float = 0.45
    time_warp: float = 1.15
    coherence_gain: float = 0.40
    damping: float = 0.06


@dataclass(frozen=True)
class PotentialRun:
    """Outputs from one simulation run."""

    trajectory: List[float]
    potentiality: float
    stability: float
    coherence: float
    responsiveness: float


class PotentialAI:
    """Numerical engine for iterative potentiality development."""

    def __init__(self, params: PotentialParams | None = None) -> None:
        self.params = params or PotentialParams()

    def _step(self, state: float, target: float, t: int) -> float:
        p = self.params

        # 1) Critical scaling: logistic-inspired critical map around state.
        critical = p.critical_scale * state * (1.0 - abs(state))

        # 2) Refinement geometry: contraction toward target manifold.
        refine = p.refine_gain * (target - state)

        # 3) Nonlinear time processing: time-adaptive gain.
        time_gain = (1.0 + t) ** (p.time_warp - 1.0)

        # 4) Global coherence enforcement through bounded consensus term.
        coherence = p.coherence_gain * math.tanh(target)

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

        # Metrics for "AI potentiality".
        deviations = [abs(x - y) for x, y in zip(trajectory, signals)]
        mse = sum(d * d for d in deviations) / len(deviations)
        coherence = 1.0 - min(1.0, sum(deviations) / len(deviations))

        # Stability penalizes high acceleration / jitter.
        if len(trajectory) >= 3:
            accel = [
                abs(trajectory[i] - 2 * trajectory[i - 1] + trajectory[i - 2])
                for i in range(2, len(trajectory))
            ]
            stability = 1.0 / (1.0 + sum(accel) / len(accel))
        else:
            stability = 1.0

        # Responsiveness rewards useful movement (non-flat and non-chaotic).
        drift = abs(trajectory[-1] - trajectory[0])
        responsiveness = math.tanh(1.5 * drift)

        # Composite potentiality score (0..1-ish).
        potentiality = max(
            0.0,
            min(1.0, 0.45 * (1.0 / (1.0 + mse)) + 0.30 * coherence + 0.15 * stability + 0.10 * responsiveness),
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
        # Mixed periodic + nonlinear drift profile.
        signal.append(0.55 * math.sin(8.0 * x) + 0.35 * math.sin(19.0 * x + 0.4) + 0.25 * (2 * x - 1) ** 3)
    return signal


def evaluate_params(params: PotentialParams, signal: Sequence[float] | None = None) -> PotentialRun:
    """Evaluate one parameter set on benchmark signal."""
    suite = list(signal) if signal is not None else default_signal_suite()
    return PotentialAI(params).run(suite)


def iterative_tune(
    baseline: PotentialParams | None = None,
    signal: Sequence[float] | None = None,
    rounds: int = 4,
) -> Tuple[PotentialParams, PotentialRun, List[Tuple[PotentialParams, PotentialRun]]]:
    """Simple coordinate-search tuner that iteratively improves potentiality."""
    signal = list(signal) if signal is not None else default_signal_suite()
    best_params = baseline or PotentialParams()
    best_run = evaluate_params(best_params, signal)
    history: List[Tuple[PotentialParams, PotentialRun]] = [(best_params, best_run)]

    # Local search deltas (deterministic and bounded for repeatability).
    deltas: Dict[str, Iterable[float]] = {
        "critical_scale": (0.85, 0.95, 1.05, 1.15),
        "refine_gain": (0.85, 0.95, 1.05, 1.15),
        "time_warp": (0.90, 0.97, 1.03, 1.10),
        "coherence_gain": (0.85, 0.95, 1.05, 1.15),
        "damping": (0.80, 0.92, 1.08, 1.20),
    }

    for _ in range(rounds):
        improved = False
        for field_name, scales in deltas.items():
            current_value = getattr(best_params, field_name)
            for scale in scales:
                candidate_value = current_value * scale
                candidate = PotentialParams(**{**best_params.__dict__, field_name: candidate_value})
                run = evaluate_params(candidate, signal)
                if run.potentiality > best_run.potentiality:
                    best_params, best_run = candidate, run
                    history.append((best_params, best_run))
                    improved = True
        if not improved:
            break

    return best_params, best_run, history


if __name__ == "__main__":
    baseline = PotentialParams()
    base_run = evaluate_params(baseline)
    tuned_params, tuned_run, tuning_history = iterative_tune(baseline=baseline, rounds=5)

    print("Baseline potentiality:", round(base_run.potentiality, 6))
    print("Tuned potentiality   :", round(tuned_run.potentiality, 6))
    print("History improvements :", len(tuning_history) - 1)
    print("Tuned params         :", tuned_params)
