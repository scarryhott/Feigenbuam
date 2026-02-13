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
from typing import Callable, Dict, Iterable, List, Sequence, Tuple
import math
import numpy as np

from born_rule import BornContext, lueders_dephase_rho, probs_from_density
from density_builders import (
    build_rho_from_scores_and_coherence,
    coherence_matrix_from_named_embeddings,
    orthonormal_basis_from_named_embeddings,
)
from potential_ai_born import PotentialAIBornPolicy, PotentialAIState


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


@dataclass(frozen=True)
class CollapseContext:
    """Represents a collapse/evaluation context for one benchmark regime."""

    name: str
    signal: Tuple[float, ...]
    runs: Dict[str, PotentialRun]

    @property
    def length(self) -> int:
        return len(self.signal)


@dataclass(frozen=True)
class PotentialInvariant:
    """Represents a duality-preserving invariant derived upstream of context."""

    name: str
    value: float
    description: str


@dataclass(frozen=True)
class PotentialLayerSpec:
    """Captures the context-free potential layer state."""

    params: PotentialParams
    invariants: Tuple[PotentialInvariant, ...]
    duality_condition: str = "D_s J = 0 (numerical analogue)"


@dataclass(frozen=True)
class InterfaceRule:
    """Describes one context-indexed collapse functor and its weights."""

    context: str
    functor_name: str
    weights: Dict[str, float]
    description: str


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

        return _compute_run_metrics(trajectory, signals)


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


def _compute_run_metrics(trajectory: Sequence[float], target: Sequence[float]) -> PotentialRun:
    """Shared metric computation used by IVI and baseline models."""

    trajectory_list = list(trajectory)
    target_list = list(target)
    if not trajectory_list:
        raise ValueError("trajectory must be non-empty")
    if len(trajectory_list) != len(target_list):
        raise ValueError("trajectory and target must have the same length")

    deviations = [abs(x - y) for x, y in zip(trajectory_list, target_list)]
    mse = sum(d * d for d in deviations) / len(deviations)
    mae = sum(deviations) / len(deviations)
    coherence = 1.0 - min(1.0, mae)

    if len(trajectory_list) >= 3:
        accel = [
            abs(trajectory_list[i] - 2 * trajectory_list[i - 1] + trajectory_list[i - 2])
            for i in range(2, len(trajectory_list))
        ]
        stability = 1.0 / (1.0 + sum(accel) / len(accel))
    else:
        stability = 1.0

    drift = abs(trajectory_list[-1] - trajectory_list[0])
    responsiveness = math.tanh(1.7 * drift)

    potentiality = max(
        0.0,
        min(1.0, 0.50 * (1.0 / (1.0 + mse)) + 0.25 * coherence + 0.15 * stability + 0.10 * responsiveness),
    )

    return PotentialRun(
        trajectory=list(trajectory_list),
        potentiality=potentiality,
        stability=stability,
        coherence=coherence,
        responsiveness=responsiveness,
    )


def persistence_baseline(signal: Sequence[float]) -> PotentialRun:
    """Naive baseline that predicts the previous observation (persistence)."""

    values = list(signal)
    if not values:
        raise ValueError("signal must be non-empty")

    preds = [values[0]]
    preds.extend(values[:-1])
    return _compute_run_metrics(preds, values)


def ewma_baseline(signal: Sequence[float], alpha: float = 0.35) -> PotentialRun:
    """Exponentially weighted moving average baseline."""

    if not 0.0 < alpha <= 1.0:
        raise ValueError("alpha must be in (0, 1]")

    values = list(signal)
    if not values:
        raise ValueError("signal must be non-empty")

    preds: List[float] = []
    ema = values[0]
    for value in values:
        preds.append(ema)
        ema = alpha * value + (1.0 - alpha) * ema
    return _compute_run_metrics(preds, values)


