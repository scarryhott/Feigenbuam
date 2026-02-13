from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

Array = np.ndarray


def _as_col(x: Array) -> Array:
    x = np.asarray(x)
    if x.ndim == 1:
        return x.reshape(-1, 1)
    return x


def normalize_vec(psi: Array, eps: float = 1e-12) -> Array:
    psi = np.asarray(psi, dtype=np.complex128).reshape(-1)
    n = np.linalg.norm(psi)
    if n < eps:
        raise ValueError("Cannot normalize near-zero psi.")
    return psi / n


def projector_from_basis_vector(v: Array, eps: float = 1e-12) -> Array:
    v = np.asarray(v, dtype=np.complex128).reshape(-1)
    n = np.linalg.norm(v)
    if n < eps:
        raise ValueError("Basis vector has near-zero norm.")
    v = v / n
    return np.outer(v, np.conjugate(v))


def is_projector(P: Array, atol: float = 1e-8) -> bool:
    P = np.asarray(P)
    return (
        P.ndim == 2
        and P.shape[0] == P.shape[1]
        and np.allclose(P, P.conjugate().T, atol=atol)
        and np.allclose(P @ P, P, atol=atol)
    )


def born_probs_from_projectors(
    psi: Array,
    projectors: Sequence[Array],
    eps: float = 1e-12,
    renormalize: bool = True,
) -> Array:
    psi = np.asarray(psi, dtype=np.complex128).reshape(-1)
    denom = float(np.vdot(psi, psi).real)
    if denom < eps:
        raise ValueError("psi has near-zero norm.")
    ps: List[float] = []
    for P in projectors:
        P = np.asarray(P, dtype=np.complex128)
        if P.shape != (psi.size, psi.size):
            raise ValueError(f"Projector shape {P.shape} incompatible with psi dim {psi.size}.")
        v = P @ psi
        ps.append(float(np.vdot(v, v).real) / denom)
    p = np.array(ps, dtype=np.float64)
    if renormalize:
        s = p.sum()
        if s > eps:
            p = p / s
    return p


def born_probs_from_orthonormal_basis(
    psi: Array,
    basis: Array,
    eps: float = 1e-12,
    renormalize: bool = True,
) -> Array:
    psi_hat = normalize_vec(psi, eps=eps)
    B = np.asarray(basis, dtype=np.complex128)
    if B.ndim != 2 or B.shape[0] != psi_hat.size:
        raise ValueError("basis must be (d, k) with d = len(psi).")
    a = B.conjugate().T @ psi_hat
    p = np.abs(a) ** 2
    p = p.astype(np.float64)
    if renormalize:
        s = p.sum()
        if s > eps:
            p = p / s
    return p


def sample_index(p: Array, rng: Optional[np.random.Generator] = None) -> int:
    p = np.asarray(p, dtype=np.float64).reshape(-1)
    if rng is None:
        rng = np.random.default_rng()
    s = p.sum()
    if s <= 0:
        raise ValueError("Probability vector sums to <= 0.")
    p = p / s
    return int(rng.choice(len(p), p=p))


def lueders_dephase_rho(rho: Array, projectors: Sequence[Array]) -> Array:
    rho = np.asarray(rho, dtype=np.complex128)
    d = rho.shape[0]
    if rho.shape != (d, d):
        raise ValueError("rho must be square.")
    out = np.zeros_like(rho)
    for P in projectors:
        P = np.asarray(P, dtype=np.complex128)
        if P.shape != (d, d):
            raise ValueError("Projector shape mismatch.")
        out += P @ rho @ P
    out = 0.5 * (out + out.conjugate().T)
    return out


def probs_from_density(
    rho: Array,
    projectors: Sequence[Array],
    eps: float = 1e-12,
    renormalize: bool = True,
) -> Array:
    rho = np.asarray(rho, dtype=np.complex128)
    d = rho.shape[0]
    if rho.shape != (d, d):
        raise ValueError("rho must be square.")
    ps: List[float] = []
    for P in projectors:
        P = np.asarray(P, dtype=np.complex128)
        if P.shape != (d, d):
            raise ValueError("Projector shape mismatch.")
        ps.append(float(np.trace(rho @ P).real))
    p = np.array(ps, dtype=np.float64)
    p[p < 0] = 0.0
    if renormalize:
        s = p.sum()
        if s > eps:
            p = p / s
    return p


@dataclass(frozen=True)
class BornContext:
    projectors: Tuple[Array, ...]

    @staticmethod
    def from_orthonormal_basis(basis: Array) -> "BornContext":
        B = np.asarray(basis, dtype=np.complex128)
        d, k = B.shape
        projectors: List[Array] = []
        for i in range(k):
            projectors.append(projector_from_basis_vector(B[:, i]))
        return BornContext(projectors=tuple(projectors))
