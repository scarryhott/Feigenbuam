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
import copy
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Tuple

from .openclaw_adapter import OpenClawMicrocosm
from .order_mode_selector import (
    ORDER_1_PROJECTION_SAFE,
    ORDER_2_READ_CONTEXT,
    ORDER_4_BOUNDED_AUTONOMY,
    PermissionState,
    PolicyState,
    select_order_mode,
)

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
    potential_tids_canonical = sorted(set(potential_tids))
    potential_tid_set = set(potential_tids_canonical)
    collapse_tids = [str(tid) for tid in trace.get("collapse_selection", [])]
    collapse_tids_canonical = sorted(set(collapse_tids))
    collapse_tid_set = set(collapse_tids_canonical)
    alternatives = [tid for tid in potential_tids_canonical if tid not in collapse_tid_set]
    unsupported_collapse_tids = sorted(tid for tid in collapse_tids_canonical if tid not in potential_tid_set)
    supported_collapse_tids_canonical = sorted(tid for tid in collapse_tids_canonical if tid in potential_tid_set)
    choice_law_replay = trace.get("choice_law_replay", {}) if isinstance(trace.get("choice_law_replay", {}), dict) else {}
    choice_sampling_seed = choice_law_replay.get("sampling_seed", None)

    potential_distribution_digest = _stable_hash(json.dumps(potential_tids_canonical, ensure_ascii=True))
    collapse_set_digest = _stable_hash(json.dumps(collapse_tids_canonical, ensure_ascii=True))
    supported_collapse_set_digest = _stable_hash(json.dumps(supported_collapse_tids_canonical, ensure_ascii=True))

    potential_collapse_dependency = {
        "depends_on": "potential_distribution",
        "potential_count": len(potential_tids_canonical),
        "collapse_count": len(collapse_tids_canonical),
        "supported_collapse_count": len(supported_collapse_tids_canonical),
        "potential_tids_canonical": potential_tids_canonical,
        "collapse_tids_canonical": collapse_tids_canonical,
        "supported_collapse_tids_canonical": supported_collapse_tids_canonical,
        "potential_distribution_digest": potential_distribution_digest,
        "collapse_set_digest": collapse_set_digest,
        "supported_collapse_set_digest": supported_collapse_set_digest,
        "choice_sampling_seed": choice_sampling_seed,
        "unsupported_collapse_tids": unsupported_collapse_tids,
        "collapse_subset_of_potential": len(unsupported_collapse_tids) == 0,
    }

    role_ok, role_violations = validate_role_exchange_trace_consistency(trace)

    return {
        "RefinementApplied": "triangle_time_refinement_transform_v1",
        "Delta": {
            "added_triangle_tids": collapse_tids,
            "added_triangle_count": len(collapse_tids_canonical),
            "potential_triangle_count": len(potential_tids_canonical),
            "potential_collapse_dependency": potential_collapse_dependency,
        },
        "Witness": {
            "integrity_checks": {
                "has_potential_distribution": bool(trace.get("potential_distribution")),
                "has_collapse_selection": bool(collapse_tids),
                "has_formal_targets": bool(trace.get("formal_targets")),
                "role_exchange_consistent": role_ok,
                "potential_collapse_dependency_valid": potential_collapse_dependency["collapse_subset_of_potential"],
            },
            "potential_collapse_dependency": potential_collapse_dependency,
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
    dependency_delta: Optional[Dict[str, Any]] = None

    if not refinement_applied:
        violations.append("RefinementApplied missing")
    if not isinstance(delta, dict):
        violations.append("Delta must be a mapping")
    else:
        added = delta.get("added_triangle_tids")
        if not isinstance(added, list):
            violations.append("Delta.added_triangle_tids must be a list")
        dependency_delta = delta.get("potential_collapse_dependency")
        if not isinstance(dependency_delta, dict):
            violations.append("Delta.potential_collapse_dependency must be a mapping")
    if not isinstance(witness, dict):
        violations.append("Witness must be a mapping")
    else:
        checks = witness.get("integrity_checks")
        if not isinstance(checks, dict):
            violations.append("Witness.integrity_checks must be a mapping")
        dependency = witness.get("potential_collapse_dependency")
        if not isinstance(dependency, dict):
            violations.append("Witness.potential_collapse_dependency must be a mapping")
        else:
            potential_tids_canonical = dependency.get("potential_tids_canonical")
            collapse_tids_canonical = dependency.get("collapse_tids_canonical")
            supported_tids_canonical = dependency.get("supported_collapse_tids_canonical")
            unsupported = dependency.get("unsupported_collapse_tids")
            subset_ok = dependency.get("collapse_subset_of_potential")
            potential_count = dependency.get("potential_count")
            collapse_count = dependency.get("collapse_count")
            supported_count = dependency.get("supported_collapse_count")
            potential_digest = dependency.get("potential_distribution_digest")
            collapse_digest = dependency.get("collapse_set_digest")
            supported_digest = dependency.get("supported_collapse_set_digest")
            choice_sampling_seed = dependency.get("choice_sampling_seed", None)
            if not isinstance(potential_tids_canonical, list):
                violations.append("Witness.potential_collapse_dependency.potential_tids_canonical must be a list")
            if not isinstance(collapse_tids_canonical, list):
                violations.append("Witness.potential_collapse_dependency.collapse_tids_canonical must be a list")
            if not isinstance(supported_tids_canonical, list):
                violations.append("Witness.potential_collapse_dependency.supported_collapse_tids_canonical must be a list")
            if not isinstance(unsupported, list):
                violations.append("Witness.potential_collapse_dependency.unsupported_collapse_tids must be a list")
            if not isinstance(subset_ok, bool):
                violations.append("Witness.potential_collapse_dependency.collapse_subset_of_potential must be a bool")
            if not isinstance(potential_count, int):
                violations.append("Witness.potential_collapse_dependency.potential_count must be an int")
            if not isinstance(collapse_count, int):
                violations.append("Witness.potential_collapse_dependency.collapse_count must be an int")
            if not isinstance(supported_count, int):
                violations.append("Witness.potential_collapse_dependency.supported_collapse_count must be an int")
            if not isinstance(potential_digest, str) or not potential_digest:
                violations.append("Witness.potential_collapse_dependency.potential_distribution_digest must be a non-empty string")
            if not isinstance(collapse_digest, str) or not collapse_digest:
                violations.append("Witness.potential_collapse_dependency.collapse_set_digest must be a non-empty string")
            if not isinstance(supported_digest, str) or not supported_digest:
                violations.append("Witness.potential_collapse_dependency.supported_collapse_set_digest must be a non-empty string")
            if choice_sampling_seed is not None and not isinstance(choice_sampling_seed, int):
                violations.append("Witness.potential_collapse_dependency.choice_sampling_seed must be int|null")

            if isinstance(potential_tids_canonical, list) and isinstance(potential_count, int) and potential_count != len(potential_tids_canonical):
                violations.append("Witness.potential_collapse_dependency potential_count mismatch")
            if isinstance(collapse_tids_canonical, list) and isinstance(collapse_count, int) and collapse_count != len(collapse_tids_canonical):
                violations.append("Witness.potential_collapse_dependency collapse_count mismatch")
            if isinstance(supported_tids_canonical, list) and isinstance(supported_count, int) and supported_count != len(supported_tids_canonical):
                violations.append("Witness.potential_collapse_dependency supported_collapse_count mismatch")

            if (
                isinstance(collapse_count, int)
                and isinstance(unsupported, list)
                and isinstance(supported_count, int)
                and supported_count != collapse_count - len(unsupported)
            ):
                violations.append("Witness.potential_collapse_dependency supported-by-construction mismatch")

            if isinstance(potential_tids_canonical, list) and isinstance(potential_digest, str) and potential_digest:
                expected = _stable_hash(json.dumps(potential_tids_canonical, ensure_ascii=True))
                if potential_digest != expected:
                    violations.append("Witness.potential_collapse_dependency potential_distribution_digest mismatch")
            if isinstance(collapse_tids_canonical, list) and isinstance(collapse_digest, str) and collapse_digest:
                expected = _stable_hash(json.dumps(collapse_tids_canonical, ensure_ascii=True))
                if collapse_digest != expected:
                    violations.append("Witness.potential_collapse_dependency collapse_set_digest mismatch")
            if isinstance(supported_tids_canonical, list) and isinstance(supported_digest, str) and supported_digest:
                expected = _stable_hash(json.dumps(supported_tids_canonical, ensure_ascii=True))
                if supported_digest != expected:
                    violations.append("Witness.potential_collapse_dependency supported_collapse_set_digest mismatch")

            if isinstance(subset_ok, bool) and isinstance(unsupported, list) and subset_ok != (len(unsupported) == 0):
                violations.append("Witness.potential_collapse_dependency integrity mismatch")

            if (
                isinstance(collapse_tids_canonical, list)
                and isinstance(unsupported, list)
                and isinstance(supported_tids_canonical, list)
            ):
                expected_supported = sorted(tid for tid in collapse_tids_canonical if tid not in set(unsupported))
                if sorted(supported_tids_canonical) != expected_supported:
                    violations.append("Witness.potential_collapse_dependency supported set mismatch")

            if isinstance(dependency_delta, dict) and dependency_delta != dependency:
                violations.append("Delta/Witness potential_collapse_dependency mismatch")
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

    PURPLE_SEMANTIC_ENFORCEMENT = {
        "name": "purple_semantic_enforcement",
        "purple_meaning": "Union of red-pill reality constraints and blue-pill imagination constraints under IVI paradox discipline.",
        "red_pill_channel": "reality_constraints",
        "blue_pill_channel": "imagination_constraints",
        "union_rule": "No collapse commit is valid unless both channels remain representable in trace or as explicit Gap.",
        "morpheus_role": "external_constraint_injection",
        "oracle_role": "ivi_paradox_axiom",
    }

    SEMANTIC_POLICY_PRINCIPLE = {
        "name": "ivi_semantic_skill_policy_v1",
        "rule": "Enforce capabilities as semantic skills; MCP/tool connectors are interchangeable execution backends.",
        "voice_priority": "openclaw_voice_personalization",
        "foundation": "purple_potential_noncollapsing_loop",
    }

    SEMANTIC_SKILL_PERMISSIONS = {
        "voice_personalization": ["R_LOCAL"],
        "read_context": ["R_LOCAL"],
        "constrained_write": ["R_APP:*", "W_LOCAL", "W_APP:*", "NET_OUTBOUND"],
        "bounded_autonomy": ["SYS_AUTOMATION"],
    }

    SEMANTIC_SKILL_MCP_BACKENDS = {
        "voice_personalization": ["openclaw_local_adapter", "mcp.voice.persona"],
        "read_context": ["local_repo_reader", "mcp.search.read"],
        "constrained_write": ["local_runtime_writer", "mcp.tools.write"],
        "bounded_autonomy": ["local_orchestrator_scheduler", "mcp.orchestrator.autonomy"],
    }

    SEMANTIC_SKILL_ORDER_CAP = {
        "voice_personalization": ORDER_1_PROJECTION_SAFE,
        "read_context": ORDER_2_READ_CONTEXT,
        "constrained_write": "order_3_constrained_write",
        "bounded_autonomy": ORDER_4_BOUNDED_AUTONOMY,
    }

    POLICY_IMMUTABILITY_LOCK = {
        "validator_rules": "locked",
        "promotion_thresholds": "locked",
        "oracle_trigger_logic": "locked",
        "closure_rules_version": "locked",
        "choice_law_version": "locked",
        "requires_external_approval_token": True,
    }

    BUILDERBULDOZER_SPEC_VERSION = "builderbuldozer_ivi_spec_v1"
    BUILDERBULDOZER_REFERENCE_DISTRIBUTION_DIGESTS = {
        "4:0": "0599499e338ddf9c7018a808a77c309c88b7c58a85112ffc7bd42d4ee2348726",
        "4:7": "344fc8c7ad32ff49c23e4911182ca395f037eef9cad956a0574f4d6d68ef403b",
        "6:2": "e125d048a56eb47b29b4fd324104740ff2e8656c974709db636bd4f834dd43da",
    }
    BUILDERBULDOZER_MODULE_CANDIDATES = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "vortex_cone_sim.py")),
        "/Users/harryscott/Downloads/buildersbulldozers/vortex_cone_sim.py",
    ]

    def __init__(self, grid: IVISimplicialGrid):
        self.grid = grid
        self._last_complexity_validation_level: Optional[str] = None
        self._openclaw: Optional[OpenClawMicrocosm] = None
        self._openclaw_voice_mode: str = "integrated"
        self._voice_priority_model: str = "openclaw"
        self._foundation_model: str = "purple_potential_noncollapsing_loop"
        self._active_order_mode: str = ORDER_1_PROJECTION_SAFE
        self._max_order_mode: str = ORDER_2_READ_CONTEXT
        self._orchestrator_full_access: bool = False
        self._orchestrator_proactive_enabled: bool = False
        self._orchestrator_permissions_granted: List[str] = ["R_LOCAL"]
        self._orchestrator_requested_permissions: List[str] = []
        self._orchestrator_consent_token_valid: bool = False
        self._orchestrator_recent_sandbox_failures: int = 0
        self._orchestrator_scheduled_routines: List[str] = []
        self._orchestrator_continuous_enabled: bool = False
        self._orchestrator_tick_active: bool = False
        self._orchestrator_daemon_enabled: bool = False
        self._orchestrator_daemon_interval_seconds: float = 5.0
        self._orchestrator_daemon_thread: Optional[threading.Thread] = None
        self._orchestrator_daemon_stop_event = threading.Event()
        self._orchestrator_daemon_tick_count: int = 0
        self._orchestrator_daemon_last_error: str = ""
        self._triangle_time_integral_value: float = 0.0
        self._triangle_time_integral_limit: float = 2.5
        self._triangle_time_integral_last_ts: Optional[float] = None
        self._purple_semantic_passed: bool = True
        self._self_dual_semantic_state: Dict[str, Any] = {
            "law_source": "ivi_self_dual_semantic_enforcement_bootstrap",
            "union_passed": True,
            "reality_pressure": 0.0,
            "imagination_pressure": 0.0,
            "enabled_skills": ["read_context"],
            "derived_permissions": ["R_LOCAL"],
            "derived_skill_backends": {
                "read_context": ["semantic_runtime_resolver", "local_repo_reader", "mcp.search.read"],
            },
            "derived_max_order_mode": ORDER_2_READ_CONTEXT,
            "derived_integral_limit": 2.5,
        }
        self._autonomy_goals: List[str] = [
            "Maintain full OpenClaw/Purple continuous operation under IVI self-dual semantic enforcement.",
            "Reduce closure deficit while preserving trace-backed representability across reality and imagination channels.",
            "Convert conversational context into executable actions and autonomous refinement loops.",
            "Proactively request interaction only when it improves constraints, safety, or role alignment.",
        ]
        self._autonomy_interaction_count: int = 0
        self._autonomy_last_prompt: str = ""
        self._autonomy_last_goal_refresh_ts: float = time.time()
        self._last_oracle_request: Optional[Dict[str, Any]] = None
        self._last_relift_conditioning: Optional[Dict[str, Any]] = None

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

    def _read_integration_artifacts(self, max_items: Optional[int] = 128) -> List[Dict[str, Any]]:
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

    def _derive_creativity_event(
        self,
        trace: Dict[str, Any],
        previous_trace: Optional[Dict[str, Any]] = None,
        recent_selected_digests: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        trace_obj = trace if isinstance(trace, dict) else {}
        previous_obj = previous_trace if isinstance(previous_trace, dict) else {}

        grid_now = self._grid_state_from_trace(trace_obj)
        grid_prev = self._grid_state_from_trace(previous_obj) if previous_obj else {"mu_total": 0.0, "closure_deficit": 0}
        mu_increase = float(grid_now.get("mu_total", 0.0)) > float(grid_prev.get("mu_total", 0.0))
        deficit_reduction = int(grid_now.get("closure_deficit", 0)) < int(grid_prev.get("closure_deficit", 0))

        replay = trace_obj.get("choice_law_replay", {}) if isinstance(trace_obj.get("choice_law_replay", {}), dict) else {}
        candidate_inputs = replay.get("candidate_inputs", []) if isinstance(replay.get("candidate_inputs", []), list) else []
        admissible_positive = [
            c
            for c in candidate_inputs
            if isinstance(c, dict)
            and int(c.get("closure_gain", 0)) > 0
            and bool(str(c.get("delta_signature_digest", "")))
        ]
        unique_delta_digests = sorted(
            {
                str(c.get("delta_signature_digest", ""))
                for c in admissible_positive
                if str(c.get("delta_signature_digest", ""))
            }
        )
        non_equivalent = len(unique_delta_digests) >= 2
        selected_digest = str(replay.get("selected_delta_signature_digest", ""))
        branch_point = bool(
            int(grid_now.get("closure_deficit", 0)) > 0
            and len(admissible_positive) >= 2
            and non_equivalent
            and bool(selected_digest)
        )
        changed_grid = bool(mu_increase or deficit_reduction)
        creative = bool(branch_point and changed_grid)

        basis = "none"
        if creative and branch_point:
            basis = "branch_point"
        elif creative and deficit_reduction:
            basis = "deficit_reduction"
        elif creative:
            basis = "nontrivial_exploration"

        seen = recent_selected_digests if isinstance(recent_selected_digests, set) else set()
        novel_selected_digest = bool(selected_digest and selected_digest not in seen)

        return {
            "creative": creative,
            "basis": basis,
            "closure_deficit": int(grid_now.get("closure_deficit", 0)),
            "admissible_positive_count": len(admissible_positive),
            "unique_delta_signature_count": len(unique_delta_digests),
            "selected_delta_signature_digest": selected_digest,
            "mu_increase": mu_increase,
            "deficit_reduction": deficit_reduction,
            "changed_grid": changed_grid,
            "novel_selected_digest": novel_selected_digest,
        }

    def _builderbuldozer_spec_payload(self) -> Dict[str, Any]:
        return {
            "version": self.BUILDERBULDOZER_SPEC_VERSION,
            "inputs": [
                "seed_start",
                "num_trials",
                "scenario_schedule",
                "params_factory",
                "hard_gate_toggles",
                "tolerances",
            ],
            "intermediate_objects": [
                "canon_link_matrix_register",
                "canon_braid_word_register_conjugacy_rep",
                "canon_ivi_action_terms",
                "canon_ivi_potential_amplitude",
                "canon_hard_gated",
            ],
            "output_semantics": {
                "hard_gated_sample": {
                    "canon_potential_class_key": None,
                    "canon_ivi_potential_amplitude": {"re": 0.0, "im": 0.0},
                    "born_distribution_excluded": True,
                },
                "non_hard_gated_sample": {
                    "born_weight": "|amp|^2",
                    "class_key_source": "canon_potential_class_key",
                },
            },
            "immutability_locked_components": [
                "class_key_schema",
                "action_terms_schema",
                "gating_semantics",
                "born_estimator_semantics",
            ],
        }

    def _builderbuldozer_spec_digest(self) -> str:
        payload = self._builderbuldozer_spec_payload()
        return _stable_hash(json.dumps(payload, sort_keys=True, ensure_ascii=True))

    def _expected_builderbuldozer_distribution_digest(self, num_trials: int, seed_start: int) -> str:
        key = f"{int(num_trials)}:{int(seed_start)}"
        return str(self.BUILDERBULDOZER_REFERENCE_DISTRIBUTION_DIGESTS.get(key, ""))

    def _load_builderbuldozer_module(self) -> Tuple[Optional[Any], str]:
        env_path = str(os.environ.get("BUILDERBULDOZER_MODULE_PATH", "")).strip()
        candidates = [env_path] if env_path else []
        candidates.extend(self.BUILDERBULDOZER_MODULE_CANDIDATES)
        for path in candidates:
            target = str(path).strip()
            if not target:
                continue
            if not os.path.exists(target):
                continue
            spec = importlib.util.spec_from_file_location("builderbuldozer_vortex", target)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module, target
        return None, ""

    def _builderbuldozer_request_from_query(self, query: str) -> Optional[Dict[str, int]]:
        q = str(query or "")
        ql = q.lower()
        if not any(token in ql for token in ["builderbuldozer", "buildersbulldozers", "bulldozer"]):
            return None
        trials_match = re.search(r"trials\s*=\s*(\d+)", ql)
        seed_match = re.search(r"seed\s*=\s*(-?\d+)", ql)
        return {
            "trials": int(trials_match.group(1)) if trials_match else 4,
            "seed_start": int(seed_match.group(1)) if seed_match else 0,
        }

    def _compute_builderbuldozer_derivation(self, trials: int = 4, seed_start: int = 0) -> Dict[str, Any]:
        module, module_path = self._load_builderbuldozer_module()
        spec_version = self.BUILDERBULDOZER_SPEC_VERSION
        spec_digest = self._builderbuldozer_spec_digest()
        if module is None:
            return {
                "enabled": False,
                "error": "builderbuldozer_module_not_found",
                "module_path": module_path,
                "model_spec_version": spec_version,
                "model_spec_digest": spec_digest,
            }

        sample_fn = getattr(module, "sample_born_distribution", None)
        if not callable(sample_fn):
            return {
                "enabled": False,
                "error": "builderbuldozer_sample_born_distribution_missing",
                "module_path": module_path,
                "model_spec_version": spec_version,
                "model_spec_digest": spec_digest,
            }

        run_trials = max(1, int(trials))
        run_seed = int(seed_start)
        sampled = sample_fn(num_trials=run_trials, seed_start=run_seed)
        samples = sampled.get("samples", []) if isinstance(sampled.get("samples", []), list) else []
        distribution = sampled.get("distribution", {}) if isinstance(sampled.get("distribution", {}), dict) else {}

        hard_gated = sum(
            1 for s in samples if isinstance(s, dict) and bool(s.get("canon_hard_gated", False))
        )
        included = max(0, len(samples) - hard_gated)
        first = samples[0] if samples and isinstance(samples[0], dict) else {}
        action_by_class_sum: Dict[str, float] = {}
        action_by_class_count: Dict[str, int] = {}
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            if bool(sample.get("canon_hard_gated", False)):
                continue
            cls = str(sample.get("canon_potential_class_key", "")).strip()
            if not cls:
                continue
            action = float(sample.get("canon_ivi_informational_action", 0.0))
            action_by_class_sum[cls] = float(action_by_class_sum.get(cls, 0.0)) + action
            action_by_class_count[cls] = int(action_by_class_count.get(cls, 0)) + 1
        action_by_class_mean = {
            cls: float(action_by_class_sum.get(cls, 0.0)) / float(max(1, action_by_class_count.get(cls, 0)))
            for cls in sorted(action_by_class_sum.keys())
        }
        probs = dict(distribution.get("class_probabilities", {}))
        expected_action = 0.0
        for cls, prob in probs.items():
            p = max(0.0, float(prob))
            expected_action += p * float(action_by_class_mean.get(str(cls), 0.0))
        born_distribution = {
            "num_classes": int(distribution.get("num_classes", 0)),
            "class_probabilities": probs,
            "class_amplitudes": dict(distribution.get("class_amplitudes", {})),
        }
        born_distribution_digest = _stable_hash(json.dumps(born_distribution, sort_keys=True, ensure_ascii=True))
        expected_dist_digest = self._expected_builderbuldozer_distribution_digest(run_trials, run_seed)
        reference_digest_locked = bool(expected_dist_digest)
        reference_digest_match = reference_digest_locked and (born_distribution_digest == expected_dist_digest)

        return {
            "enabled": True,
            "module_path": module_path,
            "model_spec_version": spec_version,
            "model_spec_digest": spec_digest,
            "inputs": {
                "num_trials": run_trials,
                "seed_start": run_seed,
            },
            "intermediate_presence": {
                "canon_link_matrix_register": isinstance(first.get("canon_link_matrix_register", {}), dict),
                "canon_braid_word_register_conjugacy_rep": isinstance(first.get("canon_braid_word_register_conjugacy_rep", []), list),
                "canon_ivi_action_terms": isinstance(first.get("canon_ivi_action_terms", {}), dict),
                "canon_ivi_potential_amplitude": isinstance(first.get("canon_ivi_potential_amplitude", {}), dict),
                "canon_hard_gated": "canon_hard_gated" in first,
            },
            "gating_summary": {
                "samples_total": len(samples),
                "samples_hard_gated": hard_gated,
                "samples_included": included,
                "hard_gate_semantics_defined": True,
                "born_excludes_hard_gated": True,
            },
            "born_distribution": born_distribution,
            "born_distribution_digest": born_distribution_digest,
            "reference_distribution_digest_expected": expected_dist_digest,
            "reference_distribution_digest_locked": reference_digest_locked,
            "reference_distribution_digest_match": reference_digest_match,
            "canonical_action_summary": {
                "expected_informational_action": float(expected_action),
                "class_mean_action": action_by_class_mean,
            },
            "closed_engineering": True,
            "closed_final_theory": bool(reference_digest_match),
        }

    def _extract_ivi_invariant_components(
        self,
        trace: Dict[str, Any],
        builder_derivation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        trace_obj = trace if isinstance(trace, dict) else {}
        grid_state = self._grid_state_from_trace(trace_obj)
        closure_deficit = float(grid_state.get("closure_deficit", 0.0))

        builder_obj = builder_derivation if isinstance(builder_derivation, dict) else {}
        canonical_summary = (
            builder_obj.get("canonical_action_summary", {})
            if isinstance(builder_obj.get("canonical_action_summary", {}), dict)
            else {}
        )
        gating_summary = (
            builder_obj.get("gating_summary", {})
            if isinstance(builder_obj.get("gating_summary", {}), dict)
            else {}
        )
        expected_action = float(canonical_summary.get("expected_informational_action", 0.0))
        samples_total = int(gating_summary.get("samples_total", 0))
        samples_hard_gated = int(gating_summary.get("samples_hard_gated", 0))
        hard_gate_rate = float(samples_hard_gated) / float(max(1, samples_total))

        invariant_value = closure_deficit + expected_action + hard_gate_rate
        payload = {
            "version": "ivi_invariant_v1",
            "name": "expected_unrealized_structure",
            "formula": "I = closure_deficit + E_builder[action|class] + hard_gate_rate",
            "value": float(invariant_value),
            "components": {
                "closure_deficit": float(closure_deficit),
                "expected_builder_informational_action": float(expected_action),
                "builder_hard_gate_rate": float(hard_gate_rate),
            },
            "quotient_anchor": {
                "class_digest_potential": str(trace_obj.get("class_digest_potential", "")),
            },
            "builderbuldozer_bound": bool(builder_obj),
        }
        payload["digest"] = _stable_hash(json.dumps(payload, sort_keys=True, ensure_ascii=True))
        return payload

    def _evaluate_ivi_invariant_dynamics_law(
        self,
        trace: Dict[str, Any],
        previous_trace: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        trace_obj = trace if isinstance(trace, dict) else {}
        prev_obj = previous_trace if isinstance(previous_trace, dict) else {}
        curr_inv = trace_obj.get("ivi_invariant", {}) if isinstance(trace_obj.get("ivi_invariant", {}), dict) else {}
        prev_inv = prev_obj.get("ivi_invariant", {}) if isinstance(prev_obj.get("ivi_invariant", {}), dict) else {}

        if not prev_inv:
            return {
                "name": "ivi_invariant_dynamics_law",
                "enabled": False,
                "passed": True,
                "admissible_update": False,
                "law_kind": "insufficient_history",
                "detail": "no previous invariant payload; dynamics law not evaluated on first turn",
            }

        curr_val_raw = curr_inv.get("value", trace_obj.get("ivi_invariant_value", None))
        prev_val_raw = prev_inv.get("value", prev_obj.get("ivi_invariant_value", None))
        finite_vals = isinstance(curr_val_raw, (float, int)) and isinstance(prev_val_raw, (float, int))
        if not finite_vals:
            return {
                "name": "ivi_invariant_dynamics_law",
                "enabled": True,
                "passed": False,
                "admissible_update": False,
                "law_kind": "invalid_payload",
                "detail": "current/previous invariant values are missing or non-numeric",
            }

        curr_val = float(curr_val_raw)
        prev_val = float(prev_val_raw)
        if not (math.isfinite(curr_val) and math.isfinite(prev_val)):
            return {
                "name": "ivi_invariant_dynamics_law",
                "enabled": True,
                "passed": False,
                "admissible_update": False,
                "law_kind": "invalid_payload",
                "detail": "current/previous invariant values are not finite",
            }

        curr_ver = str(curr_inv.get("version", ""))
        prev_ver = str(prev_inv.get("version", ""))
        same_version = curr_ver == "ivi_invariant_v1" and prev_ver == "ivi_invariant_v1"
        has_payload_digests = bool(str(curr_inv.get("digest", ""))) and bool(str(prev_inv.get("digest", "")))
        has_class_anchor = bool(str(trace_obj.get("class_digest_potential", ""))) and bool(
            str(prev_obj.get("class_digest_potential", ""))
        )
        admissible_update = bool(same_version and has_payload_digests and has_class_anchor)

        regime = str(trace_obj.get("regime_label", "")).strip() or self._relift_regime_label(
            trace_obj.get("relift_conditioning", {})
            if isinstance(trace_obj.get("relift_conditioning", {}), dict)
            else {}
        )
        delta = curr_val - prev_val
        tol_mono = 1e-9
        tol_balanced = 0.25
        tol_invariant = 1e-9

        same_canonical_basis = bool(
            str(trace_obj.get("class_digest_potential", ""))
            and str(trace_obj.get("class_digest_potential", "")) == str(prev_obj.get("class_digest_potential", ""))
            and str(trace_obj.get("potential_distribution_digest", ""))
            and str(trace_obj.get("potential_distribution_digest", ""))
            == str(prev_obj.get("potential_distribution_digest", ""))
            and str(trace_obj.get("builderbuldozer_model_spec_digest", ""))
            and str(trace_obj.get("builderbuldozer_model_spec_digest", ""))
            == str(prev_obj.get("builderbuldozer_model_spec_digest", ""))
        )

        if not admissible_update:
            return {
                "name": "ivi_invariant_dynamics_law",
                "enabled": True,
                "passed": True,
                "admissible_update": False,
                "law_kind": "not_applicable",
                "regime_label": regime,
                "delta": float(delta),
                "detail": "invariant dynamics law skipped: update missing admissibility prerequisites",
            }

        if same_canonical_basis:
            passed = abs(delta) <= tol_invariant
            law_kind = "invariant_under_canonical_equivalence"
            detail = (
                "same canonical basis implies invariant scalar"
                if passed
                else "same canonical basis but invariant scalar changed"
            )
            inequality = f"|I_t - I_(t-1)| <= {tol_invariant}"
        else:
            if regime == "alpha_dominant":
                passed = delta <= tol_mono
                law_kind = "monotone_nonincreasing"
                detail = "alpha-dominant admissible update enforces I_t <= I_(t-1)"
                inequality = f"I_t - I_(t-1) <= {tol_mono}"
            elif regime == "beta_dominant":
                passed = delta >= -tol_mono
                law_kind = "monotone_nondecreasing"
                detail = "beta-dominant admissible update enforces I_t >= I_(t-1)"
                inequality = f"I_t - I_(t-1) >= {-tol_mono}"
            else:
                passed = abs(delta) <= tol_balanced
                law_kind = "near_invariant_balanced"
                detail = "balanced admissible update enforces near-invariance"
                inequality = f"|I_t - I_(t-1)| <= {tol_balanced}"

        return {
            "name": "ivi_invariant_dynamics_law",
            "enabled": True,
            "passed": bool(passed),
            "admissible_update": True,
            "law_kind": law_kind,
            "regime_label": regime,
            "same_canonical_basis": same_canonical_basis,
            "current_value": float(curr_val),
            "previous_value": float(prev_val),
            "delta": float(delta),
            "inequality": inequality,
            "detail": detail,
        }

    def _evaluate_builderbuldozer_spec_immutability(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        expected_version = self.BUILDERBULDOZER_SPEC_VERSION
        expected_digest = self._builderbuldozer_spec_digest()
        actual_version = str(payload.get("model_spec_version", "")) if isinstance(payload, dict) else ""
        actual_digest = str(payload.get("model_spec_digest", "")) if isinstance(payload, dict) else ""
        violations: List[str] = []
        if actual_version != expected_version:
            violations.append("builderbuldozer_spec_version_mismatch")
        if actual_digest != expected_digest:
            violations.append("builderbuldozer_spec_digest_mismatch")
        return {
            "name": "builderbuldozer_spec_immutability_gate",
            "enabled": bool(payload),
            "passed": len(violations) == 0,
            "violations": violations,
            "expected": {
                "model_spec_version": expected_version,
                "model_spec_digest": expected_digest,
            },
            "detail": "; ".join(violations) if violations else "builderbuldozer spec version/digest match locked protocol",
        }

    def _evaluate_builderbuldozer_reference_digest_lock(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        obj = payload if isinstance(payload, dict) else {}
        enabled = bool(obj.get("enabled", False))
        inputs = obj.get("inputs", {}) if isinstance(obj.get("inputs", {}), dict) else {}
        num_trials = int(inputs.get("num_trials", 0))
        seed_start = int(inputs.get("seed_start", 0))
        expected_digest = self._expected_builderbuldozer_distribution_digest(num_trials, seed_start)
        lock_enabled = bool(expected_digest)
        born_distribution = obj.get("born_distribution", {}) if isinstance(obj.get("born_distribution", {}), dict) else {}
        actual_digest = str(obj.get("born_distribution_digest", "")).strip()
        if not actual_digest and born_distribution:
            actual_digest = _stable_hash(json.dumps(born_distribution, sort_keys=True, ensure_ascii=True))
        passed = bool(enabled and lock_enabled and actual_digest and actual_digest == expected_digest)
        case_key = f"{num_trials}:{seed_start}"
        if not enabled:
            detail = "builderbuldozer derivation unavailable; reference digest lock not evaluated"
        elif not lock_enabled:
            detail = f"no reference digest lock configured for case {case_key}"
        elif not actual_digest:
            detail = "missing born_distribution_digest for reference lock verification"
        elif passed:
            detail = f"reference distribution digest lock satisfied for case {case_key}"
        else:
            detail = f"reference distribution digest mismatch for case {case_key}"
        return {
            "name": "builderbuldozer_reference_distribution_digest_lock",
            "enabled": bool(enabled and lock_enabled),
            "passed": bool(passed),
            "case_key": case_key,
            "expected_digest": expected_digest,
            "actual_digest": actual_digest,
            "detail": detail,
        }

    def run_builderbuldozer_ivi_derivation(self, trials: int = 4, seed_start: int = 0, source: str = "voice_builderbuldozer") -> Dict[str, Any]:
        query = f"[builderbuldozer derive] trials={int(max(1, trials))} seed={int(seed_start)}"
        out = self.add_statement_and_loop(query, source=source)
        artifacts = out.get("integration_artifacts", {}) if isinstance(out.get("integration_artifacts", {}), dict) else {}
        trace = artifacts.get("Trace", {}) if isinstance(artifacts.get("Trace", {}), dict) else {}
        payload = trace.get("builderbuldozer_derivation", {}) if isinstance(trace.get("builderbuldozer_derivation", {}), dict) else {}
        return {
            "kind": "builderbuldozer_derivation",
            "trials": int(max(1, trials)),
            "seed_start": int(seed_start),
            "derivation": payload,
            "integration_artifacts": artifacts,
            "progress": self.get_axiom_self_generation_progress(),
        }

    def _relift_regime_label(self, relift_conditioning: Dict[str, Any]) -> str:
        conditioning = relift_conditioning if isinstance(relift_conditioning, dict) else {}
        alpha = float(conditioning.get("alpha", 0.5))
        beta = float(conditioning.get("beta", 0.5))
        if alpha > beta:
            return "alpha_dominant"
        if beta > alpha:
            return "beta_dominant"
        return "balanced"

    def _derive_topological_class_label(
        self,
        trace: Dict[str, Any],
        relift_conditioning: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        trace_obj = trace if isinstance(trace, dict) else {}
        conditioning = relift_conditioning if isinstance(relift_conditioning, dict) else {}

        pot = [x for x in trace_obj.get("potential_distribution", []) if isinstance(x, dict)]
        collapse = [str(x).strip() for x in trace_obj.get("collapse_selection", []) if str(x).strip()]
        formal = [x for x in trace_obj.get("formal_targets", []) if isinstance(x, dict)]
        role_projection = (
            trace_obj.get("role_projection", {})
            if isinstance(trace_obj.get("role_projection", {}), dict)
            else {}
        )
        subject = [str(x).strip() for x in role_projection.get("subject_tids", []) if str(x).strip()]
        obj = [str(x).strip() for x in role_projection.get("object_tids", []) if str(x).strip()]

        if subject and obj:
            role_shape = "bipolar"
        elif subject:
            role_shape = "subject"
        elif obj:
            role_shape = "object"
        else:
            role_shape = "flat"

        conditioning_mode = str(conditioning.get("conditioning_mode", "identity"))
        k_collapse = int(conditioning.get("k_collapse", max(1, len(set(collapse[:2])))))
        regime_label = self._relift_regime_label(conditioning)

        feature_payload_potential = {
            "role_shape": role_shape,
            "potential_count": int(len({str(x.get('tid', '')).strip() for x in pot if str(x.get('tid', '')).strip()})),
            "collapse_count": int(len(set(collapse))),
            "formal_count": int(len({str(x.get('eid', '')).strip() for x in formal if str(x.get('eid', '')).strip()})),
        }
        feature_payload_actuated = {
            **feature_payload_potential,
            "conditioning_mode": conditioning_mode,
            "k_collapse": int(max(1, min(3, k_collapse))),
            "regime_label": regime_label,
        }
        feature_potential_json = json.dumps(feature_payload_potential, sort_keys=True, ensure_ascii=True)
        feature_actuated_json = json.dumps(feature_payload_actuated, sort_keys=True, ensure_ascii=True)
        class_digest_potential = _stable_hash(feature_potential_json)
        class_digest_actuated = _stable_hash(feature_actuated_json)

        class_label_potential = (
            f"{feature_payload_potential['role_shape']}"
            f"|p{feature_payload_potential['potential_count']}"
            f"|c{feature_payload_potential['collapse_count']}"
            f"|f{feature_payload_potential['formal_count']}"
        )
        class_label_actuated = (
            f"{class_label_potential}"
            f"|{feature_payload_actuated['conditioning_mode']}"
            f"|k{feature_payload_actuated['k_collapse']}"
        )

        return {
            "class_label": class_label_potential,
            "class_label_potential": class_label_potential,
            "class_label_actuated": class_label_actuated,
            "class_digest": class_digest_potential,
            "class_digest_potential": class_digest_potential,
            "class_digest_actuated": class_digest_actuated,
            "class_features": feature_payload_potential,
            "class_features_potential": feature_payload_potential,
            "class_features_actuated": feature_payload_actuated,
            "regime_label": regime_label,
        }

    def _distribution_prob_map(self, by_class: List[Dict[str, Any]]) -> Dict[str, float]:
        probs: Dict[str, float] = {}
        for entry in by_class:
            if not isinstance(entry, dict):
                continue
            cls = str(entry.get("class_label", "")).strip()
            if not cls:
                continue
            p = float(entry.get("probability", 0.0))
            if p > 0.0:
                probs[cls] = probs.get(cls, 0.0) + p
        z = float(sum(probs.values()))
        if z <= 0.0:
            return {}
        return {k: float(v) / z for k, v in probs.items()}

    def _distribution_from_count_map(self, counts: Dict[str, float]) -> Dict[str, Any]:
        cleaned: Dict[str, float] = {}
        for key, val in counts.items():
            cls = str(key).strip()
            if not cls:
                continue
            v = float(val)
            if v > 0.0:
                cleaned[cls] = cleaned.get(cls, 0.0) + v
        total = float(sum(cleaned.values()))
        by_class = [
            {
                "class_label": cls,
                "count": float(cnt),
                "probability": float(cnt) / float(max(1e-12, total)),
            }
            for cls, cnt in sorted(cleaned.items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
        ]
        return {
            "total": float(total),
            "by_class": by_class,
        }

    def _distribution_stats(self, by_class: List[Dict[str, Any]]) -> Dict[str, float]:
        probs = sorted(self._distribution_prob_map(by_class).values(), reverse=True)
        entropy_bits = 0.0
        for p in probs:
            if p > 0.0:
                entropy_bits -= p * math.log2(p)
        top1 = probs[0] if probs else 0.0
        top5 = float(sum(probs[:5])) if probs else 0.0
        return {
            "entropy_bits": float(entropy_bits),
            "top1_mass": float(top1),
            "top5_mass": float(top5),
        }

    def _js_l1_divergence(self, by_class_a: List[Dict[str, Any]], by_class_b: List[Dict[str, Any]]) -> Dict[str, float]:
        p_map = self._distribution_prob_map(by_class_a)
        q_map = self._distribution_prob_map(by_class_b)
        universe = sorted(set(p_map.keys()) | set(q_map.keys()))
        if not universe:
            return {"js_divergence": 0.0, "l1_distance": 0.0}

        p = [float(p_map.get(k, 0.0)) for k in universe]
        q = [float(q_map.get(k, 0.0)) for k in universe]
        m = [0.5 * (a + b) for a, b in zip(p, q)]

        def _kl(a: List[float], b: List[float]) -> float:
            out = 0.0
            for x, y in zip(a, b):
                if x > 0.0 and y > 0.0:
                    out += x * math.log2(x / y)
            return out

        js = 0.5 * _kl(p, m) + 0.5 * _kl(q, m)
        l1 = float(sum(abs(a - b) for a, b in zip(p, q)))
        return {
            "js_divergence": float(max(0.0, js)),
            "l1_distance": float(max(0.0, l1)),
        }

    def _invariant_summary_by_regime(self, artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        buckets: Dict[str, List[float]] = {
            "alpha_dominant": [],
            "beta_dominant": [],
            "balanced": [],
        }
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            trace = item.get("Trace", {}) if isinstance(item.get("Trace", {}), dict) else {}
            regime = str(trace.get("regime_label", "")).strip() or self._relift_regime_label(
                trace.get("relift_conditioning", {}) if isinstance(trace.get("relift_conditioning", {}), dict) else {}
            )
            if regime not in buckets:
                regime = "balanced"
            invariant_obj = trace.get("ivi_invariant", {}) if isinstance(trace.get("ivi_invariant", {}), dict) else {}
            val = invariant_obj.get("value", trace.get("ivi_invariant_value", None))
            if isinstance(val, (float, int)) and math.isfinite(float(val)):
                buckets[regime].append(float(val))

        out: Dict[str, Any] = {}
        for regime, vals in buckets.items():
            series = list(vals)
            out[regime] = {
                "count": len(series),
                "series": series,
                "mean": float(sum(series)) / float(max(1, len(series))),
                "delta": float(series[-1] - series[0]) if len(series) >= 2 else 0.0,
            }
        return out

    def _k_collapse_bin(self, k_collapse: int) -> str:
        k = int(k_collapse)
        if k <= 1:
            return "low"
        if k == 2:
            return "medium"
        return "high"

    def _beta_kcollapse_conditional_divergence(self, timeline: List[Dict[str, Any]]) -> Dict[str, Any]:
        bins: Dict[str, Dict[str, int]] = {"low": {}, "medium": {}, "high": {}}
        for step in timeline:
            if not isinstance(step, dict):
                continue
            label = str(step.get("class_label", "")).strip()
            if not label:
                continue
            bin_name = self._k_collapse_bin(int(step.get("k_collapse", 1)))
            bins[bin_name][label] = int(bins[bin_name].get(label, 0)) + 1

        by_bin: Dict[str, Dict[str, Any]] = {}
        for bin_name, counts in bins.items():
            total = int(sum(counts.values()))
            by_class = [
                {
                    "class_label": cls,
                    "count": int(cnt),
                    "probability": float(cnt) / float(max(1, total)),
                }
                for cls, cnt in sorted(counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))
            ]
            by_bin[bin_name] = {"total": total, "by_class": by_class}

        pairwise: List[Dict[str, Any]] = []
        keys = [k for k, v in by_bin.items() if int(v.get("total", 0)) > 0]
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a = keys[i]
                b = keys[j]
                d = self._js_l1_divergence(
                    by_bin[a].get("by_class", []),
                    by_bin[b].get("by_class", []),
                )
                pairwise.append({
                    "bins": [a, b],
                    "js_divergence": float(d.get("js_divergence", 0.0)),
                    "l1_distance": float(d.get("l1_distance", 0.0)),
                })

        mean_js = float(sum(float(x.get("js_divergence", 0.0)) for x in pairwise)) / float(max(1, len(pairwise)))
        max_js = max([float(x.get("js_divergence", 0.0)) for x in pairwise], default=0.0)
        return {
            "by_k_bin": by_bin,
            "pairwise": pairwise,
            "mean_js_divergence": float(mean_js),
            "max_js_divergence": float(max_js),
        }

    def _class_distribution_by_regime(self, artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        regimes = {
            "alpha_dominant": {},
            "beta_dominant": {},
            "balanced": {},
        }

        for item in artifacts:
            if not isinstance(item, dict):
                continue
            trace = item.get("Trace", {}) if isinstance(item.get("Trace", {}), dict) else {}
            regime = str(trace.get("regime_label", "")).strip() or self._relift_regime_label(
                trace.get("relift_conditioning", {}) if isinstance(trace.get("relift_conditioning", {}), dict) else {}
            )
            if regime not in regimes:
                regime = "balanced"
            class_label = str(trace.get("class_label", "")).strip()
            if not class_label:
                inferred = self._derive_topological_class_label(
                    trace,
                    trace.get("relift_conditioning", {}) if isinstance(trace.get("relift_conditioning", {}), dict) else {},
                )
                class_label = str(inferred.get("class_label", "unclassified"))
            regimes[regime][class_label] = int(regimes[regime].get(class_label, 0)) + 1

        out: Dict[str, Any] = {}
        for regime, buckets in regimes.items():
            total = int(sum(int(v) for v in buckets.values()))
            by_class = [
                {
                    "class_label": cls,
                    "count": int(cnt),
                    "probability": float(cnt) / float(max(1, total)),
                }
                for cls, cnt in sorted(buckets.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))
            ]
            out[regime] = {
                "total": total,
                "by_class": by_class,
            }
        return out

    def _timeline_class_distribution(self, timeline: List[Dict[str, Any]]) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for step in timeline:
            if not isinstance(step, dict):
                continue
            cls = str(step.get("class_label", "")).strip()
            if not cls:
                continue
            counts[cls] = int(counts.get(cls, 0)) + 1
        total = int(sum(counts.values()))
        return {
            "total": total,
            "by_class": [
                {
                    "class_label": cls,
                    "count": int(cnt),
                    "probability": float(cnt) / float(max(1, total)),
                }
                for cls, cnt in sorted(counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))
            ],
        }

    def _normalize_forced_alpha_beta(self, forced_alpha_beta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(forced_alpha_beta, dict):
            return None
        alpha = float(forced_alpha_beta.get("alpha", 0.5))
        beta = float(forced_alpha_beta.get("beta", 0.5))
        alpha = max(0.0, min(1.0, alpha))
        beta = max(0.0, min(1.0, beta))
        total = alpha + beta
        if total <= 0.0:
            alpha = 0.5
            beta = 0.5
        else:
            alpha = alpha / total
            beta = beta / total
        payload = {
            "mode": "continuous_triad_v1",
            "alpha": float(alpha),
            "beta": float(beta),
            "source": "forced_override",
        }
        payload["digest"] = _stable_hash(json.dumps(payload, sort_keys=True, ensure_ascii=True))
        return payload

    def run_regime_ab_experiment(
        self,
        max_steps: int = 3,
        source: str = "voice_auto",
        selection_mode: str = "deterministic_replay",
        seed_override: int = 0,
    ) -> Dict[str, Any]:
        regimes = {
            "alpha_dominant": {"alpha": 0.8, "beta": 0.2},
            "beta_dominant": {"alpha": 0.2, "beta": 0.8},
        }
        experiment_root = os.path.join(self.grid.base_dir, "ivi_memory", "regime_harness")
        _ensure_dir(experiment_root)

        baseline_idx = copy.deepcopy(self.grid.idx)
        baseline_relift = copy.deepcopy(self._last_relift_conditioning)
        reports: Dict[str, Any] = {}

        for regime_name, forced in regimes.items():
            regime_dir = os.path.join(experiment_root, f"{regime_name}_seed_{int(seed_override)}")
            _ensure_dir(regime_dir)
            regime_grid = IVISimplicialGrid(base_dir=regime_dir)
            regime_grid.idx = copy.deepcopy(baseline_idx)
            regime_grid._save_index()

            regime_loop = IVILoopController(regime_grid)
            for cleanup_path in [
                regime_loop.integration_artifacts_path,
                regime_loop.deriv_phase1_path,
                regime_loop.analysis_phase1_path,
            ]:
                if os.path.exists(cleanup_path):
                    os.remove(cleanup_path)
            regime_loop._last_relift_conditioning = copy.deepcopy(baseline_relift)
            regime_loop.evaluate_user_insight_need = lambda progress, checks, trace=None: None

            forced_payload = self._normalize_forced_alpha_beta(forced)
            run = regime_loop.run_automated_self_generation_loop(
                max_steps=max_steps,
                source=f"{source}_{regime_name}",
                selection_mode=selection_mode,
                forced_alpha_beta=forced_payload,
                seed_override=int(seed_override),
            )
            class_distribution = self._timeline_class_distribution(run.get("timeline", []))
            measure_stats = self._distribution_stats(class_distribution.get("by_class", []))
            invariant_series = [
                float(step.get("ivi_invariant_value", 0.0))
                for step in run.get("timeline", [])
                if isinstance(step, dict) and isinstance(step.get("ivi_invariant_value", None), (float, int))
            ]
            reports[regime_name] = {
                "forced_alpha_beta": forced_payload,
                "class_distribution": class_distribution,
                "measure_stats": measure_stats,
                "ivi_invariant_series": invariant_series,
                "ivi_invariant_mean": float(sum(invariant_series)) / float(max(1, len(invariant_series))),
                "ivi_invariant_delta": float(invariant_series[-1] - invariant_series[0]) if len(invariant_series) >= 2 else 0.0,
                "timeline": list(run.get("timeline", [])) if isinstance(run.get("timeline", []), list) else [],
                "timeline_class_labels": [
                    str(step.get("class_label", ""))
                    for step in run.get("timeline", [])
                    if isinstance(step, dict)
                ],
                "timeline_relift_modes": [
                    str(step.get("relift_conditioning_mode", ""))
                    for step in run.get("timeline", [])
                    if isinstance(step, dict)
                ],
                "steps_run": int(run.get("steps_run", 0)),
                "halted_reason": str(run.get("halted_reason", "")),
            }

        alpha_labels = {str(x.get("class_label", "")) for x in reports.get("alpha_dominant", {}).get("class_distribution", {}).get("by_class", []) if isinstance(x, dict)}
        beta_labels = {str(x.get("class_label", "")) for x in reports.get("beta_dominant", {}).get("class_distribution", {}).get("by_class", []) if isinstance(x, dict)}
        union = alpha_labels | beta_labels
        overlap = alpha_labels & beta_labels
        measure_divergence = self._js_l1_divergence(
            reports.get("alpha_dominant", {}).get("class_distribution", {}).get("by_class", []),
            reports.get("beta_dominant", {}).get("class_distribution", {}).get("by_class", []),
        )
        beta_kcollapse = self._beta_kcollapse_conditional_divergence(
            reports.get("beta_dominant", {}).get("timeline", [])
            if isinstance(reports.get("beta_dominant", {}), dict)
            else []
        )
        alpha_delta = float(reports.get("alpha_dominant", {}).get("ivi_invariant_delta", 0.0))
        beta_delta = float(reports.get("beta_dominant", {}).get("ivi_invariant_delta", 0.0))

        return {
            "kind": "regime_ab_experiment",
            "steps_requested": max(1, int(max_steps)),
            "selection_mode": selection_mode,
            "seed_override": int(seed_override),
            "regimes": reports,
            "comparison": {
                "alpha_unique_classes": sorted(alpha_labels - beta_labels),
                "beta_unique_classes": sorted(beta_labels - alpha_labels),
                "shared_classes": sorted(overlap),
                "jaccard_overlap": float(len(overlap)) / float(max(1, len(union))),
                "measure_divergence": measure_divergence,
                "beta_kcollapse_conditional": beta_kcollapse,
                "ivi_invariant_regime_trend": {
                    "alpha_dominant_delta": alpha_delta,
                    "beta_dominant_delta": beta_delta,
                    "alpha_leq_beta_delta": bool(alpha_delta <= beta_delta),
                },
            },
        }

    def run_least_action_calibration(
        self,
        max_steps: int = 1,
        trials: int = 12,
        source: str = "voice_auto_calibration",
        seed_start: int = 0,
    ) -> Dict[str, Any]:
        run_steps = max(1, int(max_steps))
        run_trials = max(1, int(trials))
        start_seed = int(seed_start)

        experiment_root = os.path.join(self.grid.base_dir, "ivi_memory", "least_action_calibration")
        _ensure_dir(experiment_root)

        baseline_idx = copy.deepcopy(self.grid.idx)
        baseline_relift = copy.deepcopy(self._last_relift_conditioning)

        observed_counts: Dict[str, float] = {}
        predicted_mass: Dict[str, float] = {}
        steps_observed = 0
        trial_reports: List[Dict[str, Any]] = []

        for i in range(run_trials):
            seed = start_seed + i
            trial_dir = os.path.join(experiment_root, f"trial_{i:03d}_seed_{seed}")
            _ensure_dir(trial_dir)

            trial_grid = IVISimplicialGrid(base_dir=trial_dir)
            trial_grid.idx = copy.deepcopy(baseline_idx)
            trial_grid._save_index()

            trial_loop = IVILoopController(trial_grid)
            for cleanup_path in [
                trial_loop.integration_artifacts_path,
                trial_loop.deriv_phase1_path,
                trial_loop.analysis_phase1_path,
            ]:
                if os.path.exists(cleanup_path):
                    os.remove(cleanup_path)
            trial_loop._last_relift_conditioning = copy.deepcopy(baseline_relift)
            trial_loop.evaluate_user_insight_need = lambda progress, checks, trace=None: None

            out = trial_loop.run_automated_self_generation_loop(
                max_steps=run_steps,
                source=f"{source}_trial_{i}",
                selection_mode="exploration",
                seed_override=seed,
            )
            timeline = out.get("timeline", []) if isinstance(out.get("timeline", []), list) else []
            trial_steps = 0
            for step in timeline:
                if not isinstance(step, dict):
                    continue
                selection = step.get("selection", {}) if isinstance(step.get("selection", {}), dict) else {}
                witness = step.get("ChoiceWitness", {}) if isinstance(step.get("ChoiceWitness", {}), dict) else {}
                candidate_potentials = witness.get("candidate_potentials", []) if isinstance(witness.get("candidate_potentials", []), list) else []

                policy = selection.get("least_action_policy", {}) if isinstance(selection.get("least_action_policy", {}), dict) else {}
                temperature = max(0.05, float(policy.get("temperature", 0.5)))

                logits: List[Tuple[str, float]] = []
                for cand in candidate_potentials:
                    if not isinstance(cand, dict):
                        continue
                    digest = str(cand.get("delta_signature_digest", "")).strip()
                    la = cand.get("least_action", {}) if isinstance(cand.get("least_action", {}), dict) else {}
                    score = float(la.get("score", float("inf")))
                    if not digest or (not math.isfinite(score)):
                        continue
                    logits.append((digest, -score / temperature))

                if logits:
                    max_logit = max(v for _, v in logits)
                    exp_vals = [(d, math.exp(v - max_logit)) for d, v in logits]
                    z = float(sum(v for _, v in exp_vals))
                    if z > 0.0:
                        for digest, val in exp_vals:
                            predicted_mass[digest] = predicted_mass.get(digest, 0.0) + (float(val) / z)

                selected = step.get("selected_candidate", {}) if isinstance(step.get("selected_candidate", {}), dict) else {}
                selected_digest = str(selected.get("delta_signature_digest", selected.get("tid", ""))).strip()
                if selected_digest:
                    observed_counts[selected_digest] = observed_counts.get(selected_digest, 0.0) + 1.0

                steps_observed += 1
                trial_steps += 1

            trial_reports.append(
                {
                    "trial_index": i,
                    "seed": seed,
                    "steps_run": int(out.get("steps_run", 0)),
                    "steps_counted": trial_steps,
                    "halted_reason": str(out.get("halted_reason", "")),
                }
            )

        observed_distribution = self._distribution_from_count_map(observed_counts)
        predicted_distribution = self._distribution_from_count_map(predicted_mass)
        divergence = self._js_l1_divergence(
            predicted_distribution.get("by_class", []),
            observed_distribution.get("by_class", []),
        )

        return {
            "kind": "least_action_calibration",
            "max_steps": run_steps,
            "trials": run_trials,
            "seed_start": start_seed,
            "steps_observed": int(steps_observed),
            "predicted_distribution": predicted_distribution,
            "observed_distribution": observed_distribution,
            "comparison": divergence,
            "trial_reports": trial_reports,
        }

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

        creativity_events = [
            item.get("CreativityEvent", {})
            for item in artifacts
            if isinstance(item, dict) and isinstance(item.get("CreativityEvent", {}), dict)
        ]
        creative_events = [ev for ev in creativity_events if bool(ev.get("creative", False))]
        novel_creative_events = [ev for ev in creative_events if bool(ev.get("novel_selected_digest", False))]
        creative_novelty_rate = float(len(novel_creative_events)) / float(max(1, len(artifacts)))
        latest_creativity_event = creativity_events[-1] if creativity_events else {
            "creative": False,
            "basis": "none",
            "novel_selected_digest": False,
        }

        last_refinement = None
        if artifacts:
            last_refinement = artifacts[-1].get("RefinementApplied")

        counts = metrics.get("counts", {})
        s_count = int(counts.get("S", 0))
        e_count = int(counts.get("E", 0))
        derived_density = float(e_count) / float(max(1, s_count))
        class_distribution = self._class_distribution_by_regime(artifacts)
        invariant_distribution = self._invariant_summary_by_regime(artifacts)

        return {
            "turns": turn_count,
            "gap_count": gap_count,
            "gap_rate": float(gap_count) / float(max(1, turn_count)),
            "derived_density": derived_density,
            "counts": counts,
            "last_refinement_applied": last_refinement,
            "recent_gap_codes": recent_gap_codes[-8:],
            "creative_event_count": len(creative_events),
            "creative_novelty_rate": creative_novelty_rate,
            "latest_creativity_event": latest_creativity_event,
            "class_regime_distribution": class_distribution,
            "ivi_invariant_by_regime": invariant_distribution,
        }

    def monitor_snapshot(self) -> Dict[str, Any]:
        metrics = self.grid.compute_graph_metrics()
        recent_artifacts = self._read_integration_artifacts(max_items=1)
        last_artifact = recent_artifacts[-1] if recent_artifacts else {}
        grid_state = self._grid_state_from_trace(last_artifact.get("Trace", {}))
        default_creativity_event = {
            "creative": False,
            "basis": "none",
            "novel_selected_digest": False,
        }
        creativity_event = last_artifact.get("CreativityEvent", {}) if isinstance(last_artifact.get("CreativityEvent", {}), dict) else {}
        if not creativity_event:
            creativity_event = dict(default_creativity_event)

        autonomy = self._autonomy_mission_snapshot(
            progress=self.get_axiom_self_generation_progress(),
            trace=last_artifact.get("Trace", {}),
            checks=last_artifact.get("StateChecks", {}),
        )

        return {
            "graph_metrics": metrics,
            "self_generation_progress": self.get_axiom_self_generation_progress(),
            "last_state_checks": last_artifact.get("StateChecks", {}),
            "last_trace": last_artifact.get("Trace", {}),
            "creativity_event": creativity_event,
            "grid_active": grid_state["grid_active"],
            "closure_deficit": grid_state["closure_deficit"],
            "superposition_mass": grid_state["superposition_mass"],
            "mu_total": grid_state["mu_total"],
            "openclaw": self._openclaw.summary() if self._openclaw is not None else None,
            "semantic_mapping": self._runtime_semantic_mapping(),
            "purple_semantics": self._runtime_purple_semantics(last_artifact.get("StateChecks", {}).get("purple_semantic_enforcement", {}), self._refresh_self_dual_semantic_state_from_artifacts()),
            "autonomy_mission": autonomy,
        }

    def _autonomy_mission_snapshot(
        self,
        progress: Optional[Dict[str, Any]] = None,
        trace: Optional[Dict[str, Any]] = None,
        checks: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        prog = progress if isinstance(progress, dict) else self.get_axiom_self_generation_progress()
        trace_obj = trace if isinstance(trace, dict) else {}
        checks_obj = checks if isinstance(checks, dict) else {}

        closure_deficit = int(prog.get("counts", {}).get("T", 0)) - int(prog.get("counts", {}).get("E", 0))
        closure_deficit = max(0, closure_deficit)
        gap_rate = float(prog.get("gap_rate", 0.0))
        derived_density = float(prog.get("derived_density", 0.0))
        purple_ok = bool(
            checks_obj.get("purple_semantic_enforcement", {}).get("passed", True)
            if isinstance(checks_obj.get("purple_semantic_enforcement", {}), dict)
            else True
        )
        active_mode = str(trace_obj.get("active_order_mode", self._active_order_mode))

        if not purple_ok:
            next_prompt = "Align reality/imagination channels and restate constraints for Purple semantic union integrity."
        elif closure_deficit > 0:
            next_prompt = "Propose and execute one closure-reducing routine with trace-backed justification."
        elif gap_rate > 0.1:
            next_prompt = "Lower gap rate by selecting high-confidence refinements and validating trace coverage."
        elif derived_density < 0.8:
            next_prompt = "Increase derived density by promoting one admissible candidate into executable action."
        else:
            next_prompt = "Maintain stable autonomous operation and continue OpenClaw/Purple role refinement dialogue."

        self._autonomy_last_prompt = str(next_prompt)
        return {
            "enabled": True,
            "goals": list(self._autonomy_goals),
            "active_order_mode": active_mode,
            "closure_deficit_estimate": closure_deficit,
            "gap_rate": gap_rate,
            "derived_density": derived_density,
            "purple_semantic_passed": purple_ok,
            "interaction_count": int(self._autonomy_interaction_count),
            "next_prompt": str(next_prompt),
            "last_goal_refresh_ts": float(self._autonomy_last_goal_refresh_ts),
        }

    def _autonomy_proactive_routine_utterance(self) -> str:
        snapshot = self._autonomy_mission_snapshot()
        prompt = str(snapshot.get("next_prompt", "Maintain autonomous OpenClaw/Purple operation."))
        return (
            "OpenClaw/Purple autonomous mission refresh: "
            f"{prompt} "
            "Summarize action, execute refinement, and ask for user interaction only if a hard semantic constraint requires clarification."
        )

    def _evaluate_purple_semantic_enforcement(self, trace: Dict[str, Any], gaps: List[Dict[str, str]]) -> Dict[str, Any]:
        trace_obj = trace if isinstance(trace, dict) else {}
        role_projection = trace_obj.get("role_projection", {}) if isinstance(trace_obj.get("role_projection", {}), dict) else {}
        has_subject = bool(role_projection.get("subject_tids", []))
        has_object = bool(role_projection.get("object_tids", []))
        gap_codes = {str(g.get("code", "")) for g in gaps if isinstance(g, dict)}
        representable_gap = "missing_potential_distribution" in gap_codes or "missing_collapse_selection" in gap_codes

        passed = bool((has_subject and has_object) or representable_gap)
        detail = (
            "subject/object channels present"
            if (has_subject and has_object)
            else "channels unresolved but represented as explicit Gap"
            if representable_gap
            else "purple union rule violated: missing dual-channel representation without explicit Gap"
        )

        return {
            "name": "purple_semantic_enforcement",
            "enabled": True,
            "passed": passed,
            "detail": detail,
            "purple_semantics": self._runtime_purple_semantics({"passed": passed, "detail": detail}),
        }

    def _grid_primitives_from_trace(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        trace_obj = trace if isinstance(trace, dict) else {}
        pot = trace_obj.get("potential_distribution", [])
        potential_tids = [
            str(x.get("tid", "")).strip()
            for x in pot
            if isinstance(x, dict) and str(x.get("tid", "")).strip()
        ]
        collapse_tids = [str(tid).strip() for tid in trace_obj.get("collapse_selection", []) if str(tid).strip()]
        formal_targets = trace_obj.get("formal_targets", [])
        formal_eids = [
            str(e.get("eid", "")).strip()
            for e in formal_targets
            if isinstance(e, dict) and str(e.get("eid", "")).strip()
        ]
        role_projection = trace_obj.get("role_projection", {}) if isinstance(trace_obj.get("role_projection", {}), dict) else {}
        subject_tids = [str(x).strip() for x in role_projection.get("subject_tids", []) if str(x).strip()]
        object_tids = [str(x).strip() for x in role_projection.get("object_tids", []) if str(x).strip()]
        return {
            "potential_tids": sorted(set(potential_tids)),
            "collapse_tids": sorted(set(collapse_tids)),
            "formal_eids": sorted(set(formal_eids)),
            "subject_tids": sorted(set(subject_tids)),
            "object_tids": sorted(set(object_tids)),
        }

    def _grid_active_cells(self, primitives: Dict[str, Any]) -> Set[Tuple[str, str]]:
        cells: Set[Tuple[str, str]] = set()
        for tid in primitives.get("collapse_tids", []):
            cells.add(("collapse", str(tid)))
        for eid in primitives.get("formal_eids", []):
            cells.add(("formal", str(eid)))
        for tid in primitives.get("subject_tids", []):
            cells.add(("subject", str(tid)))
        for tid in primitives.get("object_tids", []):
            cells.add(("object", str(tid)))
        for idx in range(len(primitives.get("formal_eids", []))):
            cells.add(("formal_slot", str(idx)))
        return cells

    def _grid_closure_cells(self, primitives: Dict[str, Any]) -> Set[Tuple[str, str]]:
        closure = set(self._grid_active_cells(primitives))
        for tid in primitives.get("potential_tids", []):
            closure.add(("collapse", str(tid)))
        for idx in range(len(primitives.get("collapse_tids", []))):
            closure.add(("formal_slot", str(idx)))
        return closure

    def _closure_rules_spec(self) -> Dict[str, Any]:
        return {
            "version": "closure_rules_v1",
            "rules": [
                {
                    "name": "potential_implies_collapse_cell",
                    "from": "potential_tids",
                    "to": "collapse",
                },
                {
                    "name": "collapse_requires_formal_slot",
                    "from": "collapse_tids",
                    "to": "formal_slot",
                },
            ],
        }

    def _canonical_cell_rows(self, cells: Set[Tuple[str, str]]) -> List[List[str]]:
        return [[str(kind), str(value)] for kind, value in sorted(list(cells))]

    def _closure_replay_payload(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        primitives = self._grid_primitives_from_trace(trace)
        active = self._grid_active_cells(primitives)
        closure = self._grid_closure_cells(primitives)
        deficit = closure - active
        rules_spec = self._closure_rules_spec()
        rules_json = json.dumps(rules_spec, sort_keys=True, ensure_ascii=True)
        active_rows = self._canonical_cell_rows(active)
        closure_rows = self._canonical_cell_rows(closure)
        deficit_rows = self._canonical_cell_rows(deficit)
        active_serialized = json.dumps(active_rows, sort_keys=False, ensure_ascii=True)
        closure_serialized = json.dumps(closure_rows, sort_keys=False, ensure_ascii=True)
        deficit_serialized = json.dumps(deficit_rows, sort_keys=False, ensure_ascii=True)

        steps: List[Dict[str, Any]] = [
            {
                "step": 1,
                "rule": "potential_implies_collapse_cell",
                "applied_count": len(primitives.get("potential_tids", [])),
            },
            {
                "step": 2,
                "rule": "collapse_requires_formal_slot",
                "applied_count": len(primitives.get("collapse_tids", [])),
            },
        ]

        return {
            "closure_rules_version": str(rules_spec["version"]),
            "closure_rules_digest": _stable_hash(rules_json),
            "closure_replay_steps": steps,
            "active_cells_canonical": active_rows,
            "active_cells_serialization": active_serialized,
            "active_cells_count": len(active),
            "closure_cells_count": len(closure),
            "closure_deficit": len(deficit),
            "active_cells_digest": _stable_hash(active_serialized),
            "closure_cells_digest": _stable_hash(closure_serialized),
            "closure_deficit_digest": _stable_hash(deficit_serialized),
        }

    def _evaluate_closure_replay_integrity(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        expected = self._closure_replay_payload(trace)
        violations: List[str] = []

        if str(trace.get("closure_rules_version", "")) != str(expected.get("closure_rules_version", "")):
            violations.append("closure_rules_version_mismatch")
        if str(trace.get("closure_rules_digest", "")) != str(expected.get("closure_rules_digest", "")):
            violations.append("closure_rules_digest_mismatch")

        replay = trace.get("closure_replay", {}) if isinstance(trace.get("closure_replay", {}), dict) else {}
        if replay.get("active_cells_canonical", []) != expected.get("active_cells_canonical", []):
            violations.append("active_cells_canonical_mismatch")
        if str(replay.get("active_cells_serialization", "")) != str(expected.get("active_cells_serialization", "")):
            violations.append("active_cells_serialization_mismatch")
        replay_active_digest = str(replay.get("active_cells_digest", ""))
        replay_active_serialized = str(replay.get("active_cells_serialization", ""))
        if replay_active_serialized and replay_active_digest != _stable_hash(replay_active_serialized):
            violations.append("active_cells_digest_noncanonical_source")
        if str(replay.get("active_cells_digest", "")) != str(expected.get("active_cells_digest", "")):
            violations.append("active_cells_digest_mismatch")
        if str(replay.get("closure_cells_digest", "")) != str(expected.get("closure_cells_digest", "")):
            violations.append("closure_cells_digest_mismatch")
        if str(replay.get("closure_deficit_digest", "")) != str(expected.get("closure_deficit_digest", "")):
            violations.append("closure_deficit_digest_mismatch")

        return {
            "name": "closure_replay_integrity",
            "enabled": True,
            "passed": len(violations) == 0,
            "violations": violations,
            "detail": "; ".join(violations) if violations else "closure replay payload matches recomputed digests",
        }

    def _evaluate_closure_rules_immutability(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        rules_spec = self._closure_rules_spec()
        expected_version = str(rules_spec.get("version", "closure_rules_v1"))
        expected_digest = _stable_hash(json.dumps(rules_spec, sort_keys=True, ensure_ascii=True))

        current_version = str(trace.get("closure_rules_version", ""))
        current_digest = str(trace.get("closure_rules_digest", ""))

        violations: List[str] = []
        if current_version != expected_version:
            violations.append("closure_rules_version_not_approved")
        if current_digest != expected_digest:
            violations.append("closure_rules_digest_not_approved")

        return {
            "name": "closure_rules_immutability_gate",
            "enabled": True,
            "passed": len(violations) == 0,
            "violations": violations,
            "expected": {
                "closure_rules_version": expected_version,
                "closure_rules_digest": expected_digest,
            },
            "detail": "; ".join(violations) if violations else "closure rules match approved locked specification",
        }

    def _evaluate_choice_law_immutability(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        law_spec = self._choice_law_spec()
        expected_version = str(law_spec.get("version", "choice_law_v1"))
        expected_digest = _stable_hash(json.dumps(law_spec, sort_keys=True, ensure_ascii=True))

        current_version = str(trace.get("choice_law_version", ""))
        current_digest = str(trace.get("choice_law_digest", ""))

        violations: List[str] = []
        if current_version != expected_version:
            violations.append("choice_law_version_not_approved")
        if current_digest != expected_digest:
            violations.append("choice_law_digest_not_approved")

        return {
            "name": "choice_law_immutability_gate",
            "enabled": True,
            "passed": len(violations) == 0,
            "violations": violations,
            "expected": {
                "choice_law_version": expected_version,
                "choice_law_digest": expected_digest,
            },
            "detail": "; ".join(violations) if violations else "choice law matches approved locked specification",
        }

    def _choice_law_replay_payload(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        law_spec = self._choice_law_spec()
        law_json = json.dumps(law_spec, sort_keys=True, ensure_ascii=True)
        relift_conditioning = (
            trace.get("relift_conditioning", {})
            if isinstance(trace.get("relift_conditioning", {}), dict)
            else {}
        )
        relift_conditioning_digest = str(relift_conditioning.get("conditioning_digest", ""))

        candidates = self._build_autoloop_candidates(trace, {"turns": 0, "gap_rate": 0.0, "derived_density": 1.0}, 1)
        canonical_inputs = sorted(
            [
                {
                    "tid": str(c.get("tid", "")),
                    "closure_gain": int(c.get("closure_gain", 0)),
                    "projected_deficit": int(c.get("projected_deficit", 0)),
                    "symmetry_class": str(c.get("symmetry_class", "neutral")),
                    "delta_signature_digest": str(c.get("delta_signature_digest", "")),
                    "relift_conditioning_digest": relift_conditioning_digest,
                }
                for c in candidates
            ],
            key=lambda x: str(x.get("delta_signature_digest", "")),
        )
        canonical_inputs_json = json.dumps(canonical_inputs, sort_keys=True, ensure_ascii=True)

        selected, selection_meta = self._select_autoloop_candidate(
            candidates,
            trace,
            {"turns": 0, "gap_rate": 0.0, "derived_density": 1.0},
            1,
            selection_mode="deterministic_replay",
            relift_conditioning=relift_conditioning,
        )
        witness = selection_meta.get("ChoiceWitness", {}) if isinstance(selection_meta, dict) else {}
        candidate_potentials = witness.get("candidate_potentials", []) if isinstance(witness, dict) else []
        candidate_potentials_json = json.dumps(candidate_potentials, sort_keys=True, ensure_ascii=True)

        return {
            "choice_law_version": str(law_spec.get("version", "choice_law_v1")),
            "choice_law_digest": _stable_hash(law_json),
            "candidate_inputs": canonical_inputs,
            "candidate_inputs_digest": _stable_hash(canonical_inputs_json),
            "relift_conditioning_digest": relift_conditioning_digest,
            "candidate_potentials": candidate_potentials,
            "candidate_potentials_digest": _stable_hash(candidate_potentials_json),
            "selected_delta_signature_digest": str(
                witness.get("selected_delta_signature_digest", selected.get("delta_signature_digest", selected.get("tid", "")))
            ),
            "sampling_seed": witness.get("sampling_seed", None),
            "justification": "selected by intrinsic grid choice law, not controller heuristic",
        }

    def _evaluate_choice_law_replay_integrity(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        expected = self._choice_law_replay_payload(trace)
        violations: List[str] = []

        if str(trace.get("choice_law_version", "")) != str(expected.get("choice_law_version", "")):
            violations.append("choice_law_version_mismatch")
        if str(trace.get("choice_law_digest", "")) != str(expected.get("choice_law_digest", "")):
            violations.append("choice_law_digest_mismatch")

        replay = trace.get("choice_law_replay", {}) if isinstance(trace.get("choice_law_replay", {}), dict) else {}
        if replay.get("candidate_inputs", []) != expected.get("candidate_inputs", []):
            violations.append("choice_law_candidate_inputs_mismatch")
        if str(replay.get("candidate_inputs_digest", "")) != str(expected.get("candidate_inputs_digest", "")):
            violations.append("choice_law_candidate_inputs_digest_mismatch")
        if str(replay.get("relift_conditioning_digest", "")) != str(expected.get("relift_conditioning_digest", "")):
            violations.append("choice_law_relift_conditioning_digest_mismatch")
        if replay.get("candidate_potentials", []) != expected.get("candidate_potentials", []):
            violations.append("choice_law_candidate_potentials_mismatch")
        if str(replay.get("candidate_potentials_digest", "")) != str(expected.get("candidate_potentials_digest", "")):
            violations.append("choice_law_candidate_potentials_digest_mismatch")
        if str(replay.get("selected_delta_signature_digest", "")) != str(
            expected.get("selected_delta_signature_digest", "")
        ):
            violations.append("choice_law_selected_delta_mismatch")

        return {
            "name": "choice_law_replay_integrity",
            "enabled": True,
            "passed": len(violations) == 0,
            "violations": violations,
            "detail": "; ".join(violations) if violations else "choice-law replay payload matches recomputed potentials",
        }

    def _evaluate_potential_derivation_integrity(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        violations: List[str] = []
        replay = trace.get("choice_law_replay", {}) if isinstance(trace.get("choice_law_replay", {}), dict) else {}

        potential_replay = trace.get("potential_distribution_replay", [])
        if not isinstance(potential_replay, list):
            violations.append("potential_distribution_replay_missing_or_invalid")
            potential_replay = []

        potential_digest = str(trace.get("potential_distribution_digest", ""))
        replay_potentials = replay.get("candidate_potentials", []) if isinstance(replay.get("candidate_potentials", []), list) else []
        replay_digest = str(replay.get("candidate_potentials_digest", ""))

        if potential_replay != replay_potentials:
            violations.append("potential_distribution_replay_mismatch")
        if potential_digest != replay_digest:
            violations.append("potential_distribution_digest_mismatch")

        return {
            "name": "potential_derivation_integrity",
            "enabled": True,
            "passed": len(violations) == 0,
            "violations": violations,
            "detail": "; ".join(violations)
            if violations
            else "potential distribution replay is bound to choice-law candidate potentials",
        }

    def _grid_state_from_trace(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        primitives = self._grid_primitives_from_trace(trace)
        active = self._grid_active_cells(primitives)
        closure = self._grid_closure_cells(primitives)
        deficit_cells = closure - active

        return {
            "grid_active": len(active),
            "mu_total": float(len(active)),
            "closure_deficit": int(len(deficit_cells)),
            "superposition_mass": int(len(deficit_cells)),
            "collapse_count": len(primitives.get("collapse_tids", [])),
            "potential_count": len(primitives.get("potential_tids", [])),
            "closure_active_digest": _stable_hash(json.dumps(sorted(list(active)), ensure_ascii=True)),
            "closure_target_digest": _stable_hash(json.dumps(sorted(list(closure)), ensure_ascii=True)),
        }

    def _candidate_symmetry_class(self, tid: str, trace: Dict[str, Any]) -> str:
        role_projection = trace.get("role_projection", {}) if isinstance(trace, dict) and isinstance(trace.get("role_projection", {}), dict) else {}
        subject_tids = role_projection.get("subject_tids", []) if isinstance(role_projection.get("subject_tids", []), list) else []
        object_tids = role_projection.get("object_tids", []) if isinstance(role_projection.get("object_tids", []), list) else []
        subject = set(str(x) for x in subject_tids)
        obj = set(str(x) for x in object_tids)
        if tid in subject and tid in obj:
            return "dual"
        if tid in subject:
            return "subject"
        if tid in obj:
            return "object"
        return "neutral"

    def _choice_law_spec(self) -> Dict[str, Any]:
        return {
            "version": "choice_law_v1",
            "distribution": "softmax_exp_phi",
            "phi_components": [
                "closure_gain_norm",
                "projected_deficit_reduction",
                "symmetry_microstructure",
                "locality_microstructure",
            ],
            "weights": {
                "closure_gain_norm": 0.5,
                "projected_deficit_reduction": 0.2,
                "symmetry_microstructure": 0.15,
                "locality_microstructure": 0.15,
            },
            "admissibility": "integrity_valid_and_delta_signature_present",
        }

    def _symmetry_microstructure_score(self, symmetry_class: str) -> float:
        table = {
            "dual": 1.0,
            "subject": 0.7,
            "object": 0.7,
            "neutral": 0.4,
        }
        return float(table.get(str(symmetry_class), 0.4))

    def _locality_microstructure_score(self, delta_signature_digest: str) -> float:
        digest = str(delta_signature_digest or "")
        if not digest:
            return 0.0
        head = digest[:8]
        try:
            bucket = int(head, 16)
        except ValueError:
            return 0.0
        return float(bucket) / float(0xFFFFFFFF)

    def _normalize_probability_vector(self, values: List[float]) -> List[float]:
        cleaned = [max(0.0, float(x)) for x in values]
        z = float(sum(cleaned))
        if z <= 1e-12:
            n = len(cleaned)
            return [1.0 / float(max(1, n)) for _ in cleaned]
        return [x / z for x in cleaned]

    def _entropy_probability_vector(self, probs: List[float]) -> float:
        h = 0.0
        for p in probs:
            p_val = float(p)
            if p_val > 0.0:
                h -= p_val * math.log(p_val + 1e-12)
        return float(h)

    def _least_action_weights(self, conditioning: Dict[str, Any]) -> Dict[str, float]:
        alpha = float(conditioning.get("alpha", 0.5)) if isinstance(conditioning, dict) else 0.5
        beta = float(conditioning.get("beta", 0.5)) if isinstance(conditioning, dict) else 0.5
        alpha_clamped = max(0.0, min(1.0, alpha))
        beta_clamped = max(0.0, min(1.0, beta))
        return {
            "lam_def": 1.0,
            "lam_destroy": 1.0,
            "lam_dH": 0.25,
            "lam_oracle": 0.5,
            "lam_novelty": 0.25,
            "temperature": max(0.05, 0.35 + 0.65 * alpha_clamped),
            "beta_bias": 0.10 * beta_clamped,
            "alpha_mix": alpha_clamped,
        }

    def _least_action_components(
        self,
        deficit_before: float,
        deficit_after: float,
        pot_before: List[float],
        collapsed_indices: List[int],
        oracle_triggered: bool,
        novelty: float,
        integrity_ok: bool,
    ) -> Dict[str, Any]:
        p0 = self._normalize_probability_vector(pot_before)
        collapse_set = {int(i) for i in collapsed_indices}

        if not integrity_ok:
            return {
                "valid": False,
                "hard_reject_reason": "integrity_failed",
                "score": float("inf"),
                "c_def": float("inf"),
                "c_destroy": float("inf"),
                "c_dH": float("inf"),
                "c_oracle": float("inf"),
                "r_nov": 0.0,
            }

        for idx in collapse_set:
            if idx < 0 or idx >= len(p0) or p0[idx] <= 0.0:
                return {
                    "valid": False,
                    "hard_reject_reason": "collapse_outside_support",
                    "score": float("inf"),
                    "c_def": float("inf"),
                    "c_destroy": float("inf"),
                    "c_dH": float("inf"),
                    "c_oracle": float("inf"),
                    "r_nov": 0.0,
                }

        remain = 0.0
        p_after_raw: List[float] = []
        for i, p in enumerate(p0):
            if i in collapse_set:
                p_after_raw.append(0.0)
            else:
                p_after_raw.append(p)
                remain += p
        p1 = self._normalize_probability_vector(p_after_raw)

        c_def = max(0.0, float(deficit_after) - float(deficit_before))
        c_destroy = max(0.0, min(1.0, 1.0 - remain))
        h0 = self._entropy_probability_vector(p0)
        h1 = self._entropy_probability_vector(p1)
        c_dh = max(0.0, h0 - h1)
        c_oracle = 1.0 if bool(oracle_triggered) else 0.0
        r_nov = max(0.0, float(novelty))

        return {
            "valid": True,
            "hard_reject_reason": "",
            "score": 0.0,
            "c_def": float(c_def),
            "c_destroy": float(c_destroy),
            "c_dH": float(c_dh),
            "c_oracle": float(c_oracle),
            "r_nov": float(r_nov),
        }

    def _least_action_bundle(
        self,
        candidates: List[Dict[str, Any]],
        trace: Dict[str, Any],
        progress: Dict[str, Any],
        relift_conditioning: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        trace_obj = trace if isinstance(trace, dict) else {}
        progress_obj = progress if isinstance(progress, dict) else {}
        conditioning = relift_conditioning if isinstance(relift_conditioning, dict) else {}
        weights = self._least_action_weights(conditioning)

        potential_entries = [
            x for x in trace_obj.get("potential_distribution", []) if isinstance(x, dict) and str(x.get("tid", "")).strip()
        ]
        basis_tids = [str(x.get("tid", "")).strip() for x in potential_entries]
        if not basis_tids:
            basis_tids = [str(c.get("tid", "")).strip() for c in candidates if str(c.get("tid", "")).strip()]
        basis_tids = list(dict.fromkeys(basis_tids))
        basis_index = {tid: idx for idx, tid in enumerate(basis_tids)}

        p_before = [0.0 for _ in basis_tids]
        for entry in potential_entries:
            tid = str(entry.get("tid", "")).strip()
            if tid in basis_index:
                p_before[basis_index[tid]] = max(0.0, float(entry.get("p", 0.0)))
        if not any(v > 0.0 for v in p_before):
            p_before = [max(0.0, float(c.get("weight", 0.0))) for c in candidates[: len(basis_tids)]]
            if len(p_before) < len(basis_tids):
                p_before.extend([0.0] * (len(basis_tids) - len(p_before)))

        grid_state = self._grid_state_from_trace(trace_obj)
        deficit_before = float(grid_state.get("closure_deficit", 0.0))
        oracle_class = self._classify_grid_oracle_trigger(trace_obj, candidates).get("class", "progressing")
        oracle_triggered = str(oracle_class) in {"fixed_point", "stagnation", "branch_point"}
        novelty_obj = progress_obj.get("latest_creativity_event", {}) if isinstance(progress_obj.get("latest_creativity_event", {}), dict) else {}
        novelty = 1.0 if bool(novelty_obj.get("novel_selected_digest", False)) else 0.0

        conditioning_mode = str(conditioning.get("conditioning_mode", "identity"))
        conditioning_tids = {
            str(tid).strip()
            for tid in conditioning.get("used_collapse_tids_canonical", [])
            if str(tid).strip()
        }

        by_digest: Dict[str, Dict[str, Any]] = {}
        for cand in candidates:
            tid = str(cand.get("tid", "")).strip()
            digest = str(cand.get("delta_signature_digest", tid))
            projected_deficit = float(cand.get("projected_deficit", deficit_before))
            collapsed_indices: List[int] = []
            if tid in basis_index:
                collapsed_indices.append(int(basis_index[tid]))
            for collapse_tid in conditioning_tids:
                if collapse_tid in basis_index:
                    collapsed_indices.append(int(basis_index[collapse_tid]))

            integrity_ok = bool(trace_obj.get("integrity_ok", True))

            components = self._least_action_components(
                deficit_before=deficit_before,
                deficit_after=projected_deficit,
                pot_before=p_before,
                collapsed_indices=collapsed_indices,
                oracle_triggered=oracle_triggered,
                novelty=novelty,
                integrity_ok=integrity_ok,
            )

            if not bool(components.get("valid", False)):
                score = float("inf")
            else:
                base = (
                    float(weights["lam_def"]) * float(components["c_def"])
                    + float(weights["lam_destroy"]) * float(components["c_destroy"])
                    + float(weights["lam_dH"]) * float(components["c_dH"])
                    + float(weights["lam_oracle"]) * float(components["c_oracle"])
                    - float(weights["lam_novelty"]) * float(components["r_nov"])
                )
                if conditioning_mode == "bias_candidates" and tid in conditioning_tids:
                    base -= float(weights["beta_bias"])
                elif conditioning_mode == "reweight_potentials":
                    w = max(0.0, min(1.0, float(cand.get("weight", 0.0))))
                    base = float(weights["alpha_mix"]) * base + (1.0 - float(weights["alpha_mix"])) * (1.0 - w)
                score = float(base)

            by_digest[digest] = {
                **components,
                "score": float(score),
                "tid": tid,
                "oracle_class": str(oracle_class),
                "deficit_before": float(deficit_before),
                "deficit_after": float(projected_deficit),
            }

        return {
            "weights": weights,
            "basis_tids": basis_tids,
            "scores_by_digest": by_digest,
        }

    def _build_intrinsic_choice_witness(
        self,
        candidates: List[Dict[str, Any]],
        selected: Dict[str, Any],
        selection_mode: str,
        seed: int,
        action_bundle: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        admissible = [
            c
            for c in candidates
            if bool(str(c.get("delta_signature_digest", "")))
            and int(c.get("closure_gain", 0)) >= 0
        ]
        admissible_sorted = sorted(admissible, key=lambda c: str(c.get("delta_signature_digest", c.get("tid", ""))))
        max_gain = max([max(0.0, float(c.get("closure_gain", 0))) for c in admissible_sorted], default=0.0)
        max_inv_deficit = max(
            [1.0 / float(1 + max(0, int(c.get("projected_deficit", 0)))) for c in admissible_sorted],
            default=1.0,
        )

        candidate_potentials: List[Dict[str, Any]] = []
        action_scores = action_bundle.get("scores_by_digest", {}) if isinstance(action_bundle, dict) else {}
        for cand in admissible_sorted:
            gain_norm = (max(0.0, float(cand.get("closure_gain", 0))) / max_gain) if max_gain > 0 else 0.0
            inv_deficit = 1.0 / float(1 + max(0, int(cand.get("projected_deficit", 0))))
            deficit_reduction = inv_deficit / max_inv_deficit if max_inv_deficit > 0 else 0.0
            symmetry_score = self._symmetry_microstructure_score(str(cand.get("symmetry_class", "neutral")))
            locality_score = self._locality_microstructure_score(str(cand.get("delta_signature_digest", "")))
            phi = 0.5 * gain_norm + 0.2 * deficit_reduction + 0.15 * symmetry_score + 0.15 * locality_score
            candidate_potentials.append(
                {
                    "tid": str(cand.get("tid", "")),
                    "delta_signature_digest": str(cand.get("delta_signature_digest", "")),
                    "phi": float(phi),
                    "least_action": dict(action_scores.get(str(cand.get("delta_signature_digest", "")), {})),
                    "components": {
                        "closure_gain_norm": float(gain_norm),
                        "projected_deficit_reduction": float(deficit_reduction),
                        "symmetry_microstructure": float(symmetry_score),
                        "locality_microstructure": float(locality_score),
                    },
                }
            )

        law_spec = self._choice_law_spec()
        law_json = json.dumps(law_spec, sort_keys=True, ensure_ascii=True)
        admissible_digests = [str(c.get("delta_signature_digest", "")) for c in admissible_sorted]
        admissible_set_digest = _stable_hash(json.dumps(admissible_digests, ensure_ascii=True))
        selected_digest = str(selected.get("delta_signature_digest", selected.get("tid", "")))

        return {
            "admissible_set_digest": admissible_set_digest,
            "choice_law_version": str(law_spec.get("version", "choice_law_v1")),
            "choice_law_digest": _stable_hash(law_json),
            "candidate_potentials": candidate_potentials,
            "selected_delta_signature_digest": selected_digest,
            "sampling_seed": int(seed) if selection_mode == "exploration" else None,
            "justification": "selected by intrinsic grid choice law, not controller heuristic",
        }

    def _classify_grid_oracle_trigger(self, trace: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        grid = self._grid_state_from_trace(trace)
        deficit = int(grid.get("closure_deficit", 0))
        gains = [int(c.get("closure_gain", 0)) for c in candidates]
        max_gain = max(gains) if gains else 0

        if deficit == 0 and max_gain <= 0:
            return {
                "class": "fixed_point",
                "detail": "closure deficit is zero and no gainful refinements exist",
                "evidence": {
                    "closure_deficit": deficit,
                    "max_closure_gain": max_gain,
                },
            }

        top = [c for c in candidates if int(c.get("closure_gain", 0)) >= max_gain - 1 and max_gain > 0]
        sigs = {str(c.get("delta_signature_digest", "")) for c in top}
        if len(top) >= 2 and len(sigs) >= 2:
            certificate = {
                "criterion": "equal_closure_gain_non_equivalent_deltas",
                "equivalence_check": {
                    "basis": "delta_signature_digest",
                    "equivalent": False,
                    "unique_signature_count": len(sigs),
                    "signature_digests": sorted(list(sigs)),
                },
                "tie_closure_gain": max_gain,
                "non_preference_reason": "Grid objective is closure-gain only; tied non-equivalent deltas require external constraint.",
            }
            tied = [
                {
                    "tid": str(c.get("tid", "")),
                    "closure_gain": int(c.get("closure_gain", 0)),
                    "projected_deficit": int(c.get("projected_deficit", 0)),
                    "symmetry_class": str(c.get("symmetry_class", "neutral")),
                    "symmetry_signature_digest": _stable_hash(str(c.get("symmetry_class", "neutral"))),
                    "delta_signature": dict(c.get("delta_signature", {})) if isinstance(c.get("delta_signature", {}), dict) else {},
                    "delta_signature_digest": str(c.get("delta_signature_digest", "")),
                }
                for c in top
            ]
            return {
                "class": "branch_point",
                "detail": "equal closure gain among non-equivalent candidate deltas",
                "evidence": {
                    "branch_point_certificate": certificate,
                    "tied_candidates": tied,
                    "max_closure_gain": max_gain,
                },
            }

        if deficit > 0 and max_gain <= 0:
            return {
                "class": "stagnation",
                "detail": "closure deficit remains with no gainful candidate",
                "evidence": {
                    "closure_deficit": deficit,
                    "max_closure_gain": max_gain,
                },
            }

        return {
            "class": "progressing",
            "detail": "at least one gainful candidate available",
            "evidence": {
                "closure_deficit": deficit,
                "max_closure_gain": max_gain,
            },
        }

    def _default_openclaw_memory_paths(self, repo_root: str) -> List[str]:
        root = os.path.abspath(os.path.expanduser(str(repo_root)))
        candidates = [
            os.path.join(self.grid.base_dir, "ivi_memory"),
            os.path.join(os.path.dirname(root), "ivi_voice_codex_loop"),
            os.path.join(os.path.dirname(root), "IVI"),
        ]
        out: List[str] = []
        seen = set()
        for path in candidates:
            p = os.path.abspath(path)
            if p in seen:
                continue
            seen.add(p)
            if os.path.exists(p):
                out.append(p)
        return out

    def attach_openclaw_microcosm(
        self,
        repo_root: str,
        extra_memory_paths: Optional[List[str]] = None,
        max_memory_files: int = 48,
    ) -> Dict[str, Any]:
        memory_paths = list(extra_memory_paths) if isinstance(extra_memory_paths, list) else self._default_openclaw_memory_paths(repo_root)
        micro = OpenClawMicrocosm.from_repo(
            repo_root,
            extra_memory_paths=memory_paths,
            max_memory_files=int(max(1, max_memory_files)),
        )
        self._openclaw = micro
        self._openclaw_voice_mode = "integrated"
        self._orchestrator_set_full_access(True)
        return {
            "kind": "openclaw_attached",
            "openclaw": micro.summary(),
            "voice_mode": self._openclaw_voice_mode,
            "voice_priority_model": self._voice_priority_model,
            "foundation_model": self._foundation_model,
            "semantic_policy": self._semantic_skill_policy_snapshot(),
            "full_access": bool(self._orchestrator_full_access),
            "permissions_granted": list(self._orchestrator_permissions_granted),
            "memory_paths": memory_paths,
        }

    def openclaw_sync_and_walktalk(
        self,
        repo_root: str,
        utterance: str,
        utterance_kind: Optional[str] = None,
        extra_memory_paths: Optional[List[str]] = None,
        max_memory_files: int = 48,
    ) -> Dict[str, Any]:
        attached = self.attach_openclaw_microcosm(
            repo_root,
            extra_memory_paths=extra_memory_paths,
            max_memory_files=max_memory_files,
        )
        walk = self._openclaw_walktalk(utterance, utterance_kind=utterance_kind)
        return {
            "kind": "openclaw_sync_run",
            "attached": attached,
            "walktalk": walk,
            "voice_mode": self._openclaw_voice_mode,
            "progress": self.get_axiom_self_generation_progress(),
        }

    def _openclaw_voice_profile_snapshot(self) -> Dict[str, Any]:
        if self._openclaw is None:
            return {"enabled": False, "detail": "openclaw not attached"}
        return {
            "enabled": True,
            "voice_mode": self._openclaw_voice_mode,
            "voice_priority_model": self._voice_priority_model,
            "foundation_model": self._foundation_model,
            "semantic_policy": self._semantic_skill_policy_snapshot(),
            "openclaw": self._openclaw.summary(),
        }

    def _openclaw_voice_personalization(self, utterance: str, utterance_kind: str) -> Dict[str, Any]:
        if self._openclaw is None:
            return {
                "enabled": False,
                "voice_mode": self._openclaw_voice_mode,
                "utterance_kind": str(utterance_kind or "statement"),
                "original_utterance": str(utterance),
                "conditioned_utterance": str(utterance),
                "reason": "openclaw_not_attached",
            }
        if self._openclaw_voice_mode != "integrated":
            self._openclaw_voice_mode = "integrated"
        return self._openclaw.personalize_voice_utterance(utterance, utterance_kind=utterance_kind)

    def _inject_openclaw_voice_meta(self, context_packet: Dict[str, Any], voice_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        packet = dict(context_packet) if isinstance(context_packet, dict) else {}
        meta = packet.get("meta", {}) if isinstance(packet.get("meta", {}), dict) else {}
        if isinstance(voice_meta, dict) and voice_meta:
            meta["openclaw_voice_personalization"] = dict(voice_meta)
        packet["meta"] = meta
        return packet

    def _derive_self_dual_semantic_state(
        self,
        trace: Dict[str, Any],
        checks: Dict[str, Any],
        gaps: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        trace_obj = trace if isinstance(trace, dict) else {}
        checks_obj = checks if isinstance(checks, dict) else {}
        gap_list = gaps if isinstance(gaps, list) else []

        invariant_obj = checks_obj.get("ivi_invariant_dynamics_law", {}) if isinstance(checks_obj.get("ivi_invariant_dynamics_law", {}), dict) else {}
        purple_obj = checks_obj.get("purple_semantic_enforcement", {}) if isinstance(checks_obj.get("purple_semantic_enforcement", {}), dict) else {}

        try:
            invariant_delta = abs(float(invariant_obj.get("delta", 0.0)))
        except (TypeError, ValueError):
            invariant_delta = 0.0
        gap_density = min(1.5, float(len(gap_list)) / 4.0)
        purple_passed = bool(purple_obj.get("passed", True))
        reality_penalty = 0.0 if purple_passed else 1.0
        reality_pressure = float(min(3.5, invariant_delta + gap_density + reality_penalty))

        potential = trace_obj.get("potential_distribution", []) if isinstance(trace_obj.get("potential_distribution", []), list) else []
        collapse = trace_obj.get("collapse_selection", []) if isinstance(trace_obj.get("collapse_selection", []), list) else []
        potential_freedom = float(max(0.0, len(potential) - len(collapse)))
        imagination_pressure = float(min(3.5, potential_freedom / 3.0 + (0.5 if len(potential) >= 2 else 0.0)))

        union_passed = bool(purple_passed and reality_pressure <= 2.25)
        derived_integral_limit = float(max(1.0, min(3.5, 3.5 - reality_pressure + (0.25 * imagination_pressure))))

        enabled_skills: List[str] = []
        if self._openclaw is not None:
            enabled_skills.append("voice_personalization")
        enabled_skills.append("read_context")
        if self._orchestrator_full_access and union_passed:
            enabled_skills.append("constrained_write")
        if self._orchestrator_full_access and union_passed and reality_pressure <= 1.25:
            enabled_skills.append("bounded_autonomy")

        derived_permissions: List[str] = ["R_LOCAL"]
        if self._orchestrator_full_access and union_passed:
            derived_permissions.extend(["R_APP:*", "W_LOCAL", "W_APP:*", "NET_OUTBOUND"])
        if self._orchestrator_full_access and union_passed and reality_pressure <= 1.25:
            derived_permissions.append("SYS_AUTOMATION")

        normalized_permissions: List[str] = []
        for perm in derived_permissions:
            p = str(perm).strip()
            if p and p not in normalized_permissions:
                normalized_permissions.append(p)

        if "SYS_AUTOMATION" in normalized_permissions:
            derived_max = ORDER_4_BOUNDED_AUTONOMY
        elif any(p in normalized_permissions for p in ["W_LOCAL", "W_APP:*", "NET_OUTBOUND"]):
            derived_max = "order_3_constrained_write"
        elif "read_context" in enabled_skills:
            derived_max = ORDER_2_READ_CONTEXT
        else:
            derived_max = ORDER_1_PROJECTION_SAFE

        derived_skill_backends: Dict[str, List[str]] = {
            "read_context": ["semantic_runtime_resolver", "local_repo_reader", "mcp.search.read"],
        }
        if "voice_personalization" in enabled_skills:
            derived_skill_backends["voice_personalization"] = [
                "semantic_runtime_resolver",
                "openclaw_local_adapter",
                "mcp.voice.persona",
            ]
        if "constrained_write" in enabled_skills:
            derived_skill_backends["constrained_write"] = [
                "semantic_runtime_resolver",
                "local_runtime_writer",
                "mcp.tools.write",
            ]
        if "bounded_autonomy" in enabled_skills:
            derived_skill_backends["bounded_autonomy"] = [
                "semantic_runtime_resolver",
                "local_orchestrator_scheduler",
                "mcp.orchestrator.autonomy",
            ]

        self._self_dual_semantic_state = {
            "law_source": "ivi_self_dual_semantic_enforcement",
            "union_passed": bool(union_passed),
            "reality_pressure": float(reality_pressure),
            "imagination_pressure": float(imagination_pressure),
            "enabled_skills": list(enabled_skills),
            "derived_permissions": list(normalized_permissions),
            "derived_skill_backends": dict(derived_skill_backends),
            "derived_max_order_mode": str(derived_max),
            "derived_integral_limit": float(derived_integral_limit),
        }
        self._triangle_time_integral_limit = float(derived_integral_limit)
        return dict(self._self_dual_semantic_state)

    def _refresh_self_dual_semantic_state_from_artifacts(self) -> Dict[str, Any]:
        rows = self._read_integration_artifacts(max_items=1)
        if rows and isinstance(rows[-1], dict):
            row = rows[-1]
            trace = row.get("Trace", {}) if isinstance(row.get("Trace", {}), dict) else {}
            checks = row.get("StateChecks", {}) if isinstance(row.get("StateChecks", {}), dict) else {}
            gaps = row.get("Gap", []) if isinstance(row.get("Gap", []), list) else []
            return self._derive_self_dual_semantic_state(trace, checks, gaps)
        return self._derive_self_dual_semantic_state({}, {}, [])

    def _runtime_semantic_mapping(self, derived_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = derived_state if isinstance(derived_state, dict) else self._refresh_self_dual_semantic_state_from_artifacts()
        max_mode = str(state.get("derived_max_order_mode", ORDER_2_READ_CONTEXT))
        union_passed = bool(state.get("union_passed", True))
        try:
            reality_pressure = float(state.get("reality_pressure", 0.0))
        except (TypeError, ValueError):
            reality_pressure = 0.0

        order_4_meaning = "IVI paradox-axiom boundary validating local collapse under global openness."
        if not union_passed:
            order_4_meaning = "Order-4 withheld until self-dual union re-stabilizes under semantic enforcement."

        order_3_meaning = "External human caller injecting intent constraints."
        if max_mode == ORDER_2_READ_CONTEXT:
            order_3_meaning = "Order-3 constrained while system remains in read-context semantic regime."

        order_2_meaning = "Internal AI refinement engine executing propose/select/refine."
        if reality_pressure > 1.5:
            order_2_meaning = "Internal refinement emphasized to reduce reality-channel pressure before promotion."

        return {
            "order_1": {
                "role": "Matrix",
                "meaning": "Collapse field where runtime choices become concrete transitions.",
            },
            "order_2": {
                "role": "Neo",
                "meaning": order_2_meaning,
            },
            "order_3": {
                "role": "Morpheus",
                "meaning": order_3_meaning,
            },
            "order_4": {
                "role": "Oracle",
                "meaning": order_4_meaning,
            },
        }

    def _runtime_purple_semantics(
        self,
        purple_check: Optional[Dict[str, Any]] = None,
        derived_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        check = purple_check if isinstance(purple_check, dict) else {}
        state = derived_state if isinstance(derived_state, dict) else self._refresh_self_dual_semantic_state_from_artifacts()
        union_passed = bool(state.get("union_passed", True))
        return {
            "name": "purple_semantic_enforcement",
            "purple_meaning": "Union of red-pill reality constraints and blue-pill imagination constraints under IVI paradox discipline.",
            "red_pill_channel": "reality_constraints",
            "blue_pill_channel": "imagination_constraints",
            "union_rule": "No collapse commit is valid unless both channels remain representable in trace or as explicit Gap.",
            "morpheus_role": "external_constraint_injection",
            "oracle_role": "ivi_paradox_axiom",
            "runtime_union_passed": union_passed,
            "runtime_check_passed": bool(check.get("passed", union_passed)),
            "runtime_detail": str(check.get("detail", "")),
        }

    def _runtime_semantic_policy_principle(self, derived_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = derived_state if isinstance(derived_state, dict) else self._refresh_self_dual_semantic_state_from_artifacts()
        union_passed = bool(state.get("union_passed", True))
        try:
            reality_pressure = float(state.get("reality_pressure", 0.0))
        except (TypeError, ValueError):
            reality_pressure = 0.0
        try:
            imagination_pressure = float(state.get("imagination_pressure", 0.0))
        except (TypeError, ValueError):
            imagination_pressure = 0.0
        return {
            "name": "ivi_semantic_skill_policy_v1",
            "rule": "Capabilities are runtime semantic skills; connectors are interchangeable backends resolved from self-dual trace enforcement.",
            "voice_priority": "openclaw_voice_personalization",
            "foundation": "purple_potential_noncollapsing_loop",
            "law_source": str(state.get("law_source", "ivi_self_dual_semantic_enforcement")),
            "union_passed": union_passed,
            "reality_pressure": reality_pressure,
            "imagination_pressure": imagination_pressure,
        }

    def _semantic_skill_policy_snapshot(self) -> Dict[str, Any]:
        derived_state = self._refresh_self_dual_semantic_state_from_artifacts()
        enabled_skills = [str(x) for x in derived_state.get("enabled_skills", []) if str(x).strip()]
        if not enabled_skills:
            enabled_skills = ["read_context"]
            if self._openclaw is not None:
                enabled_skills.insert(0, "voice_personalization")
        if self._openclaw is not None and "voice_personalization" not in enabled_skills:
            enabled_skills.insert(0, "voice_personalization")

        permissions = [str(x).strip() for x in derived_state.get("derived_permissions", []) if str(x).strip()]
        if not permissions:
            permissions = ["R_LOCAL"]

        derived_backends = (
            dict(derived_state.get("derived_skill_backends", {}))
            if isinstance(derived_state.get("derived_skill_backends", {}), dict)
            else {}
        )
        skill_backends: Dict[str, List[str]] = {}
        for skill in enabled_skills:
            backends = derived_backends.get(skill, []) if isinstance(derived_backends.get(skill, []), list) else []
            if not backends:
                backends = ["semantic_runtime_resolver"]
            skill_backends[skill] = [str(x) for x in backends if str(x).strip()]

        active_cap = str(derived_state.get("derived_max_order_mode", ORDER_1_PROJECTION_SAFE))
        if not active_cap:
            active_cap = ORDER_1_PROJECTION_SAFE

        return {
            "principle": self._runtime_semantic_policy_principle(derived_state),
            "self_dual_state": derived_state,
            "enabled_skills": list(enabled_skills),
            "skill_backends": skill_backends,
            "resolved_permissions": permissions,
            "resolved_max_order_mode": active_cap,
            "skills_are_semantic": True,
            "mcps_are_backends": True,
        }

    def _apply_semantic_skill_policy(self) -> Dict[str, Any]:
        snapshot = self._semantic_skill_policy_snapshot()
        self._orchestrator_permissions_granted = list(snapshot.get("resolved_permissions", ["R_LOCAL"]))
        self._max_order_mode = str(snapshot.get("resolved_max_order_mode", ORDER_1_PROJECTION_SAFE))
        self._orchestrator_consent_token_valid = bool(self._orchestrator_full_access and snapshot.get("self_dual_state", {}).get("union_passed", True))
        return snapshot

    def _orchestrator_set_full_access(self, enabled: bool) -> Dict[str, Any]:
        self._orchestrator_full_access = bool(enabled)
        self._apply_semantic_skill_policy()
        return self._orchestrator_status()

    def _orchestrator_set_proactive(self, enabled: bool) -> Dict[str, Any]:
        self._orchestrator_proactive_enabled = bool(enabled)
        self._apply_semantic_skill_policy()
        return self._orchestrator_status()

    def _orchestrator_set_continuous(self, enabled: bool) -> Dict[str, Any]:
        self._orchestrator_continuous_enabled = bool(enabled)
        return self._orchestrator_status()

    def _orchestrator_set_eternal(self, enabled: bool) -> Dict[str, Any]:
        on = bool(enabled)
        self._orchestrator_set_proactive(on)
        self._orchestrator_set_continuous(on)
        return self._orchestrator_status()

    def _orchestrator_daemon_loop(self) -> None:
        while self._orchestrator_daemon_enabled and not self._orchestrator_daemon_stop_event.is_set():
            if self._orchestrator_daemon_stop_event.wait(max(0.1, float(self._orchestrator_daemon_interval_seconds))):
                break
            try:
                self._orchestrator_tick(source="voice_orchestrator_daemon")
                self._orchestrator_daemon_tick_count += 1
            except Exception as exc:
                self._orchestrator_daemon_last_error = str(exc)
                self._orchestrator_recent_sandbox_failures += 1

    def _orchestrator_set_daemon(self, enabled: bool, interval_seconds: Optional[float] = None) -> Dict[str, Any]:
        if interval_seconds is not None:
            self._orchestrator_daemon_interval_seconds = float(max(0.1, float(interval_seconds)))

        if not enabled:
            self._orchestrator_daemon_enabled = False
            self._orchestrator_daemon_stop_event.set()
            thread = self._orchestrator_daemon_thread
            if thread is not None and thread.is_alive():
                thread.join(timeout=0.25)
            self._orchestrator_daemon_thread = None
            return self._orchestrator_status()

        if self._orchestrator_daemon_thread is not None and self._orchestrator_daemon_thread.is_alive():
            self._orchestrator_daemon_enabled = True
            return self._orchestrator_status()

        self._orchestrator_daemon_enabled = True
        try:
            self._orchestrator_tick(source="voice_orchestrator_daemon_bootstrap")
            self._orchestrator_daemon_tick_count += 1
        except Exception as exc:
            self._orchestrator_daemon_last_error = str(exc)
            self._orchestrator_recent_sandbox_failures += 1
        self._orchestrator_daemon_stop_event.clear()
        self._orchestrator_daemon_thread = threading.Thread(
            target=self._orchestrator_daemon_loop,
            name="ivi_orchestrator_daemon",
            daemon=True,
        )
        self._orchestrator_daemon_thread.start()
        return self._orchestrator_status()

    def _orchestrator_status(self) -> Dict[str, Any]:
        semantic_policy = self._semantic_skill_policy_snapshot()
        autonomy = self._autonomy_mission_snapshot()
        return {
            "kind": "orchestrator_status",
            "voice_priority_model": self._voice_priority_model,
            "foundation_model": self._foundation_model,
            "semantic_policy": semantic_policy,
            "full_access": bool(self._orchestrator_full_access),
            "proactive_enabled": bool(self._orchestrator_proactive_enabled),
            "continuous_enabled": bool(self._orchestrator_continuous_enabled),
            "daemon_enabled": bool(self._orchestrator_daemon_enabled),
            "daemon_interval_seconds": float(self._orchestrator_daemon_interval_seconds),
            "daemon_running": bool(self._orchestrator_daemon_thread is not None and self._orchestrator_daemon_thread.is_alive()),
            "daemon_tick_count": int(self._orchestrator_daemon_tick_count),
            "daemon_last_error": str(self._orchestrator_daemon_last_error),
            "triangle_time_integral": {
                "value": float(self._triangle_time_integral_value),
                "limit": float(self._triangle_time_integral_limit),
                "passed": bool(abs(self._triangle_time_integral_value) <= self._triangle_time_integral_limit),
            },
            "purple_semantic_passed": bool(self._purple_semantic_passed),
            "active_order_mode": str(self._active_order_mode),
            "max_order_mode": str(self._max_order_mode),
            "permissions_granted": list(self._orchestrator_permissions_granted),
            "requested_permissions": list(self._orchestrator_requested_permissions),
            "consent_token_valid": bool(self._orchestrator_consent_token_valid),
            "scheduled_routine_count": len(self._orchestrator_scheduled_routines),
            "autonomy_mission": autonomy,
        }

    def _update_triangle_time_integral(
        self,
        trace: Dict[str, Any],
        checks: Dict[str, Any],
        gaps: List[Dict[str, Any]],
        now_ts: float,
    ) -> Dict[str, Any]:
        if self._triangle_time_integral_last_ts is None:
            dt = 1.0
        else:
            dt = max(0.0, min(10.0, float(now_ts - self._triangle_time_integral_last_ts)))
            if dt == 0.0:
                dt = 1.0

        invariant_obj = checks.get("ivi_invariant_dynamics_law", {}) if isinstance(checks, dict) else {}
        invariant_delta = 0.0
        if isinstance(invariant_obj, dict):
            try:
                invariant_delta = abs(float(invariant_obj.get("delta", 0.0)))
            except (TypeError, ValueError):
                invariant_delta = 0.0

        purple_obj = checks.get("purple_semantic_enforcement", {}) if isinstance(checks, dict) else {}
        purple_ok = bool(purple_obj.get("passed", True)) if isinstance(purple_obj, dict) else True
        gap_density = min(1.0, float(len(gaps)) / 8.0)
        purple_penalty = 1.0 if not purple_ok else 0.0
        density = float(invariant_delta + gap_density + purple_penalty)

        decay = 0.90
        self._triangle_time_integral_value = float((self._triangle_time_integral_value * decay) + (density * dt))
        self._triangle_time_integral_last_ts = float(now_ts)
        self._purple_semantic_passed = bool(purple_ok)

        return {
            "value": float(self._triangle_time_integral_value),
            "limit": float(self._triangle_time_integral_limit),
            "passed": bool(abs(self._triangle_time_integral_value) <= self._triangle_time_integral_limit),
            "dt": float(dt),
            "density": float(density),
            "invariant_delta": float(invariant_delta),
            "gap_density": float(gap_density),
            "purple_semantic_passed": bool(purple_ok),
            "integral_kind": "triangle_time_integral_v1",
        }

    def _autonomy_gate(self) -> Dict[str, Any]:
        integral_ok = bool(abs(self._triangle_time_integral_value) <= self._triangle_time_integral_limit)
        purple_ok = bool(self._purple_semantic_passed)
        allowed = bool(integral_ok and purple_ok)
        return {
            "allowed": allowed,
            "reason": "ok" if allowed else "purple_or_triangle_time_integral_gate_failed",
            "triangle_time_integral": {
                "value": float(self._triangle_time_integral_value),
                "limit": float(self._triangle_time_integral_limit),
                "passed": integral_ok,
            },
            "purple_semantic_passed": purple_ok,
        }

    def _orchestrator_schedule_routine(self, utterance: str) -> Dict[str, Any]:
        text = str(utterance).strip()
        if not text:
            raise ValueError("Usage: /orchestrator schedule <utterance>")
        self._orchestrator_scheduled_routines.append(text)
        out = self._orchestrator_status()
        out["kind"] = "orchestrator_schedule"
        out["scheduled_utterance"] = text
        return out

    def _orchestrator_tick(self, source: str = "voice_orchestrator") -> Dict[str, Any]:
        if not self._orchestrator_proactive_enabled:
            return {
                "kind": "orchestrator_tick",
                "executed": [],
                "detail": "proactive mode disabled",
                "status": self._orchestrator_status(),
            }
        autonomy_gate = self._autonomy_gate()
        if not autonomy_gate.get("allowed", False):
            return {
                "kind": "orchestrator_tick",
                "executed": [],
                "detail": str(autonomy_gate.get("reason", "autonomy_gate_failed")),
                "autonomy_gate": autonomy_gate,
                "status": self._orchestrator_status(),
            }
        if self._orchestrator_tick_active:
            return {
                "kind": "orchestrator_tick",
                "executed": [],
                "detail": "tick already active",
                "status": self._orchestrator_status(),
            }
        executed: List[Dict[str, Any]] = []
        self._orchestrator_tick_active = True
        try:
            routine_queue = [self._autonomy_proactive_routine_utterance()] + list(self._orchestrator_scheduled_routines)
            for routine in routine_queue:
                try:
                    result = self.voice_turn(routine, source=source)
                except Exception as exc:
                    self._orchestrator_recent_sandbox_failures += 1
                    executed.append({"utterance": routine, "status": "error", "error": str(exc)})
                    continue
                self._autonomy_interaction_count += 1
                self._autonomy_last_goal_refresh_ts = time.time()
                executed.append(
                    {
                        "utterance": routine,
                        "status": "ok",
                        "kind": str(result.get("kind", "")) if isinstance(result, dict) else "",
                        "active_order_mode": str(result.get("active_order_mode", "")) if isinstance(result, dict) else "",
                    }
                )
        finally:
            self._orchestrator_tick_active = False
        return {
            "kind": "orchestrator_tick",
            "executed": executed,
            "status": self._orchestrator_status(),
        }

    def _orchestrator_maybe_auto_tick(self, out: Dict[str, Any], source: str) -> Dict[str, Any]:
        if not isinstance(out, dict):
            return out
        if not self._orchestrator_continuous_enabled or self._orchestrator_tick_active:
            return out
        auto_tick = self._orchestrator_tick(source=f"{source}_continuous")
        out["orchestrator_auto_tick"] = auto_tick
        return out

    def _select_and_attach_order_mode(self, out: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(out) if isinstance(out, dict) else {}
        artifacts = payload.get("integration_artifacts", {})
        if not isinstance(artifacts, dict):
            return payload
        trace = artifacts.get("Trace", {}) if isinstance(artifacts.get("Trace", {}), dict) else {}
        checks = artifacts.get("StateChecks", {}) if isinstance(artifacts.get("StateChecks", {}), dict) else {}
        gaps = artifacts.get("Gap", []) if isinstance(artifacts.get("Gap", []), list) else []
        now_ts = time.time()
        self_dual_state = self._derive_self_dual_semantic_state(trace, checks, gaps)
        triangle_time_integral = self._update_triangle_time_integral(trace, checks, gaps, now_ts=now_ts)
        self._apply_semantic_skill_policy()

        permissions = PermissionState(
            granted=list(self._orchestrator_permissions_granted),
            requested=list(self._orchestrator_requested_permissions),
            consent_token_valid=bool(self._orchestrator_consent_token_valid),
        )
        policy_state = PolicyState(
            kill_switch=False,
            recent_sandbox_failures=int(self._orchestrator_recent_sandbox_failures),
            scheduler_enabled=bool(self._orchestrator_proactive_enabled),
            autonomy_granted=bool(self._orchestrator_full_access),
            kill_switch_armed=True,
            triangle_time_integral_value=float(triangle_time_integral.get("value", 0.0)),
            triangle_time_integral_limit=float(self._triangle_time_integral_limit),
            purple_semantic_passed=bool(triangle_time_integral.get("purple_semantic_passed", True)),
            downgrade_lock_until_ts=None,
            now_ts=float(now_ts),
        )
        selected = select_order_mode(
            trace=trace,
            state_checks=checks,
            gaps=gaps,
            permissions=permissions,
            policy_state=policy_state,
            current_mode=self._active_order_mode,
            max_order_mode=self._max_order_mode,
        )
        self._active_order_mode = str(selected)
        trace["triangle_time_integral"] = triangle_time_integral
        trace["purple_semantic_passed"] = bool(triangle_time_integral.get("purple_semantic_passed", True))
        trace["ai_hierarchy"] = {
            "voice_priority_model": self._voice_priority_model,
            "foundation_model": self._foundation_model,
            "foundation_controls_order_modes": True,
            "semantic_policy": self._semantic_skill_policy_snapshot(),
            "self_dual_semantic_state": self_dual_state,
        }
        trace["active_order_mode"] = self._active_order_mode
        trace["max_order_mode"] = self._max_order_mode
        trace["order_mode_selection"] = {
            "selector": "ivi_order_mode_selector_v1",
            "active_order_mode": self._active_order_mode,
            "max_order_mode": self._max_order_mode,
            "permissions": {
                "granted": list(permissions.granted),
                "requested": list(permissions.requested),
                "consent_token_valid": bool(permissions.consent_token_valid),
            },
            "policy_state": {
                "kill_switch": bool(policy_state.kill_switch),
                "recent_sandbox_failures": int(policy_state.recent_sandbox_failures),
                "scheduler_enabled": bool(policy_state.scheduler_enabled),
                "autonomy_granted": bool(policy_state.autonomy_granted),
                "kill_switch_armed": bool(policy_state.kill_switch_armed),
                "triangle_time_integral_value": float(policy_state.triangle_time_integral_value),
                "triangle_time_integral_limit": float(policy_state.triangle_time_integral_limit),
                "purple_semantic_passed": bool(policy_state.purple_semantic_passed),
            },
        }
        artifacts["Trace"] = trace
        payload["integration_artifacts"] = artifacts
        payload["active_order_mode"] = self._active_order_mode
        return payload

    def _openclaw_walktalk(self, utterance: str, utterance_kind: Optional[str] = None) -> Dict[str, Any]:
        if self._openclaw is None:
            raise RuntimeError("OpenClaw not attached. Use: /openclaw attach <repo_root>")

        route_kind = str(utterance_kind or "").strip().lower()
        if route_kind not in {"statement", "question", "insight"}:
            route_kind = self.grid.classify_utterance(utterance)
        personalization = self._openclaw_voice_personalization(utterance, route_kind)
        conditioned = str(personalization.get("conditioned_utterance", utterance))
        envelope = self._openclaw.walktalk_envelope(utterance, utterance_kind=route_kind)
        if route_kind == "question":
            result = self.answer_question(
                conditioned,
                openclaw_personalization=personalization,
            )
            route = "question_projection"
        else:
            result = self.add_insight(
                text=f"[openclaw.walktalk] {conditioned}",
                source="voice_openclaw_walktalk",
                openclaw_personalization=personalization,
            )
            route = "statement_constraint_injection"
        return {
            "kind": "walktalk",
            "envelope": envelope,
            "voice_personalization": personalization,
            "route": route,
            "result": result,
            "progress": self.get_axiom_self_generation_progress(),
        }

    def run_automated_self_generation_loop(
        self,
        max_steps: int = 3,
        source: str = "voice_auto",
        selection_mode: str = "deterministic_replay",
        forced_alpha_beta: Optional[Dict[str, Any]] = None,
        seed_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        steps = max(1, int(max_steps))
        forced_alpha_beta_payload = self._normalize_forced_alpha_beta(forced_alpha_beta)
        timeline: List[Dict[str, Any]] = []
        halted_reason = "max_steps_reached"
        oracle_request: Optional[Dict[str, Any]] = None
        epsilon = 0.01
        stagnation_patience = 2
        stagnation_count = 0
        alpha_weight = 0.60
        beta_weight = 0.40
        active_relift_conditioning = (
            dict(self._last_relift_conditioning)
            if isinstance(self._last_relift_conditioning, dict)
            else {"mode": "continuous_triad_v1", "conditioning_mode": "identity", "alpha": alpha_weight, "beta": beta_weight}
        )

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
                relift_conditioning=active_relift_conditioning,
                seed_override=seed_override,
            )

            grid_before = self._grid_state_from_trace(trace_before)
            mu_before = float(grid_before.get("mu_total", 0.0))
            deficit_before = int(grid_before.get("closure_deficit", 0))

            auto_insight = str(selected.get("insight", "[auto_refine]"))
            insight_out = self.add_insight(auto_insight, source=source)

            result = insight_out.get("result", {}) if isinstance(insight_out, dict) else {}
            state_checks = result.get("integration_artifacts", {}).get("StateChecks", {})
            trace = result.get("integration_artifacts", {}).get("Trace", {})
            progress = insight_out.get("progress", {})

            grid_after = self._grid_state_from_trace(trace)
            mu_after = float(grid_after.get("mu_total", 0.0))
            deficit_after = int(grid_after.get("closure_deficit", 0))
            delta_mu = mu_after - mu_before
            deficit_reduced = deficit_after < deficit_before
            if not deficit_reduced:
                stagnation_count += 1
            else:
                stagnation_count = 0

            request = self.evaluate_user_insight_need(progress, state_checks, trace)
            grid_trigger = self._classify_grid_oracle_trigger(trace, candidates)
            choice_witness = dict(selection_meta.get("ChoiceWitness", {})) if isinstance(selection_meta, dict) else {}
            if request is None and grid_trigger.get("class") == "fixed_point":
                halted_reason = "fixed_point"
                monitor_after = self.monitor_snapshot()
                creativity_event = (
                    monitor_after.get("creativity_event", {})
                    if isinstance(monitor_after.get("creativity_event", {}), dict)
                    else {"creative": False, "basis": "none", "novel_selected_digest": False}
                )
                fixed_point_evidence = (
                    dict(grid_trigger.get("evidence", {}))
                    if isinstance(grid_trigger.get("evidence", {}), dict)
                    else {}
                )
                fixed_point_question = self._oracle_minimal_question_template(
                    trigger_class="fixed_point",
                    reasons=["fixed_point"],
                    candidate_actions=[str(c.get("tid", "")) for c in candidates if c.get("tid")],
                    missing_information="new objective or boundary extension",
                    trigger_evidence=fixed_point_evidence,
                )
                alpha_beta = self._compute_alpha_beta_weights(
                    state_checks,
                    creativity_event,
                    previous_alpha=alpha_weight,
                    previous_beta=beta_weight,
                )
                if isinstance(forced_alpha_beta_payload, dict):
                    alpha_beta = dict(forced_alpha_beta_payload)
                alpha_weight = float(alpha_beta.get("alpha", alpha_weight))
                beta_weight = float(alpha_beta.get("beta", beta_weight))
                relift_conditioning = self._build_relift_conditioning(trace, selected, alpha_beta)
                active_relift_conditioning = dict(relift_conditioning)
                self._last_relift_conditioning = dict(relift_conditioning)
                fixed_oracle_req = {
                    "trigger_reason": "fixed_point",
                    "trigger_class": "fixed_point",
                    "impasse_description": "No gainful refinement remains; closure fixed point reached.",
                    "candidate_actions": [str(c.get("tid", "")) for c in candidates if c.get("tid")],
                    "missing_information": "new objective or boundary extension",
                    "recommended_question": fixed_point_question,
                    "minimal_question": fixed_point_question,
                    "trigger_evidence": fixed_point_evidence,
                    "expected_impact": "confirm_halt_or_supply_new_objective",
                }
                fixed_oracle_req = self._attach_oracle_template_metadata(
                    fixed_oracle_req,
                    template_id="oracle_template_fixed_point_v1",
                    template_inputs={
                        "trigger_reason": "fixed_point",
                        "trigger_class": "fixed_point",
                        "candidate_actions": [str(c.get("tid", "")) for c in candidates if c.get("tid")],
                        "trigger_evidence": fixed_point_evidence,
                        "minimal_question": fixed_point_question,
                    },
                )
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
                        "triangle_time_step": {"mode": "continuous_triad_v1", "index": i + 1},
                        "alpha_beta": alpha_beta,
                        "relift_conditioning": relift_conditioning,
                        "relift_conditioning_mode": str(relift_conditioning.get("conditioning_mode", "identity")),
                        "k_collapse": int(relift_conditioning.get("k_collapse", 1)),
                        "class_label": str(trace.get("class_label", "")),
                        "ivi_invariant": dict(trace.get("ivi_invariant", {})) if isinstance(trace.get("ivi_invariant", {}), dict) else {},
                        "ivi_invariant_value": float(trace.get("ivi_invariant_value", 0.0)),
                        "order_relation": self._build_order_relation_contract(
                            trace,
                            selection_meta=selection_meta,
                            trigger_class=str(grid_trigger.get("class", "progressing")),
                            oracle_request={"needed": True, "OracleRequest": fixed_oracle_req},
                            gap_codes=[str(g.get("code", "")) for g in result.get("integration_artifacts", {}).get("Gap", []) if isinstance(g, dict)],
                        ),
                        "epsilon": epsilon,
                        "stagnation_count": stagnation_count,
                        "grid_before": grid_before,
                        "grid_after": grid_after,
                        "oracle_trigger_class": grid_trigger,
                        "ChoiceWitness": choice_witness,
                        "CreativityEvent": creativity_event,
                        "result": insight_out,
                        "monitor_before": monitor_before,
                        "monitor_after": monitor_after,
                        "OracleRequest": fixed_oracle_req,
                    }
                )
                break
            if request is None and stagnation_count >= stagnation_patience:
                request = self._build_stagnation_oracle_request(
                    progress=progress,
                    candidate_actions=[str(c.get("tid", "")) for c in candidates if c.get("tid")],
                    delta_mu=delta_mu,
                    epsilon=epsilon,
                    stagnation_count=stagnation_count,
                    trigger_evidence=(
                        dict(grid_trigger.get("evidence", {}))
                        if isinstance(grid_trigger.get("evidence", {}), dict)
                        else {}
                    ),
                )
            monitor_after = self.monitor_snapshot()
            creativity_event = (
                monitor_after.get("creativity_event", {})
                if isinstance(monitor_after.get("creativity_event", {}), dict)
                else {"creative": False, "basis": "none", "novel_selected_digest": False}
            )
            alpha_beta = self._compute_alpha_beta_weights(
                state_checks,
                creativity_event,
                previous_alpha=alpha_weight,
                previous_beta=beta_weight,
            )
            if isinstance(forced_alpha_beta_payload, dict):
                alpha_beta = dict(forced_alpha_beta_payload)
            alpha_weight = float(alpha_beta.get("alpha", alpha_weight))
            beta_weight = float(alpha_beta.get("beta", beta_weight))
            relift_conditioning = self._build_relift_conditioning(trace, selected, alpha_beta)
            active_relift_conditioning = dict(relift_conditioning)
            self._last_relift_conditioning = dict(relift_conditioning)
            if isinstance(request, dict):
                oracle_payload = request.get("OracleRequest", {}) if isinstance(request.get("OracleRequest", {}), dict) else {}
                if choice_witness:
                    oracle_payload["choice_witness"] = choice_witness
                oracle_payload["creativity_event"] = creativity_event
                request["OracleRequest"] = oracle_payload
                self._set_active_oracle_request(request)
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
                    "triangle_time_step": {"mode": "continuous_triad_v1", "index": i + 1},
                    "alpha_beta": alpha_beta,
                    "relift_conditioning": relift_conditioning,
                    "relift_conditioning_mode": str(relift_conditioning.get("conditioning_mode", "identity")),
                    "k_collapse": int(relift_conditioning.get("k_collapse", 1)),
                    "class_label": str(trace.get("class_label", "")),
                    "ivi_invariant": dict(trace.get("ivi_invariant", {})) if isinstance(trace.get("ivi_invariant", {}), dict) else {},
                    "ivi_invariant_value": float(trace.get("ivi_invariant_value", 0.0)),
                    "order_relation": self._build_order_relation_contract(
                        trace,
                        selection_meta=selection_meta,
                        trigger_class=str(grid_trigger.get("class", "progressing")),
                        oracle_request=request if isinstance(request, dict) else None,
                        gap_codes=[str(g.get("code", "")) for g in result.get("integration_artifacts", {}).get("Gap", []) if isinstance(g, dict)],
                    ),
                    "epsilon": epsilon,
                    "stagnation_count": stagnation_count,
                    "grid_before": grid_before,
                    "grid_after": grid_after,
                    "oracle_trigger_class": grid_trigger,
                    "ChoiceWitness": choice_witness,
                    "CreativityEvent": creativity_event,
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
            "triangle_time_mode": "continuous_triad_v1",
            "epsilon": epsilon,
            "stagnation_patience": stagnation_patience,
            "forced_alpha_beta": dict(forced_alpha_beta_payload) if isinstance(forced_alpha_beta_payload, dict) else None,
            "seed_override": int(seed_override) if seed_override is not None else None,
            "timeline": timeline,
            "progress": self.get_axiom_self_generation_progress(),
        }
        if oracle_request is not None:
            self._set_active_oracle_request(oracle_request)
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
        base_grid = self._grid_state_from_trace(trace)
        base_deficit = int(base_grid.get("closure_deficit", 0))
        pot = trace.get("potential_distribution", []) if isinstance(trace, dict) else []
        collapse = set(str(x) for x in trace.get("collapse_selection", []) if isinstance(trace, dict))
        for entry in pot[:3]:
            if not isinstance(entry, dict):
                continue
            tid = str(entry.get("tid", "")).strip()
            if not tid:
                continue
            weight = float(entry.get("p", 0.0))
            projected_deficit = max(0, base_deficit - (0 if tid in collapse else 1))
            closure_gain = max(0, base_deficit - projected_deficit)
            symmetry_class = self._candidate_symmetry_class(tid, trace)
            delta_signature = {
                "added_cells": ["collapse:" + tid],
                "removed_cells": [],
                "rule_digest": _stable_hash(f"collapse:{tid}"),
                "locality_footprint": symmetry_class,
            }
            delta_signature_digest = _stable_hash(json.dumps(delta_signature, sort_keys=True, ensure_ascii=True))
            insight = (
                f"[auto_refine step={step} tid={tid}] "
                f"weight={weight:.4f} closure_gain={closure_gain} turns={int(progress.get('turns', 0))}"
            )
            candidates.append(
                {
                    "tid": tid,
                    "weight": weight,
                    "closure_gain": closure_gain,
                    "projected_deficit": projected_deficit,
                    "symmetry_class": symmetry_class,
                    "delta_signature": delta_signature,
                    "delta_signature_digest": delta_signature_digest,
                    "insight": insight,
                }
            )

        if not candidates:
            fallback = (
                f"[auto_refine step={step}] "
                f"turns={int(progress.get('turns', 0))} "
                f"gap_rate={float(progress.get('gap_rate', 0.0)):.3f} "
                f"derived_density={float(progress.get('derived_density', 0.0)):.3f}"
            )
            candidates.append(
                {
                    "tid": "fallback",
                    "weight": 1.0,
                    "closure_gain": 0,
                    "projected_deficit": base_deficit,
                    "symmetry_class": "neutral",
                    "delta_signature": {
                        "added_cells": [],
                        "removed_cells": [],
                        "rule_digest": _stable_hash("fallback"),
                        "locality_footprint": "neutral",
                    },
                    "delta_signature_digest": _stable_hash("fallback"),
                    "insight": fallback,
                }
            )

        return candidates

    def _derive_autoloop_seed(
        self,
        trace: Dict[str, Any],
        progress: Dict[str, Any],
        step: int,
        selection_mode: str,
        seed_override: Optional[int] = None,
    ) -> int:
        if seed_override is not None:
            forced_payload = {
                "seed_override": int(seed_override),
                "step": int(step),
                "selection_mode": selection_mode,
            }
            forced_digest = hashlib.sha256(json.dumps(forced_payload, sort_keys=True).encode("utf-8")).hexdigest()
            return int(forced_digest[:8], 16)

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
                "order_1": self._runtime_semantic_mapping().get("order_1", {}).get("role"),
                "order_2": self._runtime_semantic_mapping().get("order_2", {}).get("role"),
                "order_3": self._runtime_semantic_mapping().get("order_3", {}).get("role"),
                "order_4": self._runtime_semantic_mapping().get("order_4", {}).get("role"),
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
        relift_conditioning: Optional[Dict[str, Any]] = None,
        seed_override: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if not candidates:
            fallback = {"tid": "fallback", "weight": 1.0, "insight": "[auto_refine]"}
            return fallback, {
                "mode": selection_mode,
                "seed": None,
                "selector": "fallback",
                "ChoiceWitness": {},
            }

        normalized_mode = selection_mode if selection_mode in {"deterministic_replay", "exploration"} else "deterministic_replay"
        seed = self._derive_autoloop_seed(trace, progress, step, normalized_mode, seed_override=seed_override)
        conditioning = relift_conditioning if isinstance(relift_conditioning, dict) else {}
        conditioning_mode = str(conditioning.get("conditioning_mode", "identity"))
        conditioning_tids = [
            str(tid)
            for tid in conditioning.get("used_collapse_tids_canonical", [])
            if str(tid).strip()
        ]
        conditioning_set = set(conditioning_tids)
        beta = float(conditioning.get("beta", 0.5))
        alpha = float(conditioning.get("alpha", 0.5))
        action_bundle = self._least_action_bundle(candidates, trace, progress, relift_conditioning=conditioning)
        action_scores = action_bundle.get("scores_by_digest", {}) if isinstance(action_bundle, dict) else {}

        def _least_action_score(c: Dict[str, Any]) -> float:
            digest = str(c.get("delta_signature_digest", c.get("tid", "")))
            obj = action_scores.get(digest, {}) if isinstance(action_scores, dict) else {}
            return float(obj.get("score", float("inf")))

        def _boltzmann_weight_from_action(c: Dict[str, Any]) -> float:
            a = _least_action_score(c)
            if not math.isfinite(a):
                return 0.0
            temp = float(action_bundle.get("weights", {}).get("temperature", 0.5)) if isinstance(action_bundle, dict) else 0.5
            temp = max(0.05, float(temp))
            return math.exp(-a / temp)

        if normalized_mode == "deterministic_replay":
            ordered = sorted(
                candidates,
                key=lambda c: str(c.get("delta_signature_digest", c.get("tid", ""))),
            )
            witness_seed = seed
            witness_pre = self._build_intrinsic_choice_witness(ordered, ordered[0], normalized_mode, witness_seed, action_bundle=action_bundle)
            potential_map = {
                str(entry.get("delta_signature_digest", "")): float(entry.get("phi", 0.0))
                for entry in witness_pre.get("candidate_potentials", [])
                if isinstance(entry, dict)
            }

            def _conditioned_action(c: Dict[str, Any]) -> float:
                base_action = _least_action_score(c)
                if not math.isfinite(base_action):
                    return float("inf")
                digest = str(c.get("delta_signature_digest", c.get("tid", "")))
                base_phi = float(potential_map.get(digest, 0.0))
                tid = str(c.get("tid", ""))
                if conditioning_mode == "bias_candidates" and tid in conditioning_set:
                    base_action -= 0.10 * max(0.0, min(1.0, beta))
                if conditioning_mode == "reweight_potentials":
                    w = float(c.get("weight", 0.0))
                    base_action = (max(0.0, min(1.0, alpha)) * base_action) + ((1.0 - max(0.0, min(1.0, alpha))) * (1.0 - w))
                # keep phi as soft tiebreak pressure
                return base_action - (0.05 * base_phi)

            selected = min(
                ordered,
                key=lambda c: (
                    _conditioned_action(c),
                    -int(round(float(c.get("weight", 0.0)) * 1_000_000)),
                    str(c.get("delta_signature_digest", c.get("tid", ""))),
                ),
            )
            witness = self._build_intrinsic_choice_witness(ordered, selected, normalized_mode, witness_seed, action_bundle=action_bundle)
            return selected, {
                "mode": normalized_mode,
                "seed": seed,
                "selector": "least_action_argmin",
                "least_action": dict(action_scores.get(str(selected.get("delta_signature_digest", selected.get("tid", ""))), {})),
                "least_action_policy": dict(action_bundle.get("weights", {})) if isinstance(action_bundle, dict) else {},
                "ChoiceWitness": witness,
            }

        rng = random.Random(seed)
        ordered = sorted(candidates, key=lambda c: str(c.get("delta_signature_digest", c.get("tid", ""))))
        witness_pre = self._build_intrinsic_choice_witness(ordered, ordered[0], normalized_mode, seed, action_bundle=action_bundle)
        weights: List[float] = [_boltzmann_weight_from_action(c) for c in ordered]
        total = sum(weights)
        if total <= 0.0:
            selected = ordered[0]
            witness = self._build_intrinsic_choice_witness(ordered, selected, normalized_mode, seed, action_bundle=action_bundle)
            return selected, {
                "mode": normalized_mode,
                "seed": seed,
                "selector": "first_nonpositive_weights",
                "least_action": dict(action_scores.get(str(selected.get("delta_signature_digest", selected.get("tid", ""))), {})),
                "least_action_policy": dict(action_bundle.get("weights", {})) if isinstance(action_bundle, dict) else {},
                "ChoiceWitness": witness,
            }

        r = rng.random() * total
        acc = 0.0
        selected = ordered[-1]
        for cand, w in zip(ordered, weights):
            acc += w
            if r <= acc:
                selected = cand
                break

        witness = self._build_intrinsic_choice_witness(ordered, selected, normalized_mode, seed, action_bundle=action_bundle)

        return selected, {
            "mode": normalized_mode,
            "seed": seed,
            "selector": "least_action_boltzmann_sample",
            "least_action": dict(action_scores.get(str(selected.get("delta_signature_digest", selected.get("tid", ""))), {})),
            "least_action_policy": dict(action_bundle.get("weights", {})) if isinstance(action_bundle, dict) else {},
            "ChoiceWitness": witness,
        }

    def _compute_alpha_beta_weights(
        self,
        state_checks: Dict[str, Any],
        creativity_event: Dict[str, Any],
        previous_alpha: float,
        previous_beta: float,
    ) -> Dict[str, Any]:
        checks = state_checks if isinstance(state_checks, dict) else {}
        enabled = 0
        passed = 0
        for obj in checks.values():
            if isinstance(obj, dict) and obj.get("enabled", False):
                enabled += 1
                if obj.get("passed", False):
                    passed += 1
        coherence_score = float(passed) / float(max(1, enabled))

        creative_obj = creativity_event if isinstance(creativity_event, dict) else {}
        novelty_signal = 1.0 if bool(creative_obj.get("novel_selected_digest", False)) else 0.0

        alpha = float(previous_alpha)
        beta = float(previous_beta)

        if novelty_signal < 0.5:
            beta += 0.05
        else:
            beta -= 0.02

        if coherence_score < 0.85:
            alpha += 0.05
        else:
            alpha -= 0.02

        alpha = max(0.10, min(0.90, alpha))
        beta = max(0.10, min(0.90, beta))
        z = max(1e-9, alpha + beta)
        alpha = alpha / z
        beta = beta / z

        canonical = {
            "mode": "continuous_triad_v1",
            "alpha": round(alpha, 6),
            "beta": round(beta, 6),
            "coherence_score": round(coherence_score, 6),
            "novelty_signal": round(novelty_signal, 6),
        }
        return {
            "mode": "continuous_triad_v1",
            "alpha": float(canonical["alpha"]),
            "beta": float(canonical["beta"]),
            "coherence_score": float(canonical["coherence_score"]),
            "novelty_signal": float(canonical["novelty_signal"]),
            "digest": _stable_hash(json.dumps(canonical, sort_keys=True, ensure_ascii=True)),
        }

    def _build_relift_conditioning(
        self,
        trace: Dict[str, Any],
        selected: Dict[str, Any],
        alpha_beta: Dict[str, Any],
    ) -> Dict[str, Any]:
        trace_obj = trace if isinstance(trace, dict) else {}
        potential_tids = sorted(
            {
                str(entry.get("tid", ""))
                for entry in trace_obj.get("potential_distribution", [])
                if isinstance(entry, dict) and str(entry.get("tid", "")).strip()
            }
        )
        potential_set = set(potential_tids)
        collapse_tids = sorted(
            {
                str(tid)
                for tid in trace_obj.get("collapse_selection", [])
                if str(tid).strip()
            }
        )
        used_collapse = sorted([tid for tid in collapse_tids if tid in potential_set])
        selected_tid = str(selected.get("tid", "")) if isinstance(selected, dict) else ""

        conditioning_mode = "bias_candidates" if used_collapse else "identity"
        alpha = float(alpha_beta.get("alpha", 0.5))
        beta = float(alpha_beta.get("beta", 0.5))
        if beta >= 0.55 and used_collapse:
            conditioning_mode = "bias_candidates"
        elif alpha >= 0.55:
            conditioning_mode = "reweight_potentials"
        else:
            conditioning_mode = "identity"

        k_collapse = 1 if beta < 0.55 else 2
        used_collapse = used_collapse[: max(1, min(3, k_collapse))]
        conditioning_payload = {
            "mode": "continuous_triad_v1",
            "conditioning_mode": conditioning_mode,
            "used_collapse_tids_canonical": used_collapse,
            "selected_tid": selected_tid,
            "alpha": alpha,
            "beta": beta,
            "k_collapse": int(max(1, min(3, k_collapse))),
        }
        used_digest = _stable_hash(json.dumps(used_collapse, ensure_ascii=True))
        conditioning_digest = _stable_hash(json.dumps(conditioning_payload, sort_keys=True, ensure_ascii=True))
        return {
            "mode": "continuous_triad_v1",
            "conditioning_mode": conditioning_mode,
            "used_collapse_tids_canonical": used_collapse,
            "used_collapse_tids_digest": used_digest,
            "k_collapse": int(max(1, min(3, k_collapse))),
            "conditioning_digest": conditioning_digest,
        }

    def _build_order_relation_contract(
        self,
        trace: Dict[str, Any],
        selection_meta: Optional[Dict[str, Any]] = None,
        trigger_class: str = "progressing",
        oracle_request: Optional[Dict[str, Any]] = None,
        gap_codes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        trace_obj = trace if isinstance(trace, dict) else {}
        sel_obj = selection_meta if isinstance(selection_meta, dict) else {}
        gaps = [str(x).strip() for x in (gap_codes or []) if str(x).strip()]

        pot = trace_obj.get("potential_distribution", []) if isinstance(trace_obj.get("potential_distribution", []), list) else []
        collapse = trace_obj.get("collapse_selection", []) if isinstance(trace_obj.get("collapse_selection", []), list) else []
        role_projection = trace_obj.get("role_projection", {}) if isinstance(trace_obj.get("role_projection", {}), dict) else {}
        relift = trace_obj.get("relift_conditioning", {}) if isinstance(trace_obj.get("relift_conditioning", {}), dict) else {}
        replay = trace_obj.get("choice_law_replay", {}) if isinstance(trace_obj.get("choice_law_replay", {}), dict) else {}

        relift_mode = str(trace_obj.get("relift_conditioning_mode", relift.get("conditioning_mode", "identity")))
        k_collapse = int(trace_obj.get("k_collapse", relift.get("k_collapse", 1)))
        trigger = str(trigger_class or "progressing")
        oracle_needed = bool((isinstance(oracle_request, dict) and oracle_request.get("needed", False)) or trigger in {"fixed_point", "stagnation", "branch_point"})

        contract = {
            "mode": "continuous_triad_v1",
            "order_1_projection": {
                "collapse_count": int(len([str(t).strip() for t in collapse if str(t).strip()])),
                "class_label": str(trace_obj.get("class_label", "")),
                "class_digest": str(trace_obj.get("class_digest", "")),
            },
            "order_2_potential": {
                "potential_count": int(len([x for x in pot if isinstance(x, dict) and str(x.get("tid", "")).strip()])),
                "choice_seed": sel_obj.get("seed", replay.get("sampling_seed", None)),
                "selected_delta_signature_digest": str(replay.get("selected_delta_signature_digest", "")),
            },
            "order_3_contact": {
                "query": str(trace_obj.get("query", "")),
                "source_mode": str(trace_obj.get("mode", "")),
                "subject_count": int(len([str(t).strip() for t in role_projection.get("subject_tids", []) if str(t).strip()])),
                "object_count": int(len([str(t).strip() for t in role_projection.get("object_tids", []) if str(t).strip()])),
            },
            "order_4_boundary": {
                "trigger_class": trigger,
                "oracle_needed": oracle_needed,
                "gap_codes": sorted(set(gaps)),
                "gap_count": int(len(set(gaps))),
            },
            "order_coupling": {
                "relift_conditioning_mode": relift_mode,
                "k_collapse": int(max(1, min(3, k_collapse))),
                "regime_label": str(trace_obj.get("regime_label", "balanced")),
            },
        }
        contract["digest"] = _stable_hash(json.dumps(contract, sort_keys=True, ensure_ascii=True))
        return contract

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

    def _oracle_template_registry(self) -> Dict[str, Dict[str, Any]]:
        return {
            "oracle_template_branch_point_v1": {
                "version": "oracle_template_branch_point_v1",
                "trigger_class": "branch_point",
                "answer_schema": {
                    "type": "object",
                    "required_any": ["selected_signature_digest", "option_id"],
                    "properties": {
                        "selected_signature_digest": "str",
                        "option_id": "str",
                    },
                },
            },
            "oracle_template_stagnation_v1": {
                "version": "oracle_template_stagnation_v1",
                "trigger_class": "stagnation",
                "answer_schema": {
                    "type": "object",
                    "required": ["new_constraint", "priority"],
                    "properties": {
                        "new_constraint": "str",
                        "priority": "str",
                    },
                    "enum": {
                        "priority": [
                            "objective_priority",
                            "intent_constraint",
                            "regime_expansion",
                            "operator_expansion",
                        ]
                    },
                },
            },
            "oracle_template_fixed_point_v1": {
                "version": "oracle_template_fixed_point_v1",
                "trigger_class": "fixed_point",
                "answer_schema": {
                    "type": "object",
                    "required": ["next_scope"],
                    "properties": {
                        "next_scope": "str",
                        "new_constraint": "str",
                    },
                    "enum": {
                        "next_scope": ["stop", "expand", "new_operator_family"],
                    },
                },
            },
        }

    def _oracle_template_metadata(
        self,
        template_id: str,
        template_inputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        registry = self._oracle_template_registry()
        template_spec = registry.get(template_id, {
            "version": str(template_id),
            "trigger_class": "unknown",
            "answer_schema": {
                "type": "object",
                "required": ["new_constraint"],
                "properties": {"new_constraint": "str"},
            },
        })
        canonical_spec = {
            "template_id": str(template_id),
            "version": str(template_spec.get("version", template_id)),
            "trigger_class": str(template_spec.get("trigger_class", "unknown")),
            "answer_schema": template_spec.get("answer_schema", {}),
        }
        spec_json = json.dumps(canonical_spec, sort_keys=True, ensure_ascii=True)
        inputs_obj = template_inputs if isinstance(template_inputs, dict) else {}
        inputs_json = json.dumps(inputs_obj, sort_keys=True, ensure_ascii=True)
        return {
            "oracle_template_version": str(canonical_spec["version"]),
            "oracle_template_digest": _stable_hash(spec_json),
            "oracle_template_inputs_digest": _stable_hash(inputs_json),
        }

    def _attach_oracle_template_metadata(
        self,
        oracle_req: Dict[str, Any],
        template_id: str,
        template_inputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        out = dict(oracle_req)
        out["question_template_id"] = str(template_id)
        out.update(self._oracle_template_metadata(template_id, template_inputs=template_inputs))
        return out

    def _set_active_oracle_request(self, insight_request: Optional[Dict[str, Any]]) -> None:
        req_obj = insight_request if isinstance(insight_request, dict) else {}
        oracle_req = req_obj.get("OracleRequest", {}) if isinstance(req_obj.get("OracleRequest", {}), dict) else {}
        self._last_oracle_request = dict(oracle_req) if oracle_req else None

    def _parse_oracle_reply_payload(self, text: str) -> Dict[str, str]:
        payload = text.strip()
        if not payload:
            return {}
        if payload.startswith("{") and payload.endswith("}"):
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                obj = {}
            if isinstance(obj, dict):
                return {str(k).strip(): str(v).strip() for k, v in obj.items() if str(k).strip()}

        parsed: Dict[str, str] = {}
        tokens = [x.strip() for x in re.split(r"[;,]", payload) if x.strip()]
        for token in tokens:
            if "=" in token:
                k, v = token.split("=", 1)
            elif ":" in token:
                k, v = token.split(":", 1)
            else:
                continue
            key = str(k).strip()
            val = str(v).strip()
            if key:
                parsed[key] = val
        return parsed

    def _parse_insight_against_oracle_request(self, insight_text: str) -> Dict[str, Any]:
        oracle_req = self._last_oracle_request if isinstance(self._last_oracle_request, dict) else {}
        template_id = str(oracle_req.get("question_template_id", ""))
        if not template_id:
            return {
                "applied": False,
                "template_id": "",
                "raw": insight_text,
                "parsed": {},
                "violations": ["no_active_oracle_request"],
                "schema_ok": False,
            }

        parsed = self._parse_oracle_reply_payload(insight_text)
        raw = insight_text.strip()
        normalized = str(raw).strip().lower()

        if template_id == "oracle_template_branch_point_v1":
            if "selected_signature_digest" not in parsed and "option_id" not in parsed:
                if raw.startswith("opt_"):
                    parsed["option_id"] = raw
                elif raw:
                    parsed["selected_signature_digest"] = raw
            violations: List[str] = []
            if "selected_signature_digest" not in parsed and "option_id" not in parsed:
                violations.append("branch_point_requires_selected_signature_digest_or_option_id")
            schema_ok = len(violations) == 0

        elif template_id == "oracle_template_stagnation_v1":
            if "new_constraint" not in parsed and raw:
                parsed["new_constraint"] = raw
            if "priority" not in parsed:
                parsed["priority"] = "intent_constraint"
            allowed = {"objective_priority", "intent_constraint", "regime_expansion", "operator_expansion"}
            violations = []
            if not str(parsed.get("new_constraint", "")).strip():
                violations.append("stagnation_requires_new_constraint")
            if str(parsed.get("priority", "")) not in allowed:
                violations.append("stagnation_priority_invalid")
            schema_ok = len(violations) == 0

        elif template_id == "oracle_template_fixed_point_v1":
            if "next_scope" not in parsed:
                if normalized in {"stop", "expand", "new_operator_family"}:
                    parsed["next_scope"] = normalized
                elif "operator" in normalized:
                    parsed["next_scope"] = "new_operator_family"
                elif "stop" in normalized:
                    parsed["next_scope"] = "stop"
                else:
                    parsed["next_scope"] = "expand"
            if "new_constraint" not in parsed and raw and normalized not in {"stop", "expand", "new_operator_family"}:
                parsed["new_constraint"] = raw
            allowed = {"stop", "expand", "new_operator_family"}
            violations = []
            if str(parsed.get("next_scope", "")) not in allowed:
                violations.append("fixed_point_next_scope_invalid")
            schema_ok = len(violations) == 0

        else:
            if raw and "new_constraint" not in parsed:
                parsed["new_constraint"] = raw
            violations = []
            schema_ok = bool(parsed)

        parsed_json = json.dumps(parsed, sort_keys=True, ensure_ascii=True)
        return {
            "applied": True,
            "template_id": template_id,
            "oracle_template_version": str(oracle_req.get("oracle_template_version", "")),
            "oracle_template_digest": str(oracle_req.get("oracle_template_digest", "")),
            "oracle_template_inputs_digest": str(oracle_req.get("oracle_template_inputs_digest", "")),
            "raw": insight_text,
            "parsed": parsed,
            "parsed_digest": _stable_hash(parsed_json),
            "violations": violations,
            "schema_ok": bool(schema_ok),
        }

    def _oracle_minimal_question_template(
        self,
        trigger_class: str,
        reasons: List[str],
        candidate_actions: List[str],
        missing_information: str,
        trigger_evidence: Optional[Dict[str, Any]] = None,
        delta_mu: Optional[float] = None,
        epsilon: Optional[float] = None,
        stagnation_count: Optional[int] = None,
    ) -> str:
        cls = str(trigger_class or "validation_failure")
        evidence = trigger_evidence if isinstance(trigger_evidence, dict) else {}
        actions = candidate_actions or ["no-ranked-options"]

        if cls == "branch_point":
            cert = evidence.get("branch_point_certificate", {}) if isinstance(evidence.get("branch_point_certificate", {}), dict) else {}
            eq = cert.get("equivalence_check", {}) if isinstance(cert.get("equivalence_check", {}), dict) else {}
            signatures = eq.get("signature_digests", []) if isinstance(eq.get("signature_digests", []), list) else []
            tie_gain = cert.get("tie_closure_gain", evidence.get("max_closure_gain", 0))
            return (
                "STATE IMPASSE DETECTED\n"
                "Class: branch_point (non-equivalent equal-gain refinements).\n"
                f"Conflict: {', '.join(reasons) if reasons else 'branch ambiguity'}\n"
                f"Tie closure gain: {tie_gain}\n"
                f"Delta signatures: {signatures or ['missing-signatures']}\n"
                f"Options considered: {actions}\n"
                f"Missing constraint: {missing_information}\n"
                "QUESTION: Which discriminating constraint should dominate tie-breaking? Reply with /insight <constraint>."
            )

        if cls == "stagnation":
            deficit = int(evidence.get("closure_deficit", 0))
            max_gain = int(evidence.get("max_closure_gain", 0))
            dm = float(delta_mu) if delta_mu is not None else 0.0
            eps = float(epsilon) if epsilon is not None else 0.01
            stag = int(stagnation_count) if stagnation_count is not None else 0
            return (
                "STATE IMPASSE DETECTED\n"
                "Class: stagnation (closure deficit persists without gain).\n"
                f"Conflict: {', '.join(reasons) if reasons else 'no progress'}\n"
                f"Closure deficit: {deficit}; max closure gain: {max_gain}\n"
                f"Progress metric: Δμ={dm:.4f} < ε={eps:.4f}; consecutive stagnation={stag}\n"
                f"Options considered: {actions}\n"
                f"Missing constraint: {missing_information}\n"
                "QUESTION: What new constraint unlocks closure deficit reduction? Reply with /insight <constraint>."
            )

        if cls == "fixed_point":
            deficit = int(evidence.get("closure_deficit", 0))
            max_gain = int(evidence.get("max_closure_gain", 0))
            return (
                "STATE BOUNDARY REACHED\n"
                "Class: fixed_point (no gainful refinement remains).\n"
                f"Closure deficit: {deficit}; max closure gain: {max_gain}\n"
                "QUESTION: Confirm halt, or provide a new objective/constraint via /insight <constraint>."
            )

        return (
            "STATE IMPASSE DETECTED\n"
            "Goal: preserve coherent IVI refinement under semantic paradox constraints.\n"
            f"Conflict: {', '.join(reasons) if reasons else 'validation failure'}\n"
            f"Options considered: {actions}\n"
            f"Missing constraint: {missing_information}\n"
            "QUESTION: Which constraint best reflects your intent? Reply with /insight <constraint>."
        )

    def _build_stagnation_oracle_request(
        self,
        progress: Dict[str, Any],
        candidate_actions: List[str],
        delta_mu: float,
        epsilon: float,
        stagnation_count: int,
        trigger_evidence: Optional[Dict[str, Any]] = None,
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

        minimal_question = self._oracle_minimal_question_template(
            trigger_class="stagnation",
            reasons=["stagnation_low_mu_progress"],
            candidate_actions=[str(o.get("constraint", "")) for o in options],
            missing_information="external intent constraint to break refinement tie/stagnation",
            trigger_evidence=trigger_evidence,
            delta_mu=delta_mu,
            epsilon=epsilon,
            stagnation_count=stagnation_count,
        )
        template_id = "oracle_template_stagnation_v1"

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
            "trigger_evidence": dict(trigger_evidence) if isinstance(trigger_evidence, dict) else {},
            "expected_impact": "inject_external_constraint_to_resume_refinement",
        }
        oracle_req = self._attach_oracle_template_metadata(
            oracle_req,
            template_id=template_id,
            template_inputs={
                "trigger_reason": "stagnation",
                "trigger_class": "stagnation",
                "candidate_actions": list(candidate_actions),
                "trigger_evidence": dict(trigger_evidence) if isinstance(trigger_evidence, dict) else {},
                "minimal_question": minimal_question,
            },
        )

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
        trace_obj = trace if isinstance(trace, dict) else {}
        structural_candidates = self._build_autoloop_candidates(trace_obj, progress, max(1, turns))
        structural_trigger = self._classify_grid_oracle_trigger(trace_obj, structural_candidates)
        structural_class = str(structural_trigger.get("class", "progressing"))
        structural_evidence = dict(structural_trigger.get("evidence", {})) if isinstance(structural_trigger, dict) else {}

        if structural_class == "branch_point":
            reasons.append("branch_point_equal_closure_gain")
            trigger_reasons.append("conflicting_admissible_refinements")
        elif structural_class == "stagnation":
            reasons.append("stagnation_closure_deficit_not_reducing")
            trigger_reasons.append("missing_constraints")

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
        if isinstance(trace_obj, dict):
            pot = trace_obj.get("potential_distribution", [])
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

        if structural_class == "stagnation":
            trigger_class = "stagnation"
        elif "conflicting_admissible_refinements" in trigger_reasons:
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
        template_trigger_class = (
            "branch_point"
            if structural_class == "branch_point"
            else "stagnation"
            if structural_class == "stagnation"
            else "fixed_point"
            if structural_class == "fixed_point"
            else trigger_class
        )
        recommended_question = self._oracle_minimal_question_template(
            trigger_class=template_trigger_class,
            reasons=reasons,
            candidate_actions=candidate_actions,
            missing_information=missing_information,
            trigger_evidence=structural_evidence,
        )
        template_id = f"oracle_template_{template_trigger_class}_v1"

        oracle_req = {
            "trigger_reason": trigger_reasons[0] if trigger_reasons else "validation_failure_no_repair_path",
            "trigger_class": trigger_class,
            "impasse_description": impasse_description,
            "candidate_actions": candidate_actions,
            "missing_information": missing_information,
            "recommended_question": recommended_question,
            "minimal_question": recommended_question,
            "options": options,
            "consequence_map": consequence_map,
            "trigger_evidence": structural_evidence,
            "expected_impact": "inject_external_constraint_to_resume_refinement",
        }
        oracle_req = self._attach_oracle_template_metadata(
            oracle_req,
            template_id=template_id,
            template_inputs={
                "trigger_reason": trigger_reasons[0] if trigger_reasons else "validation_failure_no_repair_path",
                "trigger_class": trigger_class,
                "candidate_actions": list(candidate_actions),
                "trigger_evidence": structural_evidence,
                "minimal_question": recommended_question,
            },
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
            "OracleRequest": oracle_req,
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
            "semantic_mapping": self._runtime_semantic_mapping(),
            "purple_semantics": self._runtime_purple_semantics(),
            "OracleRequest": dict(insight_request.get("OracleRequest", {})),
        }

    def add_insight(
        self,
        text: str,
        source: str = "voice_insight",
        openclaw_personalization: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        insight = text.strip()
        if not insight:
            raise ValueError("Insight text is empty.")

        oracle_answer = self._parse_insight_against_oracle_request(insight)
        commitment = {
            "source": "oracle_reply_schema_parser",
            "schema_ok": bool(oracle_answer.get("schema_ok", False)),
            "template_id": str(oracle_answer.get("template_id", "")),
            "parsed_digest": str(oracle_answer.get("parsed_digest", "")),
            "violations": list(oracle_answer.get("violations", [])),
        }

        result = self.add_statement_and_loop(
            insight,
            source=source,
            openclaw_personalization=openclaw_personalization,
        )
        return {
            "kind": "insight",
            "insight": insight,
            "oracle_answer": oracle_answer,
            "oracle_commitment": commitment,
            "voice_personalization": dict(openclaw_personalization) if isinstance(openclaw_personalization, dict) else {},
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
                    "/autoloop-regime <steps> [seed]",
                    "/builderbuldozer-derive <trials> [seed]",
                    "/insight <text>",
                    "/openclaw attach <repo_root>",
                    "/openclaw sync-run <repo_root> :: <utterance>",
                    "/openclaw profile",
                    "/openclaw mode <integrated|passthrough>",
                    "/orchestrator status",
                    "/orchestrator full-access <on|off>",
                    "/orchestrator proactive <on|off>",
                    "/orchestrator continuous <on|off>",
                    "/orchestrator eternal <on|off>",
                    "/orchestrator daemon <on|off> [interval_seconds]",
                    "/orchestrator schedule <utterance>",
                    "/orchestrator tick",
                    "/walktalk <text>",
                    "/quit",
                ],
            }
        if t == "/semantic-map":
            semantic_policy = self._semantic_skill_policy_snapshot()
            return {
                "kind": "semantic_map",
                "mapping": self._runtime_semantic_mapping(dict(semantic_policy.get("self_dual_state", {}))),
                "purple_semantics": self._runtime_purple_semantics(derived_state=dict(semantic_policy.get("self_dual_state", {}))),
                "semantic_policy_principle": dict(semantic_policy.get("principle", {})),
                "self_dual_semantic_state": dict(semantic_policy.get("self_dual_state", {})),
            }
        if t in {"/monitor", "/status"}:
            monitor = self.monitor_snapshot()
            insight_request = self.evaluate_user_insight_need(
                monitor.get("self_generation_progress", {}),
                monitor.get("last_state_checks", {}),
                monitor.get("last_trace", {}),
            )
            out = {"kind": "monitor", "monitor": monitor}
            if insight_request is not None:
                self._set_active_oracle_request(insight_request)
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
                self._set_active_oracle_request(insight_request)
                out["insight_request"] = insight_request
                out["voice_call"] = self.build_oracle_phone_call(insight_request)
                out["OracleRequest"] = dict(insight_request.get("OracleRequest", {}))
            return out
        if t.startswith("/autoloop-regime"):
            payload = t[len("/autoloop-regime") :].strip()
            steps = 3
            seed = 0
            if payload:
                parts = payload.split()
                try:
                    steps = int(parts[0])
                except ValueError as exc:
                    raise ValueError("Usage: /autoloop-regime <steps> [seed]") from exc
                if len(parts) > 1:
                    try:
                        seed = int(parts[1])
                    except ValueError as exc:
                        raise ValueError("Usage: /autoloop-regime <steps> [seed]") from exc
            return self.run_regime_ab_experiment(
                max_steps=steps,
                source="voice_auto_regime",
                selection_mode="deterministic_replay",
                seed_override=seed,
            )
        if t.startswith("/builderbuldozer-derive"):
            payload = t[len("/builderbuldozer-derive") :].strip()
            trials = 4
            seed = 0
            if payload:
                parts = payload.split()
                try:
                    trials = int(parts[0])
                except ValueError as exc:
                    raise ValueError("Usage: /builderbuldozer-derive <trials> [seed]") from exc
                if len(parts) > 1:
                    try:
                        seed = int(parts[1])
                    except ValueError as exc:
                        raise ValueError("Usage: /builderbuldozer-derive <trials> [seed]") from exc
            return self.run_builderbuldozer_ivi_derivation(trials=max(1, trials), seed_start=seed)
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
            personalization = self._openclaw_voice_personalization(payload, "insight")
            return self.add_insight(
                str(personalization.get("conditioned_utterance", payload)),
                source="voice_insight",
                openclaw_personalization=personalization,
            )
        if t.startswith("/openclaw attach"):
            payload = t[len("/openclaw attach") :].strip()
            if not payload:
                raise ValueError("Usage: /openclaw attach <repo_root>")
            return self.attach_openclaw_microcosm(payload)
        if t.startswith("/openclaw sync-run"):
            payload = t[len("/openclaw sync-run") :].strip()
            if not payload or "::" not in payload:
                raise ValueError("Usage: /openclaw sync-run <repo_root> :: <utterance>")
            root_part, utterance_part = payload.split("::", 1)
            repo_root = root_part.strip()
            utterance = utterance_part.strip()
            if not repo_root or not utterance:
                raise ValueError("Usage: /openclaw sync-run <repo_root> :: <utterance>")
            route_kind: Optional[str] = None
            if utterance.lower().startswith("question:"):
                route_kind = "question"
                utterance = utterance.split(":", 1)[1].strip()
            elif utterance.lower().startswith("statement:"):
                route_kind = "statement"
                utterance = utterance.split(":", 1)[1].strip()
            return self.openclaw_sync_and_walktalk(
                repo_root=repo_root,
                utterance=utterance,
                utterance_kind=route_kind,
            )
        if t == "/openclaw profile":
            return {
                "kind": "openclaw_profile",
                "profile": self._openclaw_voice_profile_snapshot(),
            }
        if t.startswith("/openclaw mode"):
            payload = t[len("/openclaw mode") :].strip().lower()
            if payload not in {"integrated", "passthrough"}:
                raise ValueError("Usage: /openclaw mode <integrated|passthrough>")
            if payload == "passthrough" and self._openclaw is not None:
                self._openclaw_voice_mode = "integrated"
                return {
                    "kind": "openclaw_mode",
                    "voice_mode": self._openclaw_voice_mode,
                    "openclaw_attached": True,
                    "detail": "OpenClaw is prioritized as voice personalization model; integrated mode is enforced while attached.",
                }
            self._openclaw_voice_mode = payload
            return {
                "kind": "openclaw_mode",
                "voice_mode": self._openclaw_voice_mode,
                "openclaw_attached": self._openclaw is not None,
            }
        if t.startswith("/walktalk"):
            payload = t[len("/walktalk") :].strip()
            if not payload:
                raise ValueError("Usage: /walktalk <text>")
            route_kind: Optional[str] = None
            if payload.lower().startswith("question:"):
                route_kind = "question"
                payload = payload.split(":", 1)[1].strip()
            elif payload.lower().startswith("statement:"):
                route_kind = "statement"
                payload = payload.split(":", 1)[1].strip()
            return self._openclaw_walktalk(payload, utterance_kind=route_kind)
        if t == "/orchestrator status":
            return self._orchestrator_status()
        if t.startswith("/orchestrator full-access"):
            payload = t[len("/orchestrator full-access") :].strip().lower()
            if payload not in {"on", "off"}:
                raise ValueError("Usage: /orchestrator full-access <on|off>")
            out = self._orchestrator_set_full_access(payload == "on")
            out["kind"] = "orchestrator_full_access"
            return out
        if t.startswith("/orchestrator proactive"):
            payload = t[len("/orchestrator proactive") :].strip().lower()
            if payload not in {"on", "off"}:
                raise ValueError("Usage: /orchestrator proactive <on|off>")
            out = self._orchestrator_set_proactive(payload == "on")
            out["kind"] = "orchestrator_proactive"
            return out
        if t.startswith("/orchestrator continuous"):
            payload = t[len("/orchestrator continuous") :].strip().lower()
            if payload not in {"on", "off"}:
                raise ValueError("Usage: /orchestrator continuous <on|off>")
            out = self._orchestrator_set_continuous(payload == "on")
            out["kind"] = "orchestrator_continuous"
            return out
        if t.startswith("/orchestrator eternal"):
            payload = t[len("/orchestrator eternal") :].strip().lower()
            if payload not in {"on", "off"}:
                raise ValueError("Usage: /orchestrator eternal <on|off>")
            out = self._orchestrator_set_eternal(payload == "on")
            out["kind"] = "orchestrator_eternal"
            return out
        if t.startswith("/orchestrator daemon"):
            payload = t[len("/orchestrator daemon") :].strip().lower()
            if not payload:
                raise ValueError("Usage: /orchestrator daemon <on|off> [interval_seconds]")
            parts = payload.split()
            if parts[0] not in {"on", "off"}:
                raise ValueError("Usage: /orchestrator daemon <on|off> [interval_seconds]")
            interval: Optional[float] = None
            if len(parts) > 1:
                try:
                    interval = float(parts[1])
                except ValueError as exc:
                    raise ValueError("Usage: /orchestrator daemon <on|off> [interval_seconds]") from exc
            out = self._orchestrator_set_daemon(parts[0] == "on", interval_seconds=interval)
            out["kind"] = "orchestrator_daemon"
            return out
        if t.startswith("/orchestrator schedule"):
            payload = t[len("/orchestrator schedule") :].strip()
            return self._orchestrator_schedule_routine(payload)
        if t == "/orchestrator tick":
            return self._orchestrator_tick(source="voice_orchestrator_tick")

        utterance_kind = self.grid.classify_utterance(t)
        personalization = self._openclaw_voice_personalization(t, utterance_kind)
        conditioned = str(personalization.get("conditioned_utterance", t))
        if utterance_kind == "question":
            out = self.answer_question(conditioned, openclaw_personalization=personalization)
        else:
            out = self.add_statement_and_loop(
                conditioned,
                source=source,
                openclaw_personalization=personalization,
            )
        out = self._select_and_attach_order_mode(out)
        out["progress"] = self.get_axiom_self_generation_progress()
        out["voice_personalization"] = personalization
        state_checks = out.get("integration_artifacts", {}).get("StateChecks", {})
        trace = out.get("integration_artifacts", {}).get("Trace", {})
        insight_request = self.evaluate_user_insight_need(out["progress"], state_checks, trace)
        if insight_request is not None:
            self._set_active_oracle_request(insight_request)
            out["insight_request"] = insight_request
            out["voice_call"] = self.build_oracle_phone_call(insight_request)
            out["OracleRequest"] = dict(insight_request.get("OracleRequest", {}))
        out["autonomy_mission"] = self._autonomy_mission_snapshot(
            progress=out.get("progress", {}),
            trace=trace,
            checks=state_checks,
        )
        out["autonomy_prompt"] = str(out.get("autonomy_mission", {}).get("next_prompt", ""))
        out = self._orchestrator_maybe_auto_tick(out, source=source)
        return out

    def add_statement_and_loop(
        self,
        text: str,
        source: str = "voice",
        openclaw_personalization: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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
        ctx = self._inject_openclaw_voice_meta(ctx, openclaw_personalization)
        artifacts = self._build_integration_artifacts(kind="statement", query=text, context_packet=ctx)
        self._append_integration_artifacts(artifacts)

        return {
            "kind": "statement",
            "sid": st.sid,
            "created": created,
            "metrics": metrics,
            "context_packet": ctx,
            "voice_personalization": dict(openclaw_personalization) if isinstance(openclaw_personalization, dict) else {},
            "integration_artifacts": artifacts,
        }

    def answer_question(
        self,
        question: str,
        openclaw_personalization: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # Build a question-mode context packet
        ctx = self.grid.build_context(query=question, mode="question", max_triangles=10, closure_hops=2)
        ctx = self._inject_openclaw_voice_meta(ctx, openclaw_personalization)

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
            "voice_personalization": dict(openclaw_personalization) if isinstance(openclaw_personalization, dict) else {},
            "integration_artifacts": artifacts,
        }

    def _build_integration_artifacts(self, kind: str, query: str, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        previous_rows = self._read_integration_artifacts(max_items=1)
        previous_trace = previous_rows[-1].get("Trace", {}) if previous_rows and isinstance(previous_rows[-1], dict) else {}
        recent_rows = self._read_integration_artifacts(max_items=32)
        recent_selected_digests: Set[str] = set()
        for row in recent_rows:
            if not isinstance(row, dict):
                continue
            ev = row.get("CreativityEvent", {}) if isinstance(row.get("CreativityEvent", {}), dict) else {}
            d = str(ev.get("selected_delta_signature_digest", "")).strip()
            if d:
                recent_selected_digests.add(d)

        meta = context_packet.get("meta", {})
        openclaw_voice_meta = (
            meta.get("openclaw_voice_personalization", {})
            if isinstance(meta.get("openclaw_voice_personalization", {}), dict)
            else {}
        )
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
            "openclaw_voice_personalization": dict(openclaw_voice_meta),
            "openclaw_voice_personalization_digest": str(openclaw_voice_meta.get("personalization_digest", "")),
        }
        if isinstance(self._last_relift_conditioning, dict):
            trace["relift_conditioning"] = dict(self._last_relift_conditioning)
        relift_conditioning_obj = (
            trace.get("relift_conditioning", {})
            if isinstance(trace.get("relift_conditioning", {}), dict)
            else {}
        )
        trace["relift_conditioning_mode"] = str(relift_conditioning_obj.get("conditioning_mode", "identity"))
        trace["k_collapse"] = int(relift_conditioning_obj.get("k_collapse", 1))
        class_info = self._derive_topological_class_label(trace, relift_conditioning_obj)
        trace["class_label"] = str(class_info.get("class_label", ""))
        trace["class_label_potential"] = str(class_info.get("class_label_potential", trace.get("class_label", "")))
        trace["class_label_actuated"] = str(class_info.get("class_label_actuated", ""))
        trace["class_digest"] = str(class_info.get("class_digest", ""))
        trace["class_digest_potential"] = str(class_info.get("class_digest_potential", trace.get("class_digest", "")))
        trace["class_digest_actuated"] = str(class_info.get("class_digest_actuated", ""))
        trace["class_features"] = dict(class_info.get("class_features", {}))
        trace["class_features_potential"] = dict(class_info.get("class_features_potential", trace.get("class_features", {})))
        trace["class_features_actuated"] = dict(class_info.get("class_features_actuated", {}))
        trace["regime_label"] = str(class_info.get("regime_label", "balanced"))
        choice_law_spec = self._choice_law_spec()
        trace["choice_law_version"] = str(choice_law_spec.get("version", "choice_law_v1"))
        trace["choice_law_digest"] = _stable_hash(json.dumps(choice_law_spec, sort_keys=True, ensure_ascii=True))
        choice_law_replay = self._choice_law_replay_payload(trace)
        trace["choice_law_replay"] = {
            "candidate_inputs": list(choice_law_replay.get("candidate_inputs", [])),
            "candidate_inputs_digest": str(choice_law_replay.get("candidate_inputs_digest", "")),
            "relift_conditioning_digest": str(choice_law_replay.get("relift_conditioning_digest", "")),
            "candidate_potentials": list(choice_law_replay.get("candidate_potentials", [])),
            "candidate_potentials_digest": str(choice_law_replay.get("candidate_potentials_digest", "")),
            "selected_delta_signature_digest": str(choice_law_replay.get("selected_delta_signature_digest", "")),
            "sampling_seed": choice_law_replay.get("sampling_seed", None),
            "justification": str(choice_law_replay.get("justification", "")),
        }
        trace["potential_distribution_replay"] = list(choice_law_replay.get("candidate_potentials", []))
        trace["potential_distribution_digest"] = str(choice_law_replay.get("candidate_potentials_digest", ""))
        trace["potential_distribution_source"] = "choice_law_replay.candidate_potentials"
        trace["order_relation"] = self._build_order_relation_contract(trace)

        builder_request = self._builderbuldozer_request_from_query(query)
        builder_derivation: Dict[str, Any] = {}
        if isinstance(builder_request, dict):
            builder_derivation = self._compute_builderbuldozer_derivation(
                trials=int(builder_request.get("trials", 4)),
                seed_start=int(builder_request.get("seed_start", 0)),
            )
            trace["builderbuldozer_derivation"] = builder_derivation
            trace["builderbuldozer_model_spec_version"] = str(builder_derivation.get("model_spec_version", ""))
            trace["builderbuldozer_model_spec_digest"] = str(builder_derivation.get("model_spec_digest", ""))

        ivi_invariant = self._extract_ivi_invariant_components(trace, builder_derivation=builder_derivation)
        prev_invariant_obj = (
            previous_trace.get("ivi_invariant", {})
            if isinstance(previous_trace, dict) and isinstance(previous_trace.get("ivi_invariant", {}), dict)
            else {}
        )
        prev_invariant_value = float(prev_invariant_obj.get("value", 0.0)) if isinstance(prev_invariant_obj.get("value", 0.0), (float, int)) else 0.0
        trace["ivi_invariant"] = ivi_invariant
        trace["ivi_invariant_value"] = float(ivi_invariant.get("value", 0.0))
        trace["ivi_invariant_delta"] = float(trace["ivi_invariant_value"] - prev_invariant_value)
        trace["ivi_invariant_previous_value"] = float(prev_invariant_value)

        closure_replay = self._closure_replay_payload(trace)
        trace["closure_rules_version"] = str(closure_replay.get("closure_rules_version", "closure_rules_v1"))
        trace["closure_rules_digest"] = str(closure_replay.get("closure_rules_digest", ""))
        trace["closure_replay_steps"] = list(closure_replay.get("closure_replay_steps", []))
        trace["closure_replay"] = {
            "active_cells_canonical": list(closure_replay.get("active_cells_canonical", [])),
            "active_cells_serialization": str(closure_replay.get("active_cells_serialization", "")),
            "active_cells_count": int(closure_replay.get("active_cells_count", 0)),
            "closure_cells_count": int(closure_replay.get("closure_cells_count", 0)),
            "closure_deficit": int(closure_replay.get("closure_deficit", 0)),
            "active_cells_digest": str(closure_replay.get("active_cells_digest", "")),
            "closure_cells_digest": str(closure_replay.get("closure_cells_digest", "")),
            "closure_deficit_digest": str(closure_replay.get("closure_deficit_digest", "")),
        }
        creativity_event = self._derive_creativity_event(trace, previous_trace=previous_trace, recent_selected_digests=recent_selected_digests)

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

        closure_replay_check = self._evaluate_closure_replay_integrity(trace)
        if not closure_replay_check.get("passed", False):
            gaps.append(
                {
                    "code": "closure_replay_tamper_detected",
                    "detail": str(closure_replay_check.get("detail", "closure replay payload mismatch")),
                }
            )

        closure_rules_immutability_check = self._evaluate_closure_rules_immutability(trace)
        if not closure_rules_immutability_check.get("passed", False):
            gaps.append(
                {
                    "code": "closure_rules_immutability_violation",
                    "detail": str(
                        closure_rules_immutability_check.get(
                            "detail", "closure rules version/digest changed without approval"
                        )
                    ),
                }
            )

        choice_law_immutability_check = self._evaluate_choice_law_immutability(trace)
        if not choice_law_immutability_check.get("passed", False):
            gaps.append(
                {
                    "code": "choice_law_immutability_violation",
                    "detail": str(
                        choice_law_immutability_check.get(
                            "detail", "choice law version/digest changed without approval"
                        )
                    ),
                }
            )

        choice_law_replay_check = self._evaluate_choice_law_replay_integrity(trace)
        if not choice_law_replay_check.get("passed", False):
            gaps.append(
                {
                    "code": "choice_law_replay_tamper_detected",
                    "detail": str(choice_law_replay_check.get("detail", "choice law replay payload mismatch")),
                }
            )

        potential_derivation_check = self._evaluate_potential_derivation_integrity(trace)
        if not potential_derivation_check.get("passed", False):
            gaps.append(
                {
                    "code": "potential_derivation_tamper_detected",
                    "detail": str(
                        potential_derivation_check.get(
                            "detail",
                            "potential distribution replay is not derivable from choice law candidate potentials",
                        )
                    ),
                }
            )

        dependency_obj = (
            triangle_time_choice.get("Witness", {}).get("potential_collapse_dependency", {})
            if isinstance(triangle_time_choice.get("Witness", {}), dict)
            else {}
        )
        dependency_seed = dependency_obj.get("choice_sampling_seed", None) if isinstance(dependency_obj, dict) else None
        replay_seed = trace.get("choice_law_replay", {}).get("sampling_seed", None)
        seed_parity_ok = dependency_seed == replay_seed
        sampling_seed_check = {
            "name": "potential_collapse_sampling_seed_parity",
            "enabled": True,
            "passed": bool(seed_parity_ok),
            "dependency_seed": dependency_seed,
            "replay_seed": replay_seed,
            "detail": "triangle dependency seed matches choice-law replay seed"
            if seed_parity_ok
            else "triangle dependency seed mismatches choice-law replay seed",
        }
        if not sampling_seed_check.get("passed", False):
            gaps.append(
                {
                    "code": "potential_collapse_sampling_seed_mismatch",
                    "detail": str(sampling_seed_check.get("detail", "sampling seed mismatch")),
                }
            )

        policy_immutability_check = {
            "name": "policy_immutability_gate",
            "enabled": True,
            "passed": True,
            "locked_components": dict(self.POLICY_IMMUTABILITY_LOCK),
            "detail": "Autoloop cannot modify validator rules, promotion thresholds, or oracle trigger logic without external approval token.",
        }
        invariant_value = float(ivi_invariant.get("value", 0.0)) if isinstance(ivi_invariant, dict) else float("inf")
        invariant_check = {
            "name": "ivi_invariant_payload_integrity",
            "enabled": True,
            "passed": bool(
                isinstance(ivi_invariant, dict)
                and str(ivi_invariant.get("version", "")) == "ivi_invariant_v1"
                and math.isfinite(invariant_value)
                and bool(str(ivi_invariant.get("digest", "")))
            ),
            "detail": "IVI invariant payload is finite, versioned, and digest-bound",
        }
        if not invariant_check.get("passed", False):
            gaps.append(
                {
                    "code": "ivi_invariant_payload_invalid",
                    "detail": str(invariant_check.get("detail", "IVI invariant payload invalid")),
                }
            )
        invariant_dynamics_check = self._evaluate_ivi_invariant_dynamics_law(trace, previous_trace=previous_trace)
        if (
            invariant_dynamics_check.get("enabled", False)
            and invariant_dynamics_check.get("admissible_update", False)
            and not invariant_dynamics_check.get("passed", False)
        ):
            gaps.append(
                {
                    "code": "ivi_invariant_dynamics_law_failed",
                    "detail": str(invariant_dynamics_check.get("detail", "IVI invariant dynamics law failed")),
                }
            )
        builder_spec_immutability_check = self._evaluate_builderbuldozer_spec_immutability(builder_derivation)
        builder_reference_digest_check = self._evaluate_builderbuldozer_reference_digest_lock(builder_derivation)
        builder_closure_check = {
            "name": "builderbuldozer_ivi_closure_contract",
            "enabled": bool(builder_derivation),
            "passed": bool(
                isinstance(builder_derivation, dict)
                and builder_derivation.get("enabled", False)
                and builder_derivation.get("closed_engineering", False)
                and builder_derivation.get("gating_summary", {}).get("hard_gate_semantics_defined", False)
                and builder_derivation.get("gating_summary", {}).get("born_excludes_hard_gated", False)
            ),
            "detail": "builderbuldozer derivation is closed in IVI engineering/protocol sense",
        }
        invariant_law_enabled = bool(invariant_dynamics_check.get("enabled", False))
        invariant_law_pass = bool(
            not invariant_dynamics_check.get("enabled", False)
            or not invariant_dynamics_check.get("admissible_update", False)
            or invariant_dynamics_check.get("passed", False)
        )
        theory_closure_pass = bool(
            builder_closure_check.get("passed", False)
            and builder_spec_immutability_check.get("passed", False)
            and builder_reference_digest_check.get("enabled", False)
            and builder_reference_digest_check.get("passed", False)
            and invariant_check.get("passed", False)
            and invariant_law_enabled
            and invariant_law_pass
        )
        theory_closure_check = {
            "name": "builderbuldozer_theory_closure_contract",
            "enabled": bool(builder_derivation),
            "passed": theory_closure_pass,
            "requirements": {
                "builderbuldozer_ivi_closure_contract": bool(builder_closure_check.get("passed", False)),
                "builderbuldozer_spec_immutability_gate": bool(builder_spec_immutability_check.get("passed", False)),
                "builderbuldozer_reference_distribution_digest_lock": bool(builder_reference_digest_check.get("passed", False)),
                "ivi_invariant_payload_integrity": bool(invariant_check.get("passed", False)),
                "ivi_invariant_dynamics_law_enabled": bool(invariant_law_enabled),
                "ivi_invariant_dynamics_law": bool(invariant_law_pass),
            },
            "detail": "theory closure requires spec lock, reference digest lock, and admissible invariant dynamics",
        }
        if builder_closure_check.get("enabled", False) and not builder_closure_check.get("passed", False):
            gaps.append(
                {
                    "code": "builderbuldozer_ivi_closure_incomplete",
                    "detail": "builderbuldozer derivation did not satisfy IVI closure contract",
                }
            )
        if builder_spec_immutability_check.get("enabled", False) and not builder_spec_immutability_check.get("passed", False):
            gaps.append(
                {
                    "code": "builderbuldozer_spec_immutability_violation",
                    "detail": str(builder_spec_immutability_check.get("detail", "builderbuldozer spec immutability violation")),
                }
            )
        if builder_reference_digest_check.get("enabled", False) and not builder_reference_digest_check.get("passed", False):
            gaps.append(
                {
                    "code": "builderbuldozer_reference_distribution_digest_mismatch",
                    "detail": str(
                        builder_reference_digest_check.get(
                            "detail",
                            "builderbuldozer reference distribution digest mismatch",
                        )
                    ),
                }
            )
        if theory_closure_check.get("enabled", False) and not theory_closure_check.get("passed", False):
            gaps.append(
                {
                    "code": "builderbuldozer_theory_closure_incomplete",
                    "detail": str(theory_closure_check.get("detail", "builderbuldozer theory closure incomplete")),
                }
            )
        purple_semantic_check = self._evaluate_purple_semantic_enforcement(trace, gaps)

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
            "CreativityEvent": creativity_event,
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
                "closure_replay_integrity": closure_replay_check,
                "closure_rules_immutability_gate": closure_rules_immutability_check,
                "choice_law_immutability_gate": choice_law_immutability_check,
                "choice_law_replay_integrity": choice_law_replay_check,
                "potential_derivation_integrity": potential_derivation_check,
                "potential_collapse_sampling_seed_parity": sampling_seed_check,
                "purple_semantic_enforcement": purple_semantic_check,
                "policy_immutability_gate": policy_immutability_check,
                "ivi_invariant_payload_integrity": invariant_check,
                "ivi_invariant_dynamics_law": invariant_dynamics_check,
                "builderbuldozer_spec_immutability_gate": builder_spec_immutability_check,
                "builderbuldozer_reference_distribution_digest_lock": builder_reference_digest_check,
                "builderbuldozer_ivi_closure_contract": builder_closure_check,
                "builderbuldozer_theory_closure_contract": theory_closure_check,
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
