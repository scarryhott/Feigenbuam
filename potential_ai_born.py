from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from born_rule import (
    Array,
    BornContext,
    born_probs_from_projectors,
    lueders_dephase_rho,
    normalize_vec,
    probs_from_density,
    sample_index,
)


@dataclass
class PotentialAIState:
    """Carries the potential-side alignment vector psi."""

    psi: Array  # shape (d,), complex dtype recommended


@dataclass
class CollapseAIState:
    """Represents collapse-side density state after coarse graining."""

    rho: Array  # shape (d, d)


class PotentialAIBornPolicy:
    """Implements the Born-weight rule for action distributions."""

    def __init__(
        self,
        use_collapse_side: bool = False,
        rng: Optional[np.random.Generator] = None,
        collapse_projectors: Optional[Tuple[Array, ...]] = None,
    ) -> None:
        self.use_collapse_side = use_collapse_side
        self.rng = rng or np.random.default_rng()
        self.collapse_projectors = collapse_projectors

    def action_distribution(self, state: PotentialAIState, ctx: BornContext) -> np.ndarray:
        psi = normalize_vec(state.psi)
        if not self.use_collapse_side:
            return born_probs_from_projectors(psi, ctx.projectors)
        rho0 = np.outer(psi, np.conjugate(psi))
        collapse_projectors = self.collapse_projectors or ctx.projectors
        rho_c = lueders_dephase_rho(rho0, collapse_projectors)
        return probs_from_density(rho_c, ctx.projectors)

    def choose_action(self, state: PotentialAIState, ctx: BornContext, mode: str = "sample") -> int:
        probs = self.action_distribution(state, ctx)
        if mode == "argmax":
            return int(np.argmax(probs))
        return sample_index(probs, rng=self.rng)

    def update_state_after_action(
        self,
        state: PotentialAIState,
        ctx: BornContext,
        action_index: int,
        collapse: bool = True,
    ) -> PotentialAIState:
        psi = normalize_vec(state.psi)
        if not collapse:
            return PotentialAIState(psi=psi)
        P = ctx.projectors[action_index]
        new_psi = P @ psi
        if np.linalg.norm(new_psi) < 1e-12:
            return PotentialAIState(psi=psi)
        return PotentialAIState(psi=normalize_vec(new_psi))


def make_context_from_action_vectors(action_vectors: np.ndarray) -> BornContext:
    """Construct projectors from action direction vectors."""
    A = np.asarray(action_vectors, dtype=np.complex128)
    if A.ndim != 2:
        raise ValueError("action_vectors must be 2D")
    if A.shape[0] < A.shape[1]:
        vecs = [A[i, :] for i in range(A.shape[0])]
    else:
        vecs = [A[:, i] for i in range(A.shape[1])]
    projectors = []
    for v in vecs:
        v = np.asarray(v, dtype=np.complex128).reshape(-1)
        n = np.linalg.norm(v)
        if n < 1e-12:
            raise ValueError("action vector has near-zero norm")
        v = v / n
        projectors.append(np.outer(v, np.conjugate(v)))
    return BornContext(projectors=tuple(projectors))
