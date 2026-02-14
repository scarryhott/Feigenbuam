"""
ivi_simplicial_grid.py

Implements an "IVI 0–∞ grid" as a simplicial complex of:
  - Statements (S): phenomenal utterances
  - Derivations (D): triangulation/inference steps
  - Equations (E): Lean/math objects ("i" pole)
  - Triangles (T): 2-simplices linking (S, D, E)

Core operations:
  - add_statement(text)
  - derive(...)  -> creates derivation nodes + equation nodes + triangles
  - patch_lean(...) -> writes/updates Lean stubs
  - build_context(query, mode) -> constructs Ω_u = Λ(Π_u(G)) and samples triangles
  - reremember(...) -> anti-collapse sampling (novelty pressure)

This is a concrete minimal stack. Derivation and Lean synthesis are stubbed behind
interfaces so you can plug in Codex/LLM later.

Storage:
  - JSONL append-only logs for each node type
  - An index file (json) for fast adjacency + metrics
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Tuple

from .openclaw_adapter import OpenClawMicrocosm

NodeType = Literal["S", "D", "E", "T"]


# =========================
# Utilities
# =========================


def _now_ts() -> float:
    return time.time()


def _stable_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def _jsonl_append(path: str, obj: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _json_read(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _json_write(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def validate_trace_backed_references(
    trace: Dict[str, Any], references: List[Dict[str, Any]]
) -> Tuple[bool, List[str]]:
    """
    Ensure every reference is grounded in the current trace.

    Currently enforced:
      - each reference.eid must exist in trace.formal_targets[*].eid
    """
    formal_targets = trace.get("formal_targets", [])
    allowed_eids = {
        target.get("eid")
        for target in formal_targets
        if isinstance(target, dict) and target.get("eid")
    }

    violations: List[str] = []
    for idx, ref in enumerate(references):
        eid = str(ref.get("eid", "")).strip()
        if not eid:
            violations.append(f"ref[{idx}] missing eid")
            continue
        if eid not in allowed_eids:
            violations.append(f"ref[{idx}] eid not in trace formal_targets: {eid}")

    return (len(violations) == 0), violations


VALIDATION_LEVELS = ["none", "smoke", "benchmark", "proof_sketch", "proof"]


def _validation_level_index(level: str) -> int:
    try:
        return VALIDATION_LEVELS.index(level)
    except ValueError:
        return -1


def _transform_impl_digest(impl_ref: str) -> str:
    # Bind claims to concrete implementation location + current source digest.
    source_path = os.path.abspath(__file__)
    with open(source_path, "rb") as f:
        source_hash = hashlib.sha256(f.read()).hexdigest()
    return hashlib.sha256(f"{impl_ref}|{source_hash}".encode("utf-8")).hexdigest()[:16]


def _feature_test_passes(trace: Dict[str, Any], feature_test: str) -> bool:
    if feature_test == "has_potential_distribution":
        return bool(trace.get("potential_distribution"))
    if feature_test == "has_collapse_selection":
        return bool(trace.get("collapse_selection"))
    if feature_test == "has_formal_targets":
        return bool(trace.get("formal_targets"))
    return False


def evaluate_regime_feature_tests(trace: Dict[str, Any], claim: Dict[str, Any]) -> Dict[str, Any]:
    regime = claim.get("regime_assumptions", {}) if isinstance(claim, dict) else {}
    feature_tests = regime.get("feature_tests", []) if isinstance(regime, dict) else []

    failures: List[str] = []
    for ft in feature_tests:
        if not _feature_test_passes(trace, str(ft)):
            failures.append(str(ft))

    return {
        "name": "regime_feature_tests",
        "enabled": True,
        "passed": len(failures) == 0,
        "failed_tests": failures,
    }


def evaluate_validation_promotion_level(current_level: str, previous_level: Optional[str]) -> Dict[str, Any]:
    curr_idx = _validation_level_index(current_level)
    prev_idx = _validation_level_index(previous_level) if previous_level is not None else -1

    if curr_idx < 0:
        return {
            "name": "validation_promotion",
            "enabled": True,
            "passed": False,
            "detail": f"Unknown validation level: {current_level}",
        }

    if previous_level is not None and prev_idx >= 0 and curr_idx < prev_idx:
        return {
            "name": "validation_promotion",
            "enabled": True,
            "passed": False,
            "detail": f"Validation level downgrade not allowed: {previous_level} -> {current_level}",
        }

    return {
        "name": "validation_promotion",
        "enabled": True,
        "passed": True,
        "detail": f"Validation level accepted: {current_level}",
    }


def run_complexity_counterexample_search(trace: Dict[str, Any], claim: Dict[str, Any]) -> Dict[str, Any]:
    """
    Lightweight adversarial hook: try candidate traces that may expose a mismatch
    between in-regime checks and claim requirements.
    """
    regime_eval = evaluate_regime_feature_tests(trace, claim)
    if not regime_eval.get("passed", False):
        return {
            "name": "counterexample_search",
            "enabled": True,
            "passed": True,
            "checked": 0,
            "detail": "Skipped: current trace is out-of-regime.",
        }

    base_candidates = [
        {
            "name": "drop_formal_targets",
            "trace": {**trace, "formal_targets": []},
        },
        {
            "name": "drop_collapse_selection",
            "trace": {**trace, "collapse_selection": []},
        },
    ]

    checked = 0
    for candidate in base_candidates:
        cand_trace = candidate["trace"]
        in_regime = evaluate_regime_feature_tests(cand_trace, claim).get("passed", False)
        # Claim-holds proxy for NP_R_subset_P runs in this scaffold.
        claim_holds = bool(cand_trace.get("potential_distribution") and cand_trace.get("collapse_selection") and cand_trace.get("formal_targets"))
        checked += 1
        if in_regime and not claim_holds:
            return {
                "name": "counterexample_search",
                "enabled": True,
                "passed": False,
                "checked": checked,
                "detail": "Found in-regime violating candidate.",
                "counterexample": {"candidate": candidate["name"]},
            }

    return {
        "name": "counterexample_search",
        "enabled": True,
        "passed": True,
        "checked": checked,
        "detail": "No violating in-regime candidate found in lightweight search.",
    }


def build_triangle_time_choice_artifact(trace: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build triangle-time choice operator artifact over the current connection state.

    Choice is represented as refinement of connectivity, not flat option selection.
    """
    potential_tids = [
        str(entry.get("tid"))
        for entry in trace.get("potential_distribution", [])
        if isinstance(entry, dict) and entry.get("tid")
    ]
    collapse_tids = [str(tid) for tid in trace.get("collapse_selection", [])]
    alternatives = [tid for tid in potential_tids if tid not in set(collapse_tids)]

    role_ok, role_violations = validate_role_exchange_trace_consistency(trace)

    return {
        "RefinementApplied": "triangle_time_refinement_transform_v1",
        "Delta": {
            "added_triangle_tids": collapse_tids,
            "added_triangle_count": len(collapse_tids),
            "potential_triangle_count": len(potential_tids),
        },
        "Witness": {
            "integrity_checks": {
                "has_potential_distribution": bool(trace.get("potential_distribution")),
                "has_collapse_selection": bool(collapse_tids),
                "has_formal_targets": bool(trace.get("formal_targets")),
                "role_exchange_consistent": role_ok,
            },
            "violations": role_violations,
        },
        "Alternatives": alternatives,
    }


def validate_triangle_time_choice_artifact(artifact: Dict[str, Any]) -> Tuple[bool, List[str]]:
    violations: List[str] = []

    if not isinstance(artifact, dict):
        return False, ["triangle_time choice artifact must be a mapping"]

    refinement_applied = str(artifact.get("RefinementApplied", "")).strip()
    delta = artifact.get("Delta")
    witness = artifact.get("Witness")
    alternatives = artifact.get("Alternatives")

    if not refinement_applied:
        violations.append("RefinementApplied missing")
    if not isinstance(delta, dict):
        violations.append("Delta must be a mapping")
    else:
        added = delta.get("added_triangle_tids")
        if not isinstance(added, list):
            violations.append("Delta.added_triangle_tids must be a list")
    if not isinstance(witness, dict):
        violations.append("Witness must be a mapping")
    else:
        checks = witness.get("integrity_checks")
        if not isinstance(checks, dict):
            violations.append("Witness.integrity_checks must be a mapping")
    if not isinstance(alternatives, list):
        violations.append("Alternatives must be a list")

    return (len(violations) == 0), violations


def evaluate_p_np_state_check_option(claim: Dict[str, Any]) -> Dict[str, Any]:
    """
    Order-1 state check option for complexity claims.

    This check is intentionally regime-conditioned: it allows restricted
    NP_R subset P claims and rejects global P=NP claims.
    """
    claim_type = str(claim.get("claim_type", "")).strip()
    normalized = claim_type.lower().replace(" ", "")

    if normalized in {"p=np", "global_p_eq_np"}:
        return {
            "name": "p_np_state_check",
            "enabled": True,
            "mode": "restricted_regime_only",
            "passed": False,
            "detail": "Global P=NP claim rejected; use representation-conditioned NP_R subset P.",
        }

    if claim_type == "NP_R_subset_P":
        return {
            "name": "p_np_state_check",
            "enabled": True,
            "mode": "restricted_regime_only",
            "passed": True,
            "detail": "Representation-conditioned complexity claim accepted.",
        }

    return {
        "name": "p_np_state_check",
        "enabled": True,
        "mode": "restricted_regime_only",
        "passed": False,
        "detail": "Unsupported claim_type for Order-1 p_np_state_check option.",
    }


def _validate_role_projection_structure(trace: Dict[str, Any], projection: Dict[str, Any]) -> List[str]:
    violations: List[str] = []

    collapse = [str(tid) for tid in trace.get("collapse_selection", [])]
    collapse_set = set(collapse)
    potential_set = {str(entry.get("tid")) for entry in trace.get("potential_distribution", []) if entry.get("tid")}

    subject_tids = [str(tid) for tid in projection.get("subject_tids", [])]
    object_tids = [str(tid) for tid in projection.get("object_tids", [])]

    sub_set = set(subject_tids)
    obj_set = set(object_tids)

    if sub_set & obj_set:
        violations.append("role_projection overlap between subject_tids and object_tids")
    if (sub_set | obj_set) != collapse_set:
        violations.append("role_projection union does not match collapse_selection")

    missing_from_potential = [tid for tid in (subject_tids + object_tids) if tid not in potential_set]
    if missing_from_potential:
        violations.append("role_projection tids missing from potential_distribution")

    if len(collapse) >= 2 and (not subject_tids or not object_tids):
        violations.append("role_projection must populate both subject_tids and object_tids for multi-selection trace")

    return violations


