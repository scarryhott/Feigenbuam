from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Iterable, List, Optional, Sequence, Set


ORDER_1_PROJECTION_SAFE = "order_1_projection_safe"
ORDER_2_READ_CONTEXT = "order_2_read_context"
ORDER_3_CONSTRAINED_WRITE = "order_3_constrained_write"
ORDER_4_BOUNDED_AUTONOMY = "order_4_bounded_autonomy"

ORDER_MODE_SEQUENCE = [
    ORDER_1_PROJECTION_SAFE,
    ORDER_2_READ_CONTEXT,
    ORDER_3_CONSTRAINED_WRITE,
    ORDER_4_BOUNDED_AUTONOMY,
]

_MODE_RANK = {mode: idx for idx, mode in enumerate(ORDER_MODE_SEQUENCE)}

HIGH_SEVERITY_GAP_CODES = {
    "ivi_invariant_dynamics_law_failed",
    "builderbuldozer_theory_closure_incomplete",
    "builderbuldozer_reference_distribution_digest_mismatch",
    "policy_immutability_violation",
}


MODE_PERMISSION_MATRIX: Dict[str, Dict[str, object]] = {
    ORDER_1_PROJECTION_SAFE: {
        "permissions_allowed": ["R_LOCAL"],
        "mutations_allowed": False,
        "autonomy_allowed": False,
    },
    ORDER_2_READ_CONTEXT: {
        "permissions_allowed": ["R_LOCAL", "R_APP:*", "NET_OUTBOUND"],
        "mutations_allowed": False,
        "autonomy_allowed": False,
    },
    ORDER_3_CONSTRAINED_WRITE: {
        "permissions_allowed": ["R_LOCAL", "W_LOCAL", "R_APP:*", "W_APP:*", "NET_OUTBOUND"],
        "mutations_allowed": True,
        "consent_required": True,
        "autonomy_allowed": False,
    },
    ORDER_4_BOUNDED_AUTONOMY: {
        "permissions_allowed": ["R_LOCAL", "W_LOCAL", "R_APP:*", "W_APP:*", "NET_OUTBOUND", "SYS_AUTOMATION"],
        "mutations_allowed": True,
        "consent_required": True,
        "autonomy_allowed": True,
        "schedule_required": True,
        "kill_switch_required": True,
    },
}


@dataclass(frozen=True)
class PolicyState:
    kill_switch: bool = False
    recent_sandbox_failures: int = 0
    scheduler_enabled: bool = False
    autonomy_granted: bool = False
    kill_switch_armed: bool = False
    triangle_time_integral_value: float = 0.0
    triangle_time_integral_limit: float = 2.5
    purple_semantic_passed: bool = True
    downgrade_lock_until_ts: Optional[float] = None
    now_ts: Optional[float] = None


@dataclass(frozen=True)
class PermissionState:
    granted: Sequence[str]
    requested: Sequence[str]
    consent_token_valid: bool = False


def _mode_rank(mode: str) -> int:
    return _MODE_RANK.get(str(mode), 0)


def min_mode(a: str, b: str) -> str:
    return a if _mode_rank(a) <= _mode_rank(b) else b


def max_mode(a: str, b: str) -> str:
    return a if _mode_rank(a) >= _mode_rank(b) else b


def cap_mode(candidate: str, ceiling: str) -> str:
    return min_mode(candidate, ceiling)


def _normalize_perms(perms: Iterable[str]) -> Set[str]:
    out = set()
    for raw in perms:
        token = str(raw).strip()
        if token:
            out.add(token)
    return out


def _perm_granted(required: str, granted: Set[str]) -> bool:
    req = str(required).strip()
    if not req:
        return True
    if req in granted:
        return True
    if ":" in req:
        prefix, _ = req.split(":", 1)
        wildcard = f"{prefix}:*"
        if wildcard in granted:
            return True
    return False


def _triangle_time_integral_ok(policy_state: PolicyState) -> bool:
    value = float(policy_state.triangle_time_integral_value)
    limit = float(max(1e-9, policy_state.triangle_time_integral_limit))
    if not math.isfinite(value):
        return False
    return abs(value) <= limit


def has_permissions(required: Sequence[str], granted: Sequence[str]) -> bool:
    granted_set = _normalize_perms(granted)
    return all(_perm_granted(req, granted_set) for req in required)


