import pytest

from ivi_loop.order_mode_selector import (
    ORDER_1_PROJECTION_SAFE,
    ORDER_2_READ_CONTEXT,
    ORDER_3_CONSTRAINED_WRITE,
    ORDER_4_BOUNDED_AUTONOMY,
    PermissionState,
    PolicyState,
    readiness_for_order_3,
    select_order_mode,
)


def _base_checks():
    return {
        "triangle_time_choice_contract": {"enabled": True, "passed": True},
        "policy_immutability_gate": {"enabled": True, "passed": True},
        "ivi_invariant_payload_integrity": {"enabled": True, "passed": True},
        "ivi_invariant_dynamics_law": {"enabled": True, "passed": True},
    }


@pytest.mark.order1
def test_select_order_mode_forces_order1_on_kill_switch():
    mode = select_order_mode(
        trace={},
        state_checks=_base_checks(),
        gaps=[],
        permissions=PermissionState(granted=["R_LOCAL"], requested=[]),
        policy_state=PolicyState(kill_switch=True),
        current_mode=ORDER_3_CONSTRAINED_WRITE,
        max_order_mode=ORDER_4_BOUNDED_AUTONOMY,
    )
    assert mode == ORDER_1_PROJECTION_SAFE


@pytest.mark.order1
def test_select_order_mode_forces_order1_on_invariant_law_failure():
    checks = _base_checks()
    checks["ivi_invariant_dynamics_law"] = {"enabled": True, "passed": False}

    mode = select_order_mode(
        trace={},
        state_checks=checks,
        gaps=[],
        permissions=PermissionState(granted=["R_LOCAL"], requested=[]),
        policy_state=PolicyState(),
    )
    assert mode == ORDER_1_PROJECTION_SAFE


@pytest.mark.order1
def test_select_order_mode_caps_by_max_order_mode():
    perms = PermissionState(
        granted=["R_LOCAL", "W_LOCAL", "R_APP:*", "W_APP:*", "NET_OUTBOUND", "SYS_AUTOMATION"],
        requested=["W_LOCAL", "W_APP:notes"],
        consent_token_valid=True,
    )
    policy = PolicyState(scheduler_enabled=True, autonomy_granted=True, kill_switch_armed=True)

    mode = select_order_mode(
        trace={},
        state_checks=_base_checks(),
        gaps=[],
        permissions=perms,
        policy_state=policy,
        current_mode=ORDER_2_READ_CONTEXT,
        max_order_mode=ORDER_2_READ_CONTEXT,
    )
    assert mode == ORDER_2_READ_CONTEXT


@pytest.mark.order1
def test_select_order_mode_forces_order1_when_purple_semantics_fail():
    mode = select_order_mode(
        trace={},
        state_checks=_base_checks(),
        gaps=[],
        permissions=PermissionState(granted=["R_LOCAL"], requested=[]),
        policy_state=PolicyState(purple_semantic_passed=False),
        current_mode=ORDER_3_CONSTRAINED_WRITE,
        max_order_mode=ORDER_4_BOUNDED_AUTONOMY,
    )
    assert mode == ORDER_1_PROJECTION_SAFE


@pytest.mark.order1
def test_select_order_mode_forces_order1_when_triangle_time_integral_exceeds_limit():
    mode = select_order_mode(
        trace={},
        state_checks=_base_checks(),
        gaps=[],
        permissions=PermissionState(granted=["R_LOCAL"], requested=[]),
        policy_state=PolicyState(
            triangle_time_integral_value=3.0,
            triangle_time_integral_limit=2.5,
        ),
        current_mode=ORDER_3_CONSTRAINED_WRITE,
        max_order_mode=ORDER_4_BOUNDED_AUTONOMY,
    )
    assert mode == ORDER_1_PROJECTION_SAFE


@pytest.mark.order1
def test_select_order_mode_applies_sticky_downgrade_lock():
    perms = PermissionState(
        granted=["R_LOCAL", "W_LOCAL", "R_APP:*", "W_APP:*", "NET_OUTBOUND"],
        requested=["W_LOCAL"],
        consent_token_valid=True,
    )
    policy = PolicyState(
        scheduler_enabled=False,
        autonomy_granted=False,
        kill_switch_armed=True,
        downgrade_lock_until_ts=200.0,
        now_ts=150.0,
    )

    mode = select_order_mode(
        trace={},
        state_checks=_base_checks(),
        gaps=[],
        permissions=perms,
        policy_state=policy,
        current_mode=ORDER_1_PROJECTION_SAFE,
        max_order_mode=ORDER_4_BOUNDED_AUTONOMY,
    )
    assert mode == ORDER_1_PROJECTION_SAFE


@pytest.mark.order1
def test_readiness_for_order3_requires_consent_and_permissions():
    checks = _base_checks()
    denied = PermissionState(
        granted=["R_LOCAL", "R_APP:*"],
        requested=["W_APP:calendar"],
        consent_token_valid=False,
    )
    ok = PermissionState(
        granted=["R_LOCAL", "W_LOCAL", "R_APP:*", "W_APP:*"],
        requested=["W_APP:calendar"],
        consent_token_valid=True,
    )

    assert readiness_for_order_3({}, checks, [], denied) is False
    assert readiness_for_order_3({}, checks, [], ok) is True


@pytest.mark.order1
def test_select_order_mode_downgrades_on_repeated_sandbox_failures():
    mode = select_order_mode(
        trace={},
        state_checks=_base_checks(),
        gaps=[],
        permissions=PermissionState(granted=["R_LOCAL"], requested=[]),
        policy_state=PolicyState(recent_sandbox_failures=4),
        current_mode=ORDER_3_CONSTRAINED_WRITE,
        max_order_mode=ORDER_4_BOUNDED_AUTONOMY,
    )
    assert mode == ORDER_2_READ_CONTEXT