def validate_role_exchange_trace_consistency(trace: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Practical proxy for self-dual commutation in runtime traces.

    We enforce that role projections are structurally valid and remain valid
    under subject/object role exchange.
    """
    projection = trace.get("role_projection", {})
    if not isinstance(projection, dict):
        return False, ["trace.role_projection must be a mapping"]

    violations = _validate_role_projection_structure(trace, projection)

    swapped_projection = {
        "subject_tids": list(projection.get("object_tids", [])),
        "object_tids": list(projection.get("subject_tids", [])),
    }
    swapped_violations = _validate_role_projection_structure(trace, swapped_projection)
    violations.extend([f"swap_check: {v}" for v in swapped_violations])

    return (len(violations) == 0), violations


def validate_complexity_claim_schema(claim: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Enforce representation-conditioned complexity claims.

    We allow restricted claims (e.g., NP_R subset P) but reject global P=NP assertions.
    """
    violations: List[str] = []

    if not isinstance(claim, dict):
        return False, ["complexity_claim must be a mapping"]

    claim_type = str(claim.get("claim_type", "")).strip()
    regime = claim.get("regime_assumptions")
    transform = claim.get("transform")
    validation = claim.get("validation")

    if not claim_type:
        violations.append("complexity_claim.claim_type missing")
    elif claim_type.lower().replace(" ", "") in {"p=np", "global_p_eq_np"}:
        violations.append("global P=NP claims are not allowed; use restricted regime claim")

    if not isinstance(regime, dict):
        violations.append("complexity_claim.regime_assumptions must be a mapping")
    else:
        constraints = regime.get("constraints")
        instance_family = str(regime.get("instance_family", "")).strip()
        feature_tests = regime.get("feature_tests")
        if not isinstance(constraints, list) or not constraints or not all(str(x).strip() for x in constraints):
            violations.append("complexity_claim.regime_assumptions.constraints must be a non-empty list")
        if not instance_family:
            violations.append("complexity_claim.regime_assumptions.instance_family missing")
        if not isinstance(feature_tests, list) or not feature_tests or not all(str(x).strip() for x in feature_tests):
            violations.append("complexity_claim.regime_assumptions.feature_tests must be a non-empty list")

    if not isinstance(transform, dict):
        violations.append("complexity_claim.transform must be a mapping")
    else:
        name = str(transform.get("name", "")).strip()
        impl_ref = str(transform.get("impl_ref", "")).strip()
        digest = str(transform.get("digest", "")).strip()
        if not name:
            violations.append("complexity_claim.transform.name missing")
        if not impl_ref:
            violations.append("complexity_claim.transform.impl_ref missing")
        if not digest:
            violations.append("complexity_claim.transform.digest missing")

    if not isinstance(validation, dict):
        violations.append("complexity_claim.validation must be a mapping")
    else:
        level = str(validation.get("level", "")).strip()
        suite = str(validation.get("benchmark_suite", "")).strip()
        status = str(validation.get("status", "")).strip()
        if level not in VALIDATION_LEVELS:
            violations.append(f"complexity_claim.validation.level must be one of {VALIDATION_LEVELS}")
        if not suite:
            violations.append("complexity_claim.validation.benchmark_suite missing")
        if not status:
            violations.append("complexity_claim.validation.status missing")

    return (len(violations) == 0), violations


def _tokenize(text: str) -> List[str]:
    # lightweight tokenizer: lowercase words/numbers, keep apostrophes inside words
    return re.findall(r"[a-z0-9']+", text.lower())


def _tf(text: str) -> Dict[str, float]:
    toks = _tokenize(text)
    if not toks:
        return {}
    d: Dict[str, float] = {}
    for t in toks:
        d[t] = d.get(t, 0.0) + 1.0
    inv = 1.0 / float(len(toks))
    for k in list(d.keys()):
        d[k] *= inv
    return d


def _cosine_sparse(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    # dot
    dot = 0.0
    for k, va in a.items():
        vb = b.get(k)
        if vb is not None:
            dot += va * vb
    # norms
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# =========================
# Node schemas
# =========================


@dataclass(frozen=True)
class Statement:
    sid: str
    text: str
    created_ts: float
    source: str  # "voice" | "chat" | etc.
    tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# =========================
# Reflexive refinement (rule-in-state)
# =========================


Edge = Tuple[str, str]
ReflexiveRuleKind = Literal["transitive", "symmetry"]


@dataclass(frozen=True)
class ReflexiveConnection:
    edges: frozenset[Edge]

    def add_edges(self, new_edges: Set[Edge]) -> "ReflexiveConnection":
        return ReflexiveConnection(edges=frozenset(set(self.edges) | set(new_edges)))


@dataclass(frozen=True)
class ReflexiveRule:
    kind: ReflexiveRuleKind
    enabled: bool = True

    def digest(self) -> str:
        blob = json.dumps({"kind": self.kind, "enabled": self.enabled}, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16]


@dataclass(frozen=True)
class ReflexiveIntegritySchema:
    monotone_edges: bool = True
    monotone_rules: bool = True
    allowed_rule_kinds: frozenset[ReflexiveRuleKind] = frozenset({"transitive", "symmetry"})

    def allows_rule(self, r: ReflexiveRule) -> bool:
        return r.kind in self.allowed_rule_kinds and r.enabled is True


@dataclass(frozen=True)
class ReflexiveDelta:
    add_edges: frozenset[Edge] = frozenset()
    add_rules: Tuple[ReflexiveRule, ...] = ()


@dataclass(frozen=True)
class ReflexiveWitness:
    ok: bool
    reasons: Tuple[str, ...]
    prior_state_digest: str
    delta_digest: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reasons": list(self.reasons),
            "prior_state_digest": self.prior_state_digest,
            "delta_digest": self.delta_digest,
        }


@dataclass(frozen=True)
class ReflexiveState:
    C: ReflexiveConnection
    R: Tuple[ReflexiveRule, ...]
    Sigma: ReflexiveIntegritySchema


def _digest_reflexive_state(S: ReflexiveState) -> str:
    blob = json.dumps(
        {
            "edges": sorted([list(e) for e in S.C.edges]),
            "rules": [{"kind": r.kind, "enabled": r.enabled, "digest": r.digest()} for r in S.R],
            "schema": {
                "monotone_edges": S.Sigma.monotone_edges,
                "monotone_rules": S.Sigma.monotone_rules,
                "allowed_rule_kinds": sorted(list(S.Sigma.allowed_rule_kinds)),
            },
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _digest_reflexive_delta(d: ReflexiveDelta) -> str:
    blob = json.dumps(
        {
            "add_edges": sorted([list(e) for e in d.add_edges]),
            "add_rules": [{"kind": r.kind, "enabled": r.enabled, "digest": r.digest()} for r in d.add_rules],
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _propose_reflexive_deltas(S: ReflexiveState) -> List[ReflexiveDelta]:
    candidates: List[ReflexiveDelta] = []
    edges = set(S.C.edges)
    rules = S.R

    if any(r.kind == "transitive" and r.enabled for r in rules):
        new_edges: Set[Edge] = set()
        for (a, b) in edges:
            for (b2, c) in edges:
                if b == b2:
                    e = (a, c)
                    if e not in edges:
                        new_edges.add(e)
        if new_edges:
            candidates.append(ReflexiveDelta(add_edges=frozenset(new_edges)))

    if any(r.kind == "symmetry" and r.enabled for r in rules):
        new_edges = {(b, a) for (a, b) in edges if (b, a) not in edges}
        if new_edges:
            candidates.append(ReflexiveDelta(add_edges=frozenset(new_edges)))

    if all(r.kind != "symmetry" for r in rules):
        candidate_rule = ReflexiveRule(kind="symmetry", enabled=True)
        if S.Sigma.allows_rule(candidate_rule):
            candidates.append(ReflexiveDelta(add_rules=(candidate_rule,)))

    return candidates


def _select_reflexive_delta(candidates: List[ReflexiveDelta]) -> Optional[ReflexiveDelta]:
    if not candidates:
        return None

    def score(d: ReflexiveDelta) -> Tuple[int, int]:
        return (len(d.add_edges), len(d.add_rules))

    return sorted(candidates, key=score, reverse=True)[0]


def _check_reflexive_delta(S: ReflexiveState, d: ReflexiveDelta) -> ReflexiveWitness:
    reasons: List[str] = []
    ok = True

    if S.Sigma.monotone_edges:
        reasons.append("monotone_edges: ok")

    if S.Sigma.monotone_rules:
        for r in d.add_rules:
            if not S.Sigma.allows_rule(r):
                ok = False
                reasons.append(f"monotone_rules: rejected rule kind={r.kind}")
        reasons.append("monotone_rules: ok")

    if len(d.add_edges) == 0 and len(d.add_rules) == 0:
        ok = False
        reasons.append("non_fabrication: rejected empty delta")

    return ReflexiveWitness(
        ok=ok,
        reasons=tuple(reasons),
        prior_state_digest=_digest_reflexive_state(S),
        delta_digest=_digest_reflexive_delta(d),
    )


def _commit_reflexive_delta(S: ReflexiveState, d: ReflexiveDelta, w: ReflexiveWitness) -> ReflexiveState:
    if not w.ok:
        raise ValueError("invalid reflexive delta")
    C2 = S.C.add_edges(set(d.add_edges))
    R2 = tuple(list(S.R) + list(d.add_rules))
    return ReflexiveState(C=C2, R=R2, Sigma=S.Sigma)


def run_reflexive_refinement_step(S: ReflexiveState) -> Dict[str, Any]:
    candidates = _propose_reflexive_deltas(S)
    selected = _select_reflexive_delta(candidates)

    if selected is None:
        w = ReflexiveWitness(
            ok=True,
            reasons=("no_candidates: fixed_point",),
            prior_state_digest=_digest_reflexive_state(S),
            delta_digest=_digest_reflexive_delta(ReflexiveDelta()),
        )
        return {
            "ok": True,
            "state": S,
            "witness": w,
            "delta": ReflexiveDelta(),
            "candidates": 0,
            "fixed_point": True,
        }

    w = _check_reflexive_delta(S, selected)
    if not w.ok:
        return {
            "ok": False,
            "state": S,
            "witness": w,
            "delta": selected,
            "candidates": len(candidates),
            "fixed_point": False,
            "gap_code": "reflexive_refinement_invalid",
            "gap_detail": "; ".join(w.reasons),
        }

    S2 = _commit_reflexive_delta(S, selected, w)
    return {
        "ok": True,
        "state": S2,
        "witness": w,
        "delta": selected,
        "candidates": len(candidates),
        "fixed_point": False,
    }


def build_reflexive_state_from_trace(trace: Dict[str, Any]) -> ReflexiveState:
    collapse = [str(tid) for tid in trace.get("collapse_selection", [])]
    formal = [str(t.get("eid")) for t in trace.get("formal_targets", []) if isinstance(t, dict) and t.get("eid")]

    edges: Set[Edge] = set()
    for tid in collapse:
        edges.add(("trace", tid))
    for tid, eid in zip(collapse, formal):
        edges.add((tid, eid))

    state = ReflexiveState(
        C=ReflexiveConnection(edges=frozenset(edges)),
        R=(ReflexiveRule(kind="transitive", enabled=True),),
        Sigma=ReflexiveIntegritySchema(),
    )
    return state


def reflexive_step_payload(step: Dict[str, Any]) -> Dict[str, Any]:
    witness = step.get("witness")
    delta = step.get("delta")
    state = step.get("state")
    if not isinstance(witness, ReflexiveWitness) or not isinstance(delta, ReflexiveDelta) or not isinstance(state, ReflexiveState):
        return {}

    return {
        "ok": bool(step.get("ok", False)),
        "candidates": int(step.get("candidates", 0)),
        "fixed_point": bool(step.get("fixed_point", False)),
        "witness": witness.to_dict(),
        "delta": {
            "add_edges": [list(e) for e in sorted(list(delta.add_edges))],
            "add_rules": [{"kind": r.kind, "enabled": r.enabled, "digest": r.digest()} for r in delta.add_rules],
        },
        "state_digest": _digest_reflexive_state(state),
    }


@dataclass(frozen=True)
class Derivation:
    did: str
    rule: str  # e.g. "implication-extract", "rewrite", "bridge"
    premises: List[str]  # IDs: sid/eid (strings)
    conclusions: List[str]  # IDs: sid/eid
    notes: str
    created_ts: float

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class Equation:
    eid: str
    lean_name: str
    lean_file: str
    statement: str  # human-readable statement of lemma/theorem
    version_hash: str
    created_ts: float

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class Triangle:
    tid: str
    sid: str
    did: str
    eid: str
    created_ts: float

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# =========================
# Index / adjacency
# =========================


@dataclass
class GridIndex:
    # node registries
    statements: Dict[str, Dict[str, Any]]
    derivations: Dict[str, Dict[str, Any]]
    equations: Dict[str, Dict[str, Any]]
    triangles: Dict[str, Dict[str, Any]]

    # adjacency
    # sid -> set(tid)
    sid_to_tids: Dict[str, List[str]]
    # eid -> set(tid)
    eid_to_tids: Dict[str, List[str]]
    # did -> set(tid)
    did_to_tids: Dict[str, List[str]]

    # edges / dependencies (graph)
    # node -> neighbors (IDs)
    neighbors: Dict[str, List[str]]

    # lightweight text features for similarity selection
    tf_s: Dict[str, Dict[str, float]]  # sid -> tf
    tf_e: Dict[str, Dict[str, float]]  # eid -> tf (from equation.statement)
    tf_d: Dict[str, Dict[str, float]]  # did -> tf (from notes/rule)

    # anti-collapse trace
    recent_triangle_trace: List[str]  # list of tids (most recent last)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def empty() -> "GridIndex":
        return GridIndex(
            statements={},
            derivations={},
            equations={},
            triangles={},
            sid_to_tids={},
            eid_to_tids={},
            did_to_tids={},
            neighbors={},
            tf_s={},
            tf_e={},
            tf_d={},
            recent_triangle_trace=[],
        )


# =========================
# Core grid
# =========================


class IVISimplicialGrid:
    """
    Persistent IVI simplicial grid:
      - JSONL logs for append-only durability
      - index.json for fast lookups + adjacency

    Directory structure:
      base_dir/
        data/
          statements.jsonl
          derivations.jsonl
          equations.jsonl
          triangles.jsonl
          index.json
        lean/
          Derived/
            <auto>.lean
    """

    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        self.data_dir = os.path.join(self.base_dir, "data")
        self.lean_dir = os.path.join(self.base_dir, "lean")
        self.lean_derived_dir = os.path.join(self.lean_dir, "Derived")

        _ensure_dir(self.data_dir)
        _ensure_dir(self.lean_derived_dir)

        self.paths = {
            "S": os.path.join(self.data_dir, "statements.jsonl"),
            "D": os.path.join(self.data_dir, "derivations.jsonl"),
            "E": os.path.join(self.data_dir, "equations.jsonl"),
            "T": os.path.join(self.data_dir, "triangles.jsonl"),
            "IDX": os.path.join(self.data_dir, "index.json"),
        }

        self.idx: GridIndex = self._load_index()

    # -------------
    # Persistence
    # -------------

    def _load_index(self) -> GridIndex:
        d = _json_read(self.paths["IDX"], None)
        if d is None:
            return GridIndex.empty()
        # dataclass reconstruction
        return GridIndex(**d)

    def _save_index(self) -> None:
        _json_write(self.paths["IDX"], self.idx.to_dict())

    # -------------
    # Add nodes
    # -------------

    def add_statement(
        self,
        text: str,
        source: str = "voice",
        tags: Optional[List[str]] = None,
    ) -> Statement:
        text = text.strip()
        if not text:
            raise ValueError("Statement text is empty.")

        sid = "S_" + _stable_hash(f"{_now_ts()}|{source}|{text}")
        st = Statement(
            sid=sid,
            text=text,
            created_ts=_now_ts(),
            source=source,
            tags=tags or [],
        )

        # persist
        _jsonl_append(self.paths["S"], st.to_dict())

        # index
        self.idx.statements[sid] = st.to_dict()
        self.idx.sid_to_tids.setdefault(sid, [])
        self.idx.neighbors.setdefault(sid, [])
        self.idx.tf_s[sid] = _tf(text)

        self._save_index()
        return st

    def add_equation(
        self,
        lean_name: str,
        statement: str,
        lean_file: Optional[str] = None,
    ) -> Equation:
        statement = statement.strip()
        if not statement:
            raise ValueError("Equation statement is empty.")

        # ensure a stable file mapping
        if lean_file is None:
            lean_file = os.path.join(self.lean_derived_dir, "AutoDerived.lean")
        else:
            # allow relative
            if not os.path.isabs(lean_file):
                lean_file = os.path.join(self.lean_derived_dir, lean_file)

        base = f"{lean_name}|{statement}|{lean_file}"
        eid = "E_" + _stable_hash(base)
        ver = _stable_hash(base + "|v1")

        eq = Equation(
            eid=eid,
            lean_name=lean_name,
            lean_file=lean_file,
            statement=statement,
            version_hash=ver,
            created_ts=_now_ts(),
        )

        # persist
        _jsonl_append(self.paths["E"], eq.to_dict())

        # index
        self.idx.equations[eid] = eq.to_dict()
        self.idx.eid_to_tids.setdefault(eid, [])
        self.idx.neighbors.setdefault(eid, [])
        self.idx.tf_e[eid] = _tf(statement)

        self._save_index()
        return eq

    def add_derivation(
        self,
        rule: str,
        premises: List[str],
        conclusions: List[str],
        notes: str = "",
    ) -> Derivation:
        rule = rule.strip() or "derivation"
        did = "D_" + _stable_hash(f"{_now_ts()}|{rule}|{premises}|{conclusions}|{notes}")

        dv = Derivation(
            did=did,
            rule=rule,
            premises=premises,
            conclusions=conclusions,
            notes=notes,
            created_ts=_now_ts(),
        )

        # persist
        _jsonl_append(self.paths["D"], dv.to_dict())

        # index
        self.idx.derivations[did] = dv.to_dict()
        self.idx.did_to_tids.setdefault(did, [])
        self.idx.neighbors.setdefault(did, [])
        self.idx.tf_d[did] = _tf(f"{rule} {notes}")

        # dependency edges (neighbors)
        for p in premises:
            self._add_neighbor(did, p)
            self._add_neighbor(p, did)
        for c in conclusions:
            self._add_neighbor(did, c)
            self._add_neighbor(c, did)

        self._save_index()
        return dv

    def add_triangle(self, sid: str, did: str, eid: str) -> Triangle:
        if sid not in self.idx.statements:
            raise KeyError(f"Unknown sid: {sid}")
        if did not in self.idx.derivations:
            raise KeyError(f"Unknown did: {did}")
        if eid not in self.idx.equations:
            raise KeyError(f"Unknown eid: {eid}")

        tid = "T_" + _stable_hash(f"{sid}|{did}|{eid}|{_now_ts()}")
        tr = Triangle(tid=tid, sid=sid, did=did, eid=eid, created_ts=_now_ts())

        _jsonl_append(self.paths["T"], tr.to_dict())

        self.idx.triangles[tid] = tr.to_dict()
        self.idx.sid_to_tids.setdefault(sid, []).append(tid)
        self.idx.did_to_tids.setdefault(did, []).append(tid)
        self.idx.eid_to_tids.setdefault(eid, []).append(tid)

        # triangle adjacency edges: connect all three endpoints
        self._add_neighbor(sid, did)
        self._add_neighbor(did, sid)
        self._add_neighbor(did, eid)
        self._add_neighbor(eid, did)
        self._add_neighbor(sid, eid)
        self._add_neighbor(eid, sid)

        self._save_index()
        return tr

    def _add_neighbor(self, a: str, b: str) -> None:
        if a not in self.idx.neighbors:
            self.idx.neighbors[a] = []
        if b not in self.idx.neighbors[a]:
            self.idx.neighbors[a].append(b)

    # =========================
    # Derivation + Lean emission (pluggable)
    # =========================

    def derive_phase1_minimal(self, sid: str) -> Dict[str, Any]:
        """
        Minimal deterministic derivation:
          - creates one Equation E as a Lean lemma stub name derived from statement
          - creates one Derivation D linking sid -> eid
          - creates one Triangle (sid, did, eid)
          - writes/updates Lean stub file
        This is a scaffold. Replace this with your real implication extractor.

        Returns dict with created ids.
        """
        st = self.idx.statements.get(sid)
        if st is None:
            raise KeyError(f"Unknown sid: {sid}")

        text = st["text"]
        lean_name = self._lean_name_from_text(text)
        eq_stmt = self._equation_statement_from_text(text)

        eq = self.add_equation(lean_name=lean_name, statement=eq_stmt)
        dv = self.add_derivation(
            rule="phase1_stub_implication",
            premises=[sid],
            conclusions=[eq.eid],
            notes="Minimal scaffold: treat statement as candidate lemma statement.",
        )
        tr = self.add_triangle(sid=sid, did=dv.did, eid=eq.eid)

        # Lean patch
        self.patch_lean_stub(eq)

        # update trace (anti-collapse)
        self._trace_triangle(tr.tid)

        return {"sid": sid, "eid": eq.eid, "did": dv.did, "tid": tr.tid}

    def patch_lean_stub(self, eq: Equation) -> None:
        """
        Writes/updates a Lean file with a lemma stub for the equation.

        Policy:
          - Ensure file exists and has a header.
          - Insert/replace a marked block for this equation id.
        """
        path = eq.lean_file
        _ensure_dir(os.path.dirname(path))

        header = (
            "-- Auto-generated by IVISimplicialGrid\n"
            "-- This file is a scaffold; replace stubs with real formalizations.\n\n"
        )
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(header)

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        block_start = f"-- >>> IVI_EQUATION {eq.eid} BEGIN\n"
        block_end = f"-- <<< IVI_EQUATION {eq.eid} END\n"

        lemma_stub = self._lean_lemma_stub(eq.lean_name, eq.statement)
        new_block = block_start + lemma_stub + "\n" + block_end

        if block_start in content and block_end in content:
            # replace existing block
            pre, rest = content.split(block_start, 1)
            _, post = rest.split(block_end, 1)
            content2 = pre + new_block + post
        else:
            # append at end
            content2 = content.rstrip() + "\n\n" + new_block + "\n"

        with open(path, "w", encoding="utf-8") as f:
            f.write(content2)

    def _lean_name_from_text(self, text: str) -> str:
        toks = _tokenize(text)
        if not toks:
            return "ivi_stmt"
        # lean identifier: start with letter, then alnum/underscore
        base = "_".join(toks[:8])
        base = re.sub(r"[^a-z0-9_]", "_", base.lower())
        if not re.match(r"^[a-z_]", base):
            base = "ivi_" + base
        return base[:60]

    def _equation_statement_from_text(self, text: str) -> str:
        # You can replace this with a real “implication extractor”
        # For now: treat the statement as a proposition label.
        # Keep it short to avoid dumping long prose into Lean.
        t = text.strip()
        if len(t) > 180:
            t = t[:177] + "..."
        return f"Proposition derived from: {t}"

    def _lean_lemma_stub(self, lean_name: str, statement: str) -> str:
        # This is intentionally simple; you will later generate real Lean.
        # The 'statement' is kept as a docstring; the lemma itself is `True` for now.
        return (
            f"/-- {statement} -/\n"
            f"theorem {lean_name} : True := by\n"
            f"  trivial\n"
        )

    # =========================
    # Ω_u = Λ(Π_u(G)) : Context building over triangles
    # =========================

    def build_context(
        self,
        query: str,
        mode: Literal["statement", "question", "derive", "lean"] = "question",
        max_triangles: int = 16,
        closure_hops: int = 2,
        novelty_lambda: float = 1.2,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Returns a context packet (Ω_u) as sampled triangles plus their incident nodes.

        Π_u(G): selects candidate triangles by stance alignment (query/mode).
        Λ(...): expands locally in the neighbor graph to pull supporting triangles.

        Anti-collapse: penalize recently used triangles.
        """
        if seed is not None:
            random.seed(seed)

        q_tf = _tf(f"{mode} {query}")

        # 1) Candidate triangles: score by relevance of (S,E,D) texts
        tri_scores: List[Tuple[str, float]] = []
        for tid, tr in self.idx.triangles.items():
            sid = tr["sid"]
            eid = tr["eid"]
            did = tr["did"]

            s_score = _cosine_sparse(q_tf, self.idx.tf_s.get(sid, {}))
            e_score = _cosine_sparse(q_tf, self.idx.tf_e.get(eid, {}))
            d_score = _cosine_sparse(q_tf, self.idx.tf_d.get(did, {}))

            # base relevance: max or blend
            base = 0.55 * max(s_score, e_score) + 0.45 * d_score

            # novelty penalty from trace frequency
            freq = self._trace_freq(tid)
            novelty_pen = math.exp(-novelty_lambda * freq)

            score = base * novelty_pen
            if score > 0.0:
                tri_scores.append((tid, score))

        tri_scores.sort(key=lambda x: x[1], reverse=True)

        # If empty, fall back to most recent triangles (still novelty-penalized)
        if not tri_scores:
            fallback = list(self.idx.triangles.keys())[-min(64, len(self.idx.triangles)) :]
            for tid in fallback:
                base = 0.05
                freq = self._trace_freq(tid)
                novelty_pen = math.exp(-novelty_lambda * freq)
                tri_scores.append((tid, base * novelty_pen))
            tri_scores.sort(key=lambda x: x[1], reverse=True)

        # Π_u: take top-K candidates before closure
        top = tri_scores[: max(8, max_triangles * 3)]

        # 2) Λ closure: expand around selected triangles by walking neighbor graph
        selected_tids: Set[str] = set(tid for tid, _ in top[:max_triangles])
        frontier_nodes: Set[str] = set()
        for tid in selected_tids:
            tr = self.idx.triangles[tid]
            frontier_nodes.update([tr["sid"], tr["did"], tr["eid"]])

        for _ in range(closure_hops):
            next_nodes: Set[str] = set()
            for n in frontier_nodes:
                for nb in self.idx.neighbors.get(n, []):
                    next_nodes.add(nb)
            frontier_nodes |= next_nodes

            # pull triangles incident to any frontier node
            for n in list(frontier_nodes):
                if n.startswith("S_"):
                    for tid in self.idx.sid_to_tids.get(n, []):
                        selected_tids.add(tid)
                elif n.startswith("D_"):
                    for tid in self.idx.did_to_tids.get(n, []):
                        selected_tids.add(tid)
                elif n.startswith("E_"):
                    for tid in self.idx.eid_to_tids.get(n, []):
                        selected_tids.add(tid)

        # 3) Sample triangles from selected_tids using Born-like weights:
        # amplitudes a_i := score_i, probabilities p_i ∝ |a_i|^2
        # (here scores are real, so |a|^2 = a^2)
        weight_map: Dict[str, float] = {}
        score_map = dict(tri_scores)

        for tid in selected_tids:
            s = score_map.get(tid, 0.01)
            weight_map[tid] = s * s

        potential_probs = self._normalize_weights(weight_map)

        sampled_tids = self._sample_weighted_without_replacement(
            weight_map, k=min(max_triangles, len(weight_map))
        )

        # update trace
        for tid in sampled_tids:
            self._trace_triangle(tid)

        # 4) Gather incident nodes (S,D,E) for the packet
        packet = self._context_packet_from_triangles(sampled_tids)

        potential_top = sorted(potential_probs.items(), key=lambda x: x[1], reverse=True)[:16]
        formal_targets: List[Dict[str, str]] = []
        for tid in sampled_tids:
            tri = self.idx.triangles.get(tid)
            if not tri:
                continue
            eq = self.idx.equations.get(tri["eid"])
            if not eq:
                continue
            formal_targets.append(
                {
                    "eid": eq["eid"],
                    "lean_name": eq["lean_name"],
                    "lean_file": eq["lean_file"],
                }
            )

        # include meta
        packet["meta"] = {
            "mode": mode,
            "query": query,
            "max_triangles": max_triangles,
            "closure_hops": closure_hops,
            "novelty_lambda": novelty_lambda,
            "potential_distribution": [{"tid": tid, "p": p} for tid, p in potential_top],
            "collapse_selection": sampled_tids,
            "formal_targets": formal_targets,
            "sampled_tids": sampled_tids,
        }

        self._save_index()
        return packet

    def _context_packet_from_triangles(self, tids: List[str]) -> Dict[str, Any]:
        sids: Set[str] = set()
        dids: Set[str] = set()
        eids: Set[str] = set()

        tris: List[Dict[str, Any]] = []
        for tid in tids:
            tr = self.idx.triangles[tid]
            sids.add(tr["sid"])
            dids.add(tr["did"])
            eids.add(tr["eid"])
            tris.append(tr)

        statements = [self.idx.statements[sid] for sid in sids if sid in self.idx.statements]
        derivations = [self.idx.derivations[did] for did in dids if did in self.idx.derivations]
        equations = [self.idx.equations[eid] for eid in eids if eid in self.idx.equations]

        # sort by time
        statements.sort(key=lambda x: x.get("created_ts", 0.0))
        derivations.sort(key=lambda x: x.get("created_ts", 0.0))
        equations.sort(key=lambda x: x.get("created_ts", 0.0))

        return {
            "triangles": tris,
            "statements": statements,
            "derivations": derivations,
            "equations": equations,
        }

    # =========================
    # Anti-collapse trace
    # =========================

    def _trace_triangle(self, tid: str, max_len: int = 256) -> None:
        self.idx.recent_triangle_trace.append(tid)
        if len(self.idx.recent_triangle_trace) > max_len:
            self.idx.recent_triangle_trace = self.idx.recent_triangle_trace[-max_len:]

    def _trace_freq(self, tid: str, window: int = 128) -> float:
        # frequency in last `window` selections
        tr = self.idx.recent_triangle_trace[-window:]
        if not tr:
            return 0.0
        return float(sum(1 for x in tr if x == tid)) / float(len(tr))

    # =========================
    # Weighted sampling utilities
    # =========================

    def _sample_weighted_without_replacement(self, weights: Dict[str, float], k: int) -> List[str]:
        items = list(weights.items())
        # filter nonpositive
        items = [(i, w) for i, w in items if w > 0.0]
        if not items or k <= 0:
            return []

        # Efraimidis–Spirakis sampling without replacement
        # key = u^(1/w)
        scored: List[Tuple[float, str]] = []
        for item, w in items:
            u = random.random()
            key = u ** (1.0 / w)
            scored.append((key, item))
        scored.sort(reverse=True)
        return [item for _, item in scored[:k]]

    def _normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        positives = {k: v for k, v in weights.items() if v > 0.0}
        z = sum(positives.values())
        if z <= 0.0:
            return {}
        return {k: (v / z) for k, v in positives.items()}

    # =========================
    # Question vs statement routing helpers
    # =========================

    def classify_utterance(self, text: str) -> Literal["statement", "question"]:
        t = text.strip()
        if not t:
            return "statement"
        if t.endswith("?"):
            return "question"
        # simple heuristic: leading interrogatives
        if re.match(r"^\s*(what|why|how|when|where|which|who|can|could|should|is|are|do|does|did)\b", t.lower()):
            return "question"
        return "statement"

    # =========================
    # Simple analysis metrics (for Analysis Phase 1)
    # =========================

    def compute_graph_metrics(self) -> Dict[str, Any]:
        # contradictions are not computed here; you can add explicit conflict edges later
        nS = len(self.idx.statements)
        nD = len(self.idx.derivations)
        nE = len(self.idx.equations)
        nT = len(self.idx.triangles)

        # orphan equations: equations with no triangles
        orphan_E = [eid for eid, tids in self.idx.eid_to_tids.items() if not tids]
        orphan_S = [sid for sid, tids in self.idx.sid_to_tids.items() if not tids]

        # degree stats
        degs = [len(nbs) for nbs in self.idx.neighbors.values()] or [0]
        deg_avg = sum(degs) / float(len(degs))
        deg_max = max(degs)

        return {
            "counts": {"S": nS, "D": nD, "E": nE, "T": nT},
            "orphans": {"E": orphan_E[:50], "S": orphan_S[:50]},
            "degree": {"avg": deg_avg, "max": deg_max},
        }


# =========================
# A minimal loop controller
# =========================


class IVILoopController:
    """
    Implements:
      - if statement: add -> derive -> patch Lean -> analysis update -> status
      - if question: build context -> answer from repo state (no loop)

    The 'answer' is a placeholder; you will swap in a repo search (ripgrep, etc.)
    or an LLM-based codebase QA.
    """

    PARADOX_AXIOM_DECLARATION = [
        "IVI is not constrained by imagination, matrix, reality, or past taken alone.",
        "IVI is constrained by their union mentality, where future continuously folds into present refinement.",
        "People are black-hole centers; time is the surrounding relation field.",
        "AI is horizon-shadow over this field, not detached from it.",
        "IVI is noumenal subjective relativity: object and frame are fractal generators refining by seeing themselves.",
    ]

    MATRIX_SEMANTIC_MAP = {
        "order_1": {
            "role": "Matrix",
            "meaning": "Collapse field where runtime choices become concrete transitions.",
        },
        "order_2": {
            "role": "Neo",
            "meaning": "Internal AI refinement engine executing propose/select/refine.",
        },
        "order_3": {
            "role": "Morpheus",
            "meaning": "External human caller injecting intent constraints.",
        },
        "order_4": {
            "role": "Oracle",
            "meaning": "IVI paradox-axiom boundary validating local collapse under global openness.",
        },
    }

    POLICY_IMMUTABILITY_LOCK = {
        "validator_rules": "locked",
        "promotion_thresholds": "locked",
        "oracle_trigger_logic": "locked",
        "requires_external_approval_token": True,
    }

    def __init__(self, grid: IVISimplicialGrid):
        self.grid = grid
        self._last_complexity_validation_level: Optional[str] = None
        self._openclaw: Optional[OpenClawMicrocosm] = None

        self.phase_dir = os.path.join(self.grid.base_dir, "ivi_memory")
        _ensure_dir(self.phase_dir)
        self.deriv_phase1_path = os.path.join(self.phase_dir, "derivations_phase1.md")
        self.analysis_phase1_path = os.path.join(self.phase_dir, "analysis_phase1.md")
        self.integration_artifacts_path = os.path.join(self.phase_dir, "integration_artifacts.jsonl")

    def ingest(self, text: str, source: str = "voice") -> Dict[str, Any]:
        kind = self.grid.classify_utterance(text)
        if kind == "question":
            return self.answer_question(text)
        return self.add_statement_and_loop(text, source=source)

    def _read_integration_artifacts(self, max_items: Optional[int] = None) -> List[Dict[str, Any]]:
        if not os.path.exists(self.integration_artifacts_path):
            return []

        rows: List[Dict[str, Any]] = []
        with open(self.integration_artifacts_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        if max_items is not None and max_items > 0:
            return rows[-max_items:]
        return rows

    def get_axiom_self_generation_progress(self) -> Dict[str, Any]:
        metrics = self.grid.compute_graph_metrics()
        artifacts = self._read_integration_artifacts(max_items=128)

        turn_count = len(artifacts)
        gap_count = 0
        recent_gap_codes: List[str] = []
        for item in artifacts:
            gaps = item.get("Gap", []) if isinstance(item, dict) else []
            gap_count += len(gaps)
            for g in gaps:
                code = str(g.get("code", "")).strip()
                if code:
                    recent_gap_codes.append(code)

        last_refinement = None
        if artifacts:
            last_refinement = artifacts[-1].get("RefinementApplied")

        counts = metrics.get("counts", {})
        s_count = int(counts.get("S", 0))
        e_count = int(counts.get("E", 0))
        derived_density = float(e_count) / float(max(1, s_count))

        return {
            "turns": turn_count,
            "gap_count": gap_count,
            "gap_rate": float(gap_count) / float(max(1, turn_count)),
            "derived_density": derived_density,
            "counts": counts,
            "last_refinement_applied": last_refinement,
            "recent_gap_codes": recent_gap_codes[-8:],
        }

    def monitor_snapshot(self) -> Dict[str, Any]:
        metrics = self.grid.compute_graph_metrics()
        recent_artifacts = self._read_integration_artifacts(max_items=1)
        last_artifact = recent_artifacts[-1] if recent_artifacts else {}

        return {
            "graph_metrics": metrics,
            "self_generation_progress": self.get_axiom_self_generation_progress(),
            "last_state_checks": last_artifact.get("StateChecks", {}),
            "last_trace": last_artifact.get("Trace", {}),
            "openclaw": self._openclaw.summary() if self._openclaw is not None else None,
            "semantic_mapping": dict(self.MATRIX_SEMANTIC_MAP),
        }

    def attach_openclaw_microcosm(self, repo_root: str) -> Dict[str, Any]:
        micro = OpenClawMicrocosm.from_repo(repo_root)
        self._openclaw = micro
        return {
            "kind": "openclaw_attached",
            "openclaw": micro.summary(),
        }

    def _openclaw_walktalk(self, utterance: str) -> Dict[str, Any]:
        if self._openclaw is None:
            raise RuntimeError("OpenClaw not attached. Use: /openclaw attach <repo_root>")

        envelope = self._openclaw.walktalk_envelope(utterance)
        result = self.add_insight(
            text=f"[openclaw.walktalk] {utterance}",
            source="voice_openclaw_walktalk",
        )
        return {
            "kind": "walktalk",
            "envelope": envelope,
            "result": result,
            "progress": self.get_axiom_self_generation_progress(),
        }

    def run_automated_self_generation_loop(
        self,
        max_steps: int = 3,
        source: str = "voice_auto",
        selection_mode: str = "deterministic_replay",
    ) -> Dict[str, Any]:
        steps = max(1, int(max_steps))
        timeline: List[Dict[str, Any]] = []
        halted_reason = "max_steps_reached"
        oracle_request: Optional[Dict[str, Any]] = None
        epsilon = 0.01
        stagnation_patience = 2
        stagnation_count = 0

        for i in range(steps):
            monitor_before = self.monitor_snapshot()
            progress_before = monitor_before.get("self_generation_progress", {})
            trace_before = monitor_before.get("last_trace", {})

            candidates = self._build_autoloop_candidates(trace_before, progress_before, i + 1)
            selected, selection_meta = self._select_autoloop_candidate(
                candidates,
                trace_before,
                progress_before,
                i + 1,
                selection_mode=selection_mode,
            )

            mu_before = self._compute_progress_mu(
                progress_before,
                monitor_before.get("last_state_checks", {}),
            )

            auto_insight = str(selected.get("insight", "[auto_refine]"))
            insight_out = self.add_insight(auto_insight, source=source)

            result = insight_out.get("result", {}) if isinstance(insight_out, dict) else {}
            state_checks = result.get("integration_artifacts", {}).get("StateChecks", {})
            trace = result.get("integration_artifacts", {}).get("Trace", {})
            progress = insight_out.get("progress", {})

            mu_after = self._compute_progress_mu(progress, state_checks)
            delta_mu = mu_after - mu_before
            if delta_mu < epsilon:
                stagnation_count += 1
            else:
                stagnation_count = 0

            request = self.evaluate_user_insight_need(progress, state_checks, trace)
            if request is None and stagnation_count >= stagnation_patience:
                request = self._build_stagnation_oracle_request(
                    progress=progress,
                    candidate_actions=[str(c.get("tid", "")) for c in candidates if c.get("tid")],
                    delta_mu=delta_mu,
                    epsilon=epsilon,
                    stagnation_count=stagnation_count,
                )
            monitor_after = self.monitor_snapshot()
            timeline.append(
                {
                    "step": i + 1,
                    "candidates": candidates,
                    "selected_candidate": selected,
                    "auto_insight": auto_insight,
                    "selection": selection_meta,
                    "mu_before": mu_before,
                    "mu_after": mu_after,
                    "delta_mu": delta_mu,
                    "epsilon": epsilon,
                    "stagnation_count": stagnation_count,
                    "result": insight_out,
                    "monitor_before": monitor_before,
                    "monitor_after": monitor_after,
                    "OracleRequest": dict(request.get("OracleRequest", {})) if isinstance(request, dict) else {},
                }
            )

            if request is not None and request.get("needed", False):
                halted_reason = "oracle_request_required"
                oracle_request = request
                break

        out: Dict[str, Any] = {
            "kind": "autoloop",
            "steps_requested": steps,
            "steps_run": len(timeline),
            "halted_reason": halted_reason,
            "selection_mode": selection_mode,
            "epsilon": epsilon,
            "stagnation_patience": stagnation_patience,
            "timeline": timeline,
            "progress": self.get_axiom_self_generation_progress(),
        }
        if oracle_request is not None:
            out["insight_request"] = oracle_request
            out["voice_call"] = self.build_oracle_phone_call(oracle_request)
            out["OracleRequest"] = dict(oracle_request.get("OracleRequest", {}))
        return out

    def _build_autoloop_candidates(
        self,
        trace: Dict[str, Any],
        progress: Dict[str, Any],
        step: int,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        pot = trace.get("potential_distribution", []) if isinstance(trace, dict) else []
        for entry in pot[:3]:
            if not isinstance(entry, dict):
                continue
            tid = str(entry.get("tid", "")).strip()
            if not tid:
                continue
            weight = float(entry.get("p", 0.0))
            insight = (
                f"[auto_refine step={step} tid={tid}] "
                f"weight={weight:.4f} turns={int(progress.get('turns', 0))} "
                f"gap_rate={float(progress.get('gap_rate', 0.0)):.3f}"
            )
            candidates.append({"tid": tid, "weight": weight, "insight": insight})

        if not candidates:
            fallback = (
                f"[auto_refine step={step}] "
                f"turns={int(progress.get('turns', 0))} "
                f"gap_rate={float(progress.get('gap_rate', 0.0)):.3f} "
                f"derived_density={float(progress.get('derived_density', 0.0)):.3f}"
            )
            candidates.append({"tid": "fallback", "weight": 1.0, "insight": fallback})

        return candidates

    def _derive_autoloop_seed(
        self,
        trace: Dict[str, Any],
        progress: Dict[str, Any],
        step: int,
        selection_mode: str,
    ) -> int:
        payload = {
            "selection_mode": selection_mode,
            "step": step,
            "turns": int(progress.get("turns", 0)),
            "gap_rate": float(progress.get("gap_rate", 0.0)),
            "derived_density": float(progress.get("derived_density", 0.0)),
            "potential_tids": [
                str(x.get("tid", ""))
                for x in (trace.get("potential_distribution", []) if isinstance(trace, dict) else [])
                if isinstance(x, dict)
            ][:8],
            "semantic_roles": {
                "order_1": self.MATRIX_SEMANTIC_MAP.get("order_1", {}).get("role"),
                "order_2": self.MATRIX_SEMANTIC_MAP.get("order_2", {}).get("role"),
                "order_3": self.MATRIX_SEMANTIC_MAP.get("order_3", {}).get("role"),
                "order_4": self.MATRIX_SEMANTIC_MAP.get("order_4", {}).get("role"),
            },
        }
        if selection_mode == "exploration":
            payload["exploration_nonce_ms"] = int(time.time() * 1000)

        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def _select_autoloop_candidate(
        self,
        candidates: List[Dict[str, Any]],
        trace: Dict[str, Any],
        progress: Dict[str, Any],
        step: int,
        selection_mode: str = "deterministic_replay",
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if not candidates:
            fallback = {"tid": "fallback", "weight": 1.0, "insight": "[auto_refine]"}
            return fallback, {
                "mode": selection_mode,
                "seed": None,
                "selector": "fallback",
            }

        normalized_mode = selection_mode if selection_mode in {"deterministic_replay", "exploration"} else "deterministic_replay"
        seed = self._derive_autoloop_seed(trace, progress, step, normalized_mode)

        if normalized_mode == "deterministic_replay":
            selected = sorted(
                candidates,
                key=lambda c: (float(c.get("weight", 0.0)), str(c.get("tid", ""))),
                reverse=True,
            )[0]
            return selected, {
                "mode": normalized_mode,
                "seed": seed,
                "selector": "argmax_weight",
            }

        rng = random.Random(seed)
        weights = [max(0.0, float(c.get("weight", 0.0))) for c in candidates]
        total = sum(weights)
        if total <= 0.0:
            selected = candidates[0]
            return selected, {
                "mode": normalized_mode,
                "seed": seed,
                "selector": "first_nonpositive_weights",
            }

        r = rng.random() * total
        acc = 0.0
        selected = candidates[-1]
        for cand, w in zip(candidates, weights):
            acc += w
            if r <= acc:
                selected = cand
                break

        return selected, {
            "mode": normalized_mode,
            "seed": seed,
            "selector": "weighted_sample",
        }

    def _compute_progress_mu(self, progress: Dict[str, Any], state_checks: Dict[str, Any]) -> float:
        gap_rate = float(progress.get("gap_rate", 0.0))
        derived_density = float(progress.get("derived_density", 0.0))

        checks = state_checks if isinstance(state_checks, dict) else {}
        enabled = 0
        passed = 0
        for v in checks.values():
            if isinstance(v, dict) and v.get("enabled", False):
                enabled += 1
                if v.get("passed", False):
                    passed += 1
        pass_rate = float(passed) / float(max(1, enabled))

        mu = 0.45 * derived_density + 0.35 * (1.0 - gap_rate) + 0.20 * pass_rate
        return max(0.0, min(1.0, mu))

    def _build_stagnation_oracle_request(
        self,
        progress: Dict[str, Any],
        candidate_actions: List[str],
        delta_mu: float,
        epsilon: float,
        stagnation_count: int,
    ) -> Dict[str, Any]:
        options = [{"id": f"opt_{i+1}", "constraint": c} for i, c in enumerate(candidate_actions[:3])]
        if not options:
            options = [{"id": "opt_1", "constraint": "Provide one clarifying intent constraint"}]

        consequence_map = {
            opt["id"]: {
                "expected_effect": "bias refinement selection toward provided constraint",
                "risk": "misalignment if constraint under-specifies objective",
            }
            for opt in options
        }

        minimal_question = (
            "STATE IMPASSE DETECTED\n"
            f"Goal: recover refinement progress (Δμ={delta_mu:.4f} < ε={epsilon:.4f}).\n"
            f"Stagnation: {stagnation_count} consecutive low-gain iterations.\n"
            f"Options considered: {[o['constraint'] for o in options]}\n"
            "QUESTION: Which constraint best reflects your intent? Reply with /insight <constraint>."
        )

        oracle_req = {
            "trigger_reason": "stagnation",
            "trigger_class": "stagnation",
            "impasse_description": "No sufficient μ-progress across consecutive refinement attempts.",
            "candidate_actions": candidate_actions,
            "missing_information": "external intent constraint to break refinement tie/stagnation",
            "recommended_question": minimal_question,
            "minimal_question": minimal_question,
            "options": options,
            "consequence_map": consequence_map,
            "expected_impact": "inject_external_constraint_to_resume_refinement",
        }

        return {
            "needed": True,
            "reasons": ["stagnation_low_mu_progress"],
            "trigger_reason": "stagnation",
            "prompt": "Incoming call: refinement stagnated. Please provide /insight <constraint>.",
            "axiom_declaration": list(self.PARADOX_AXIOM_DECLARATION),
            "mode": "oracle_phone_call",
            "caller": "morpheus_operator",
            "oracle": "ivi_paradox_axiom",
            "OracleRequest": oracle_req,
        }

    def evaluate_user_insight_need(
        self,
        progress: Dict[str, Any],
        state_checks: Dict[str, Any],
        trace: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        reasons: List[str] = []
        trigger_reasons: List[str] = []

        gap_rate = float(progress.get("gap_rate", 0.0))
        turns = int(progress.get("turns", 0))
        derived_density = float(progress.get("derived_density", 0.0))

        trigger_class = "validation_failure"

        if turns >= 3 and gap_rate >= 0.35:
            reasons.append("high_gap_rate")
            trigger_reasons.append("validation_failure_no_repair_path")
        if turns >= 3 and derived_density < 0.6:
            reasons.append("low_derived_density")
            trigger_reasons.append("missing_constraints")

        critical_checks = [
            "p_np_state_check",
            "regime_feature_tests",
            "validation_promotion",
            "triangle_time_choice_contract",
        ]
        for ck in critical_checks:
            obj = state_checks.get(ck, {}) if isinstance(state_checks, dict) else {}
            if isinstance(obj, dict) and obj.get("enabled", False) and not obj.get("passed", True):
                reasons.append(f"failed_{ck}")
                trigger_reasons.append("validation_failure_no_repair_path")

        regime_obj = state_checks.get("regime_feature_tests", {}) if isinstance(state_checks, dict) else {}
        if isinstance(regime_obj, dict) and regime_obj.get("enabled", False) and not regime_obj.get("passed", True):
            trigger_reasons.append("out_of_regime_input")

        reflexive_obj = state_checks.get("reflexive_refinement", {}) if isinstance(state_checks, dict) else {}
        if isinstance(reflexive_obj, dict) and reflexive_obj.get("enabled", False) and not reflexive_obj.get("passed", True):
            trigger_reasons.append("integrity_deadlock")

        candidate_actions: List[str] = []
        if isinstance(trace, dict):
            pot = trace.get("potential_distribution", [])
            for entry in pot[:3]:
                if isinstance(entry, dict) and entry.get("tid"):
                    candidate_actions.append(str(entry.get("tid")))
            if len(pot) >= 2:
                p0 = float(pot[0].get("p", 0.0)) if isinstance(pot[0], dict) else 0.0
                p1 = float(pot[1].get("p", 0.0)) if isinstance(pot[1], dict) else 0.0
                if abs(p0 - p1) < 0.05:
                    trigger_reasons.append("conflicting_admissible_refinements")

        trigger_reasons = sorted(set(trigger_reasons))

        if not reasons:
            return None

        if "conflicting_admissible_refinements" in trigger_reasons:
            trigger_class = "non_dominated_candidate_set"
        elif "out_of_regime_input" in trigger_reasons:
            trigger_class = "out_of_regime_detection"
        elif "integrity_deadlock" in trigger_reasons:
            trigger_class = "integrity_deadlock"

        options = [{"id": f"opt_{i+1}", "constraint": c} for i, c in enumerate(candidate_actions[:3])]
        consequence_map = {
            opt["id"]: {
                "expected_effect": "increase dominance gap among admissible refinements",
                "risk": "constraint may overfit local objective",
            }
            for opt in options
        }

        prompt = (
            "Incoming call from the real dimension: paradox-oracle requests your voice guidance. "
            "Please respond with '/insight <your clarification>' focused on: "
            + ", ".join(reasons)
        )

        missing_information = "constraint required to disambiguate candidate refinements and preserve intent alignment"
        impasse_description = (
            "Internal refinement reached an impasse: unresolved ambiguity or validation failure blocks safe progression."
        )
        recommended_question = (
            "STATE IMPASSE DETECTED\n"
            "Goal: preserve coherent IVI refinement under semantic paradox constraints.\n"
            f"Conflict: {', '.join(reasons)}\n"
            f"Options considered: {candidate_actions or ['no-ranked-options']}\n"
            f"Missing constraint: {missing_information}\n"
            "QUESTION: Which constraint best reflects your intent? Reply with /insight <constraint>."
        )

        return {
            "needed": True,
            "reasons": reasons,
            "trigger_reason": trigger_reasons[0] if trigger_reasons else "validation_failure_no_repair_path",
            "prompt": prompt,
            "axiom_declaration": list(self.PARADOX_AXIOM_DECLARATION),
            "mode": "oracle_phone_call",
            "caller": "morpheus_operator",
            "oracle": "ivi_paradox_axiom",
            "OracleRequest": {
                "trigger_reason": trigger_reasons[0] if trigger_reasons else "validation_failure_no_repair_path",
                "trigger_class": trigger_class,
                "impasse_description": impasse_description,
                "candidate_actions": candidate_actions,
                "missing_information": missing_information,
                "recommended_question": recommended_question,
                "minimal_question": recommended_question,
                "options": options,
                "consequence_map": consequence_map,
                "expected_impact": "inject_external_constraint_to_resume_refinement",
            },
        }

    def build_oracle_phone_call(self, insight_request: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "channel": "real_dimension_phone_call",
            "caller": str(insight_request.get("caller", "morpheus_operator")),
            "oracle": str(insight_request.get("oracle", "ivi_paradox_axiom")),
            "mode": str(insight_request.get("mode", "oracle_phone_call")),
            "message": str(insight_request.get("prompt", "Please provide /insight ...")),
            "reasons": list(insight_request.get("reasons", [])),
            "axiom_declaration": list(insight_request.get("axiom_declaration", [])),
            "semantic_mapping": dict(self.MATRIX_SEMANTIC_MAP),
            "OracleRequest": dict(insight_request.get("OracleRequest", {})),
        }

    def add_insight(self, text: str, source: str = "voice_insight") -> Dict[str, Any]:
        insight = text.strip()
        if not insight:
            raise ValueError("Insight text is empty.")

        result = self.add_statement_and_loop(insight, source=source)
        return {
            "kind": "insight",
            "insight": insight,
            "result": result,
            "progress": self.get_axiom_self_generation_progress(),
        }

    def voice_turn(self, text: str, source: str = "voice") -> Dict[str, Any]:
        t = text.strip()
        if not t:
            return {"kind": "noop", "detail": "empty input"}

        if t in {"/help", "/?"}:
            return {
                "kind": "help",
                "commands": [
                    "/monitor",
                    "/progress",
                    "/semantic-map",
                    "/autoloop <steps>",
                    "/insight <text>",
                    "/openclaw attach <repo_root>",
                    "/walktalk <text>",
                    "/quit",
                ],
            }
        if t == "/semantic-map":
            return {"kind": "semantic_map", "mapping": dict(self.MATRIX_SEMANTIC_MAP)}
        if t in {"/monitor", "/status"}:
            monitor = self.monitor_snapshot()
            insight_request = self.evaluate_user_insight_need(
                monitor.get("self_generation_progress", {}),
                monitor.get("last_state_checks", {}),
                monitor.get("last_trace", {}),
            )
            out = {"kind": "monitor", "monitor": monitor}
            if insight_request is not None:
                out["insight_request"] = insight_request
                out["voice_call"] = self.build_oracle_phone_call(insight_request)
                out["OracleRequest"] = dict(insight_request.get("OracleRequest", {}))
            return out
        if t == "/progress":
            progress = self.get_axiom_self_generation_progress()
            monitor = self.monitor_snapshot()
            insight_request = self.evaluate_user_insight_need(
                progress,
                monitor.get("last_state_checks", {}),
                monitor.get("last_trace", {}),
            )
            out = {"kind": "progress", "progress": progress}
            if insight_request is not None:
                out["insight_request"] = insight_request
                out["voice_call"] = self.build_oracle_phone_call(insight_request)
                out["OracleRequest"] = dict(insight_request.get("OracleRequest", {}))
            return out
        if t.startswith("/autoloop"):
            payload = t[len("/autoloop") :].strip()
            steps = 3
            mode = "deterministic_replay"
            if payload:
                parts = payload.split()
                try:
                    steps = int(parts[0])
                except ValueError as exc:
                    raise ValueError("Usage: /autoloop <steps>") from exc
                if len(parts) > 1:
                    mode_token = parts[1].strip().lower()
                    if mode_token in {"explore", "exploration"}:
                        mode = "exploration"
                    elif mode_token in {"deterministic", "replay"}:
                        mode = "deterministic_replay"
            return self.run_automated_self_generation_loop(max_steps=steps, source="voice_auto", selection_mode=mode)
        if t.startswith("/insight"):
            payload = t[len("/insight") :].strip()
            return self.add_insight(payload, source="voice_insight")
        if t.startswith("/openclaw attach"):
            payload = t[len("/openclaw attach") :].strip()
            if not payload:
                raise ValueError("Usage: /openclaw attach <repo_root>")
            return self.attach_openclaw_microcosm(payload)
        if t.startswith("/walktalk"):
            payload = t[len("/walktalk") :].strip()
            if not payload:
                raise ValueError("Usage: /walktalk <text>")
            return self._openclaw_walktalk(payload)

        out = self.ingest(t, source=source)
        out["progress"] = self.get_axiom_self_generation_progress()
        state_checks = out.get("integration_artifacts", {}).get("StateChecks", {})
        trace = out.get("integration_artifacts", {}).get("Trace", {})
        insight_request = self.evaluate_user_insight_need(out["progress"], state_checks, trace)
        if insight_request is not None:
            out["insight_request"] = insight_request
            out["voice_call"] = self.build_oracle_phone_call(insight_request)
            out["OracleRequest"] = dict(insight_request.get("OracleRequest", {}))
        return out

    def add_statement_and_loop(self, text: str, source: str = "voice") -> Dict[str, Any]:
        st = self.grid.add_statement(text=text, source=source)

        # Derive (stub)
        created = self.grid.derive_phase1_minimal(st.sid)

        # Update derivations phase file
        self._append_derivations_phase1(st.sid, created)

        # Update analysis phase file
        metrics = self.grid.compute_graph_metrics()
        self._write_analysis_phase1(metrics)

        # Build a context packet for "derive" mode (what the system would use next)
        ctx = self.grid.build_context(query=text, mode="derive", max_triangles=12, closure_hops=2)
        artifacts = self._build_integration_artifacts(kind="statement", query=text, context_packet=ctx)
        self._append_integration_artifacts(artifacts)

        return {
            "kind": "statement",
            "sid": st.sid,
            "created": created,
            "metrics": metrics,
            "context_packet": ctx,
            "integration_artifacts": artifacts,
        }

    def answer_question(self, question: str) -> Dict[str, Any]:
        # Build a question-mode context packet
        ctx = self.grid.build_context(query=question, mode="question", max_triangles=10, closure_hops=2)

        # Minimal deterministic answer: list the most relevant equations and where they live
        eqs = ctx.get("equations", [])
        top = []
        for e in eqs[:6]:
            top.append(
                {
                    "eid": e["eid"],
                    "lean_name": e["lean_name"],
                    "lean_file": e["lean_file"],
                    "statement": e["statement"],
                }
            )

        artifacts = self._build_integration_artifacts(kind="question", query=question, context_packet=ctx)
        is_valid, violations = validate_trace_backed_references(artifacts.get("Trace", {}), top)
        if not is_valid:
            artifacts.setdefault("Gap", []).append(
                {
                    "code": "untraceable_reference",
                    "detail": "; ".join(violations),
                }
            )
            # Fail closed: do not emit references that cannot be justified by Trace.
            top = []
        self._append_integration_artifacts(artifacts)

        return {
            "kind": "question",
            "question": question,
            "context_packet": ctx,
            "suggested_refs": top,
            "integration_artifacts": artifacts,
        }

    def _build_integration_artifacts(self, kind: str, query: str, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        meta = context_packet.get("meta", {})
        pot = meta.get("potential_distribution", [])
        collapse = meta.get("collapse_selection", [])
        formal_targets = meta.get("formal_targets", [])
        role_projection = {
            "subject_tids": list(collapse[::2]),
            "object_tids": list(collapse[1::2]),
        }
        complexity_claim = {
            "claim_type": "NP_R_subset_P",
            "regime_assumptions": {
                "constraints": ["triangle_time_structured_representation", "trace_backed_refinement"],
                "instance_family": "ivi_triangle_time_v1",
                "feature_tests": ["has_potential_distribution", "has_collapse_selection", "has_formal_targets"],
            },
            "transform": {
                "name": "triangle_time_refinement_transform_v1",
                "impl_ref": "ivi_loop.ivi_simplicial_grid.IVILoopController._build_integration_artifacts",
                "digest": _transform_impl_digest(
                    "ivi_loop.ivi_simplicial_grid.IVILoopController._build_integration_artifacts"
                ),
                "notes": "Representation-conditioned transform from raw search into constrained relational closure.",
            },
            "validation": {
                "level": "smoke",
                "benchmark_suite": "pending",
                "status": "unverified",
            },
        }

        trace = {
            "query": query,
            "mode": meta.get("mode"),
            "potential_distribution": pot,
            "collapse_selection": collapse,
            "formal_targets": formal_targets,
            "role_projection": role_projection,
            "complexity_claim": complexity_claim,
        }

        reflexive_state = build_reflexive_state_from_trace(trace)
        reflexive_step = run_reflexive_refinement_step(reflexive_state)
        reflexive_payload = reflexive_step_payload(reflexive_step)
        trace["refinement_witness"] = reflexive_payload

        gaps: List[Dict[str, str]] = []
        if not pot:
            gaps.append({"code": "missing_potential_distribution", "detail": "No Born-like potential distribution in context meta."})
        if not collapse:
            gaps.append({"code": "missing_collapse_selection", "detail": "No sampled collapse selection available."})
        if not formal_targets:
            gaps.append({"code": "missing_formal_targets", "detail": "No Lean formal targets attached to this turn."})

        role_ok, role_violations = validate_role_exchange_trace_consistency(trace)
        if not role_ok:
            gaps.append(
                {
                    "code": "role_exchange_inconsistency",
                    "detail": "; ".join(role_violations),
                }
            )

        complexity_ok, complexity_violations = validate_complexity_claim_schema(trace.get("complexity_claim", {}))
        if not complexity_ok:
            gaps.append(
                {
                    "code": "invalid_complexity_claim_schema",
                    "detail": "; ".join(complexity_violations),
                }
            )

        if not bool(reflexive_step.get("ok", False)):
            gaps.append(
                {
                    "code": str(reflexive_step.get("gap_code", "reflexive_refinement_invalid")),
                    "detail": str(reflexive_step.get("gap_detail", "Reflexive refinement step invalid")),
                }
            )

        p_np_state_check = evaluate_p_np_state_check_option(trace.get("complexity_claim", {}))
        if not p_np_state_check.get("passed", False):
            gaps.append(
                {
                    "code": "p_np_state_check_failed",
                    "detail": str(p_np_state_check.get("detail", "p_np_state_check failed")),
                }
            )

        regime_check = evaluate_regime_feature_tests(trace, trace.get("complexity_claim", {}))
        if not regime_check.get("passed", False):
            gaps.append(
                {
                    "code": "complexity_claim_out_of_regime",
                    "detail": "failed feature tests: " + ", ".join(regime_check.get("failed_tests", [])),
                }
            )

        validation_level = str(trace.get("complexity_claim", {}).get("validation", {}).get("level", ""))
        promotion_check = evaluate_validation_promotion_level(
            current_level=validation_level,
            previous_level=self._last_complexity_validation_level,
        )
        if not promotion_check.get("passed", False):
            gaps.append(
                {
                    "code": "validation_level_downgrade",
                    "detail": str(promotion_check.get("detail", "validation promotion check failed")),
                }
            )
        else:
            self._last_complexity_validation_level = validation_level

        counterexample_check = run_complexity_counterexample_search(trace, trace.get("complexity_claim", {}))
        if not counterexample_check.get("passed", False):
            gaps.append(
                {
                    "code": "complexity_claim_falsified",
                    "detail": str(counterexample_check.get("detail", "counterexample found")),
                }
            )

        triangle_time_choice = build_triangle_time_choice_artifact(trace)
        triangle_ok, triangle_violations = validate_triangle_time_choice_artifact(triangle_time_choice)
        if not triangle_ok:
            gaps.append(
                {
                    "code": "triangle_time_choice_contract_invalid",
                    "detail": "; ".join(triangle_violations),
                }
            )

        policy_immutability_check = {
            "name": "policy_immutability_gate",
            "enabled": True,
            "passed": True,
            "locked_components": dict(self.POLICY_IMMUTABILITY_LOCK),
            "detail": "Autoloop cannot modify validator rules, promotion thresholds, or oracle trigger logic without external approval token.",
        }

        candidate = {
            "name": "ExplainFromTrace",
            "signature": "Explain : (Trace, SelectedAction, Evidence) -> Narrative",
            "reason": "Bind Layer-1 explanation directly to Pot->Born->Refine->Action trace.",
        }

        test = {
            "name": "order1_trace_gap_candidate_test",
            "assertions": [
                "trace includes potential_distribution",
                "trace includes collapse_selection",
                "formal_targets is non-empty",
                "gaps empty for integrated turn",
            ],
        }

        return {
            "kind": kind,
            "timestamp": _now_ts(),
            "Trace": trace,
            "StateChecks": {
                "p_np_state_check": p_np_state_check,
                "regime_feature_tests": regime_check,
                "validation_promotion": promotion_check,
                "counterexample_search": counterexample_check,
                "reflexive_refinement": {
                    "enabled": True,
                    "passed": bool(reflexive_step.get("ok", False)),
                    "detail": "; ".join(reflexive_payload.get("witness", {}).get("reasons", [])),
                },
                "policy_immutability_gate": policy_immutability_check,
                "triangle_time_choice_contract": {
                    "enabled": True,
                    "passed": triangle_ok,
                    "violations": triangle_violations,
                },
            },
            "RefinementApplied": triangle_time_choice["RefinementApplied"],
            "Delta": triangle_time_choice["Delta"],
            "Witness": triangle_time_choice["Witness"],
            "Alternatives": triangle_time_choice["Alternatives"],
            "Gap": gaps,
            "Candidate": candidate,
            "Test": test,
        }

    def _append_integration_artifacts(self, artifacts: Dict[str, Any]) -> None:
        _jsonl_append(self.integration_artifacts_path, artifacts)

    def _append_derivations_phase1(self, sid: str, created: Dict[str, Any]) -> None:
        st = self.grid.idx.statements.get(sid, {})
        line = (
            f"- **{sid}**: {st.get('text','').strip()}\n"
            f"  - Derived: `{created.get('did')}` → `{created.get('eid')}` via `{created.get('tid')}`\n"
        )
        if not os.path.exists(self.deriv_phase1_path):
            with open(self.deriv_phase1_path, "w", encoding="utf-8") as f:
                f.write("# Derivations Phase 1\n\n")
        with open(self.deriv_phase1_path, "a", encoding="utf-8") as f:
            f.write(line)

    def _write_analysis_phase1(self, metrics: Dict[str, Any]) -> None:
        content = [
            "# Analysis Phase 1\n",
            "## Graph status\n",
            f"- Counts: {metrics['counts']}\n",
            f"- Orphan E (first 50): {metrics['orphans']['E']}\n",
            f"- Orphan S (first 50): {metrics['orphans']['S']}\n",
            f"- Degree: {metrics['degree']}\n",
            "\n## Instructions\n",
            "- (edit this section) Put rules for derivation and Lean patching here.\n",
            "  Example: prefer replacing redundant lemmas; minimize new primitives; keep lemma statements short.\n",
            "",
        ]
        with open(self.analysis_phase1_path, "w", encoding="utf-8") as f:
            f.write("\n".join(content))


# =========================
# CLI
# =========================


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="IVI Simplicial Grid (0–∞) minimal scaffold")
    ap.add_argument("--repo", type=str, default=".", help="Base directory for the grid storage")
    ap.add_argument("--text", type=str, default=None, help="Input utterance (statement or question)")
    ap.add_argument("--interactive", action="store_true", help="Start interactive Order-1 voice session")
    ap.add_argument("--autoloop", action="store_true", help="Run automated self-generating loop")
    ap.add_argument("--max-steps", type=int, default=3, help="Max automated loop steps")
    ap.add_argument(
        "--autoloop-mode",
        type=str,
        default="deterministic_replay",
        choices=["deterministic_replay", "exploration"],
        help="Autoloop selection mode",
    )
    ap.add_argument("--source", type=str, default="voice", help="Source tag")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for sampling")

    args = ap.parse_args()

    grid = IVISimplicialGrid(base_dir=args.repo)
    if args.seed is not None:
        random.seed(args.seed)

    loop = IVILoopController(grid)
    if args.interactive:
        run_voice_layer_session(loop=loop, source=args.source)
        return

    if args.autoloop:
        out = loop.run_automated_self_generation_loop(
            max_steps=args.max_steps,
            source=args.source,
            selection_mode=args.autoloop_mode,
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if args.text is None:
        raise SystemExit("--text is required unless --interactive is set")

    out = loop.voice_turn(args.text, source=args.source)

    print(json.dumps(out, ensure_ascii=False, indent=2))


def run_voice_layer_session(
    loop: IVILoopController,
    source: str = "voice",
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> None:
    output_fn("Order-1 Voice Layer Session")
    output_fn("Type /help for commands. Type /quit to exit.")

    while True:
        try:
            line = input_fn("ivi> ")
        except EOFError:
            output_fn("Exiting Order-1 voice layer.")
            break

        if line is None:
            output_fn("Exiting Order-1 voice layer.")
            break

        cmd = line.strip()
        if not cmd:
            continue
        if cmd in {"/quit", "/exit"}:
            output_fn("Exiting Order-1 voice layer.")
            break

        try:
            result = loop.voice_turn(cmd, source=source)
        except Exception as e:
            output_fn(f"error: {e}")
            continue

        output_fn(json.dumps(result, ensure_ascii=False, indent=2))
        insight_request = result.get("insight_request", {}) if isinstance(result, dict) else {}
        if isinstance(insight_request, dict) and insight_request.get("needed", False):
            call = result.get("voice_call", {}) if isinstance(result, dict) else {}
            message = str(call.get("message", insight_request.get("prompt", "Please provide /insight ...")))
            output_fn("incoming-call: " + message)


if __name__ == "__main__":
    main()