def linear_trend_baseline(signal: Sequence[float], window: int = 6) -> PotentialRun:
    """Linear trend extrapolation using a sliding history window."""

    if window < 2:
        raise ValueError("window must be >= 2")

    values = list(signal)
    if not values:
        raise ValueError("signal must be non-empty")

    preds: List[float] = []
    for t in range(len(values)):
        history_start = max(0, t - window)
        history_idx = list(range(history_start, t))

        if not history_idx:
            preds.append(values[0])
            continue
        if len(history_idx) == 1:
            preds.append(values[history_idx[-1]])
            continue

        history_vals = [values[i] for i in history_idx]
        mean_x = sum(history_idx) / len(history_idx)
        mean_y = sum(history_vals) / len(history_vals)
        denom = sum((x - mean_x) ** 2 for x in history_idx)
        if denom == 0.0:
            slope = 0.0
        else:
            slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(history_idx, history_vals)) / denom
        intercept = mean_y - slope * mean_x
        preds.append(slope * t + intercept)

    return _compute_run_metrics(preds, values)


BaselineCallable = Callable[[Sequence[float]], PotentialRun]


def default_baseline_suite() -> Dict[str, BaselineCallable]:
    """Return the built-in collection of normal-AI baselines."""

    return {
        "persistence": persistence_baseline,
        "ewma": ewma_baseline,
        "linear_trend": linear_trend_baseline,
    }


def summarize_model_performance(contexts: Dict[str, CollapseContext]) -> Dict[str, Dict[str, float]]:
    """Aggregate potentiality statistics for every model across contexts."""

    aggregates: Dict[str, List[float]] = {}
    for context in contexts.values():
        for model_name, run in context.runs.items():
            aggregates.setdefault(model_name, []).append(run.potentiality)

    return {
        name: {
            "avg": sum(scores) / len(scores),
            "min": min(scores),
        }
        for name, scores in aggregates.items()
    }


def compare_against_normal_baselines(
    params: PotentialParams | None = None,
    length: int = 80,
    baselines: Dict[str, BaselineCallable] | None = None,
) -> Tuple[Dict[str, CollapseContext], Dict[str, Dict[str, float]]]:
    """Evaluate IVI and baseline models on the same benchmark regimes."""

    baseline_suite = baselines or default_baseline_suite()
    regimes = regime_signal_suite(length)
    ai = PotentialAI(params or PotentialParams())

    contexts: Dict[str, CollapseContext] = {}
    for name, signal in regimes.items():
        runs: Dict[str, PotentialRun] = {"ivi": ai.run(signal)}
        for baseline_name, runner in baseline_suite.items():
            runs[baseline_name] = runner(signal)
        contexts[name] = CollapseContext(name=name, signal=tuple(signal), runs=runs)

    summary = summarize_model_performance(contexts)
    return contexts, summary


def born_weighted_model_probs(
    context: CollapseContext,
    metric: Callable[[PotentialRun], float] | None = None,
    collapse_side: bool = False,
    use_density: bool = False,
    coherence_embeddings: Dict[str, Sequence[float]] | None = None,
    lam: float = 0.25,
    use_embedding_basis: bool = False,
) -> Dict[str, float]:
    """Compute Born-rule action weights for the models in one context."""

    metric_fn = metric or (lambda run: run.potentiality)
    model_names = list(context.runs.keys())
    raw_scores = {name: max(metric_fn(context.runs[name]), 0.0) for name in model_names}

    amplitudes = np.array([raw_scores[name] for name in model_names], dtype=np.complex128)
    if not np.any(amplitudes):
        amplitudes = np.ones_like(amplitudes)

    basis = None
    if use_embedding_basis and coherence_embeddings:
        basis = orthonormal_basis_from_named_embeddings(model_names, coherence_embeddings)
    if basis is None:
        basis = np.eye(len(model_names), dtype=np.complex128)
    born_ctx = BornContext.from_orthonormal_basis(basis)
    canonical_ctx = BornContext.from_orthonormal_basis(np.eye(len(model_names), dtype=np.complex128))

    if use_density:
        coherence = coherence_matrix_from_named_embeddings(model_names, coherence_embeddings)
        rho, _ = build_rho_from_scores_and_coherence(raw_scores, coherence=coherence, lam=lam)
        if collapse_side:
            rho = lueders_dephase_rho(rho, canonical_ctx.projectors)
        probs = probs_from_density(rho, born_ctx.projectors)
        return dict(zip(model_names, probs))

    state = PotentialAIState(psi=amplitudes)
    collapse_proj = canonical_ctx.projectors if collapse_side else None
    policy = PotentialAIBornPolicy(use_collapse_side=collapse_side, collapse_projectors=collapse_proj)
    probs = policy.action_distribution(state, born_ctx)
    return dict(zip(model_names, probs))


