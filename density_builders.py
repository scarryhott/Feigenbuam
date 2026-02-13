from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

Array = np.ndarray


def _symmetrize_hermitian(M: Array) -> Array:
    return 0.5 * (M + M.conjugate().T)


def coherence_from_embeddings(embeddings: Array, eps: float = 1e-12) -> Array:
    """Return a Hermitian cosine-similarity matrix from embeddings (n, d)."""
    E = np.asarray(embeddings, dtype=np.float64)
    if E.ndim != 2:
        raise ValueError("embeddings must be 2D")
    norms = np.linalg.norm(E, axis=1, keepdims=True)
    norms = np.maximum(norms, eps)
    U = E / norms
    S = U @ U.T
    return S.astype(np.complex128)


def build_rho_from_scores_and_coherence(
    scores: Dict[str, float],
    coherence: Optional[Array] = None,
    lam: float = 0.25,
    eps: float = 1e-12,
) -> Tuple[Array, Tuple[str, ...]]:
    names = tuple(scores.keys())
    a = np.array([max(float(scores[n]), 0.0) for n in names], dtype=np.float64)

    D = np.diag((a ** 2).astype(np.complex128))
    n = len(names)

    if coherence is None:
        rho = D
    else:
        C = np.asarray(coherence, dtype=np.complex128)
        if C.shape != (n, n):
            raise ValueError(f"coherence must be ({n},{n})")
        C = _symmetrize_hermitian(C)
        C = C - np.diag(np.diag(C))
        rho = D + lam * C

    rho = _symmetrize_hermitian(rho)

    w = np.linalg.eigvalsh(rho)
    min_w = float(w.min().real)
    if min_w < -1e-10:
        rho = rho + (-(min_w) + 1e-9) * np.eye(n, dtype=np.complex128)

    tr = float(np.trace(rho).real)
    if tr < eps:
        rho = np.eye(n, dtype=np.complex128) / n
    else:
        rho = rho / tr
    return rho, names


def coherence_matrix_from_named_embeddings(
    names: Sequence[str],
    embeddings: Optional[Dict[str, Sequence[float]]],
    eps: float = 1e-12,
) -> Optional[Array]:
    if not embeddings:
        return None
    matrix = []
    for name in names:
        vec = embeddings.get(name)
        if vec is None:
            return None
        matrix.append(np.asarray(vec, dtype=np.float64))
    stacked = np.stack(matrix, axis=0)
    return coherence_from_embeddings(stacked, eps=eps)


def orthonormal_basis_from_named_embeddings(
    names: Sequence[str],
    embeddings: Optional[Dict[str, Sequence[float]]],
    eps: float = 1e-12,
) -> Optional[Array]:
    """Construct an orthonormal eigenbasis derived from the embedding coherence matrix."""

    coherence = coherence_matrix_from_named_embeddings(names, embeddings, eps=eps)
    if coherence is None:
        return None

    vals, vecs = np.linalg.eigh(coherence)
    order = np.argsort(vals)[::-1]
    vecs = vecs[:, order]
    return vecs.astype(np.complex128)
