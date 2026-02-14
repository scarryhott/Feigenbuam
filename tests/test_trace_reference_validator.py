import pytest

from ivi_loop.ivi_simplicial_grid import (
    validate_role_exchange_trace_consistency,
    validate_trace_backed_references,
)


@pytest.mark.order1
def test_validate_trace_backed_references_accepts_trace_grounded_refs():
    trace = {
        "formal_targets": [
            {"eid": "E_alpha", "lean_name": "alpha", "lean_file": "A.lean"},
            {"eid": "E_beta", "lean_name": "beta", "lean_file": "B.lean"},
        ]
    }
    refs = [
        {"eid": "E_alpha", "statement": "s1"},
        {"eid": "E_beta", "statement": "s2"},
    ]

    ok, violations = validate_trace_backed_references(trace, refs)

    assert ok is True
    assert violations == []


@pytest.mark.order1
def test_validate_trace_backed_references_rejects_untraceable_refs():
    trace = {
        "formal_targets": [
            {"eid": "E_alpha", "lean_name": "alpha", "lean_file": "A.lean"},
        ]
    }
    refs = [
        {"eid": "E_alpha", "statement": "grounded"},
        {"eid": "E_unknown", "statement": "not grounded"},
        {"statement": "missing eid"},
    ]

    ok, violations = validate_trace_backed_references(trace, refs)

    assert ok is False
    assert len(violations) == 2
    assert any("E_unknown" in v for v in violations)
    assert any("missing eid" in v for v in violations)


@pytest.mark.order1
def test_validate_role_exchange_trace_consistency_accepts_valid_projection():
    trace = {
        "potential_distribution": [
            {"tid": "T_1", "p": 0.6},
            {"tid": "T_2", "p": 0.4},
        ],
        "collapse_selection": ["T_1", "T_2"],
        "role_projection": {
            "subject_tids": ["T_1"],
            "object_tids": ["T_2"],
        },
    }

    ok, violations = validate_role_exchange_trace_consistency(trace)

    assert ok is True
    assert violations == []


@pytest.mark.order1
def test_validate_role_exchange_trace_consistency_rejects_invalid_projection():
    trace = {
        "potential_distribution": [
            {"tid": "T_1", "p": 0.7},
            {"tid": "T_2", "p": 0.3},
        ],
        "collapse_selection": ["T_1", "T_2"],
        "role_projection": {
            "subject_tids": ["T_1", "T_2"],
            "object_tids": [],
        },
    }

    ok, violations = validate_role_exchange_trace_consistency(trace)

    assert ok is False
    assert any("must populate both subject_tids and object_tids" in v for v in violations)
