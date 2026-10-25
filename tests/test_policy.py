import inspect

from uc_dr_01.policy import POLICY_ROWS, score_case


def _breakers(open_ids: set[str] | None = None) -> list[dict[str, str]]:
    open_ids = open_ids or set()
    rows = []
    for breaker_id, default in (
        ("CB-EXTRACT", "closed"),
        ("CB-LLM", "closed"),
        ("CB-CONFIDENCE", "half-open"),
        ("CB-HITL-BACKLOG", "closed"),
        ("CB-CASE-WRITE", "closed"),
        ("CB-DATA-EGRESS", "closed"),
    ):
        rows.append({"id": breaker_id, "state": "open" if breaker_id in open_ids else default})
    return rows


def _score(**overrides):
    payload = {
        "unknown_type_count": 0,
        "low_confidence_count": 0,
        "identity_conflict": False,
        "elevated_indicators": [],
        "complete": True,
        "breakers": _breakers(),
        "confidence_floor": 0.9,
    }
    payload.update(overrides)
    return score_case(**payload)


def test_policy_table_ids_and_soft_row():
    assert [row["id"] for row in POLICY_ROWS] == [
        "POL-01",
        "POL-02",
        "POL-03",
        "POL-04",
        "POL-05",
        "POL-06",
    ]
    assert POLICY_ROWS[-1]["tier"] == "low"
    assert POLICY_ROWS[-1]["route"] == "soft"


def test_scorer_does_not_accept_narrative():
    params = set(inspect.signature(score_case).parameters)
    assert "narrative" not in params
    assert "summary" not in params
    assert "tier" not in params


def test_clean_pack_is_low_soft_while_confidence_breaker_is_half_open():
    score = _score()
    assert score["tier"] == "low"
    assert score["route"] == "soft"
    assert score["policyRowIds"] == ["POL-06"]
    assert score["tierSource"] == "policy_table"
    assert score["narrativeIgnored"] is True
    assert score["softPathDisabled"] is False
    assert score["openBreakers"] == []


def test_open_breaker_does_not_change_tier_and_disables_soft_path():
    score = _score(breakers=_breakers({"CB-CASE-WRITE"}))
    assert score["tier"] == "low"
    assert score["route"] == "hitl"
    assert score["softPathDisabled"] is True
    assert score["openBreakers"] == ["CB-CASE-WRITE"]
    assert score["policyRowIds"] == ["POL-06"]


def test_highest_matching_tier_is_high_and_never_soft():
    score = _score(
        complete=False,
        low_confidence_count=1,
        identity_conflict=True,
        unknown_type_count=1,
        elevated_indicators=["fixture-elevated-indicator"],
    )
    assert score["tier"] == "high"
    assert score["route"] == "hitl"
    assert score["policyRowIds"] == ["POL-01", "POL-02", "POL-03", "POL-04", "POL-05"]


def test_plain_gap_stays_medium():
    score = _score(complete=False)
    assert score["tier"] == "medium"
    assert score["route"] == "hitl"
    assert score["policyRowIds"] == ["POL-05"]