def born_weight_summary(
    contexts: Dict[str, CollapseContext],
    metric: Callable[[PotentialRun], float] | None = None,
    collapse_side: bool = False,
    use_density: bool = False,
    coherence_embeddings: Dict[str, Sequence[float]] | None = None,
    lam: float = 0.25,
    use_embedding_basis: bool = False,
) -> Dict[str, Dict[str, float]]:
    """Return Born-rule weights for every context/model combination."""

    return {
        name: born_weighted_model_probs(
            context,
            metric=metric,
            collapse_side=collapse_side,
            use_density=use_density,
            coherence_embeddings=coherence_embeddings,
            lam=lam,
            use_embedding_basis=use_embedding_basis,
        )
        for name, context in contexts.items()
    }


def derive_potential_layer_spec(
    params: PotentialParams | None = None,
    length: int = 80,
) -> Tuple[PotentialLayerSpec, Dict[str, PotentialRun], SuccessReport]:
    """Build the context-free potential layer specification and invariants."""

    base_params = params or PotentialParams()
    runs, report = evaluate_across_regimes(base_params, length)
    invariants: Tuple[PotentialInvariant, ...] = (
        PotentialInvariant(
            name="avg_potentiality",
            value=report.avg_potentiality,
            description="Context-free robust average potentiality",
        ),
        PotentialInvariant(
            name="min_potentiality",
            value=report.min_potentiality,
            description="Worst-case potentiality across benchmark regimes",
        ),
        PotentialInvariant(
            name="success_threshold",
            value=report.threshold,
            description="Target threshold ensuring duality-preserving success",
        ),
    )

    spec = PotentialLayerSpec(params=base_params, invariants=invariants)
    return spec, runs, report


def derive_interface_rules(
    params: PotentialParams | None = None,
    length: int = 80,
    baselines: Dict[str, BaselineCallable] | None = None,
) -> Dict[str, InterfaceRule]:
    """Construct per-context collapse rules (functors) with normalized weights."""

    contexts, _ = compare_against_normal_baselines(params=params, length=length, baselines=baselines)
    rules: Dict[str, InterfaceRule] = {}

    for context_name, context in contexts.items():
        potentials = {model: run.potentiality for model, run in context.runs.items()}
        total = sum(potentials.values())
        if total <= 0.0:
            weight = 1.0 / len(potentials)
            normalized = {model: weight for model in potentials.keys()}
        else:
            normalized = {model: value / total for model, value in potentials.items()}

        rules[context_name] = InterfaceRule(
            context=context_name,
            functor_name=f"F_{context_name}",
            weights=normalized,
            description="Collapse functor weights derived from shared benchmark potentialities",
        )

    return rules


def derive_duality_schema(
    params: PotentialParams | None = None,
    length: int = 80,
    baselines: Dict[str, BaselineCallable] | None = None,
) -> Tuple[PotentialLayerSpec, Dict[str, InterfaceRule], Dict[str, CollapseContext]]:
    """End-to-end derivation of potential and interface layers for analysis."""

    potential_spec, _, _ = derive_potential_layer_spec(params=params, length=length)
    contexts, _ = compare_against_normal_baselines(params=params, length=length, baselines=baselines)
    interface_rules = derive_interface_rules(params=params, length=length, baselines=baselines)
    return potential_spec, interface_rules, contexts


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