def has_high_severity_gaps(gaps: Sequence[Dict[str, str]]) -> bool:
    for g in gaps:
        if not isinstance(g, dict):
            continue
        code = str(g.get("code", "")).strip()
        if code in HIGH_SEVERITY_GAP_CODES:
            return True
    return False


def _critical_checks_ok(state_checks: Dict[str, Dict[str, object]]) -> bool:
    checks = state_checks if isinstance(state_checks, dict) else {}
    critical = [
        "triangle_time_choice_contract",
        "policy_immutability_gate",
        "ivi_invariant_payload_integrity",
    ]
    for name in critical:
        ch = checks.get(name, {}) if isinstance(checks.get(name, {}), dict) else {}
        if bool(ch.get("enabled", False)) and not bool(ch.get("passed", False)):
            return False
    return True


def readiness_for_order_2(
    trace: Dict[str, object],
    state_checks: Dict[str, Dict[str, object]],
    gaps: Sequence[Dict[str, str]],
) -> bool:
    _ = trace
    if has_high_severity_gaps(gaps):
        return False
    if not _critical_checks_ok(state_checks):
        return False
    dynamics = state_checks.get("ivi_invariant_dynamics_law", {}) if isinstance(state_checks, dict) else {}
    if bool(dynamics.get("enabled", False)) and not bool(dynamics.get("passed", False)):
        return False
    return True


def readiness_for_order_3(
    trace: Dict[str, object],
    state_checks: Dict[str, Dict[str, object]],
    gaps: Sequence[Dict[str, str]],
    permissions: PermissionState,
) -> bool:
    if not readiness_for_order_2(trace, state_checks, gaps):
        return False
    if not permissions.consent_token_valid:
        return False
    return has_permissions(permissions.requested, permissions.granted)


def readiness_for_order_4(
    trace: Dict[str, object],
    state_checks: Dict[str, Dict[str, object]],
    gaps: Sequence[Dict[str, str]],
    permissions: PermissionState,
    policy_state: PolicyState,
) -> bool:
    if not readiness_for_order_3(trace, state_checks, gaps, permissions):
        return False
    if not bool(policy_state.purple_semantic_passed):
        return False
    if not _triangle_time_integral_ok(policy_state):
        return False
    if not policy_state.scheduler_enabled:
        return False
    if not policy_state.autonomy_granted:
        return False
    if not policy_state.kill_switch_armed:
        return False
    return True


def select_order_mode(
    trace: Dict[str, object],
    state_checks: Dict[str, Dict[str, object]],
    gaps: Sequence[Dict[str, str]],
    permissions: PermissionState,
    policy_state: PolicyState,
    current_mode: str = ORDER_1_PROJECTION_SAFE,
    max_order_mode: str = ORDER_4_BOUNDED_AUTONOMY,
) -> str:
    if policy_state.kill_switch:
        return ORDER_1_PROJECTION_SAFE
    if not bool(policy_state.purple_semantic_passed):
        return ORDER_1_PROJECTION_SAFE
    if not _triangle_time_integral_ok(policy_state):
        return ORDER_1_PROJECTION_SAFE

    dynamics = state_checks.get("ivi_invariant_dynamics_law", {}) if isinstance(state_checks, dict) else {}
    if bool(dynamics.get("enabled", False)) and not bool(dynamics.get("passed", False)):
        return ORDER_1_PROJECTION_SAFE

    if int(policy_state.recent_sandbox_failures) >= 3:
        return cap_mode(ORDER_2_READ_CONTEXT, max_order_mode)

    candidate = ORDER_1_PROJECTION_SAFE
    if readiness_for_order_2(trace, state_checks, gaps):
        candidate = ORDER_2_READ_CONTEXT
    if readiness_for_order_3(trace, state_checks, gaps, permissions):
        candidate = ORDER_3_CONSTRAINED_WRITE
    if readiness_for_order_4(trace, state_checks, gaps, permissions, policy_state):
        candidate = ORDER_4_BOUNDED_AUTONOMY

    candidate = cap_mode(candidate, max_order_mode)

    if policy_state.downgrade_lock_until_ts is not None and policy_state.now_ts is not None:
        if float(policy_state.now_ts) < float(policy_state.downgrade_lock_until_ts):
            return min_mode(current_mode, candidate)

    return candidate
