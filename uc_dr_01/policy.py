"""CP-SCORE. The only place a risk tier is assigned.

Narrative text, model output, and any caller-supplied tier are not inputs.
"""

from __future__ import annotations

from typing import Any, Literal

RiskTier = Literal["low", "medium", "high"]
Route = Literal["soft", "hitl"]

# Frozen interview-demo table. Row order is the match order used by score_case.
POLICY_ROWS: tuple[dict[str, str], ...] = (
    {
        "id": "POL-01",
        "when": "Any file is outside the frozen taxonomy (unknown type).",
        "tier": "high",
        "route": "hitl",
        "control": "CP-CLS",
    },
    {
        "id": "POL-02",
        "when": "Any required field is present with confidence below 0.90.",
        "tier": "high",
        "route": "hitl",
        "control": "CP-EXT",
    },
    {
        "id": "POL-03",
        "when": "The fixture records an identity conflict across documents.",
        "tier": "high",
        "route": "hitl",
        "control": "CP-SCORE",
    },
    {
        "id": "POL-04",
        "when": "The fixture carries an elevated indicator.",
        "tier": "high",
        "route": "hitl",
        "control": "CP-SCORE",
    },
    {
        "id": "POL-05",
        "when": "PACK-v1 required document or field is missing.",
        "tier": "medium",
        "route": "hitl",
        "control": "CP-GAP",
    },
    {
        "id": "POL-06",
        "when": (
            "None of the rows above match: complete pack, no unknown type, "
            "no low-confidence required field, no conflict, no elevated indicator."
        ),
        "tier": "low",
        "route": "soft",
        "control": "CP-SCORE",
    },
)

_TIER_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def score_case(
    *,
    unknown_type_count: int,
    low_confidence_count: int,
    identity_conflict: bool,
    elevated_indicators: list[str],
    complete: bool,
    breakers: list[dict[str, Any]],
    confidence_floor: float,
) -> dict[str, Any]:
    """Return the policy-table tier and route.

    An open breaker can disable the soft path. It never changes the tier and
    never counts as approval.
    """

    matched: list[dict[str, str]] = []
    if unknown_type_count > 0:
        matched.append(
            {
                "id": "POL-01",
                "tier": "high",
                "reason": (
                    f"{unknown_type_count} file(s) sit outside the taxonomy. "
                    "Unknown types go to HITL and are never auto-routed."
                ),
            }
        )
    if low_confidence_count > 0:
        matched.append(
            {
                "id": "POL-02",
                "tier": "high",
                "reason": (
                    f"{low_confidence_count} required field(s) are below the "
                    f"{confidence_floor:.2f} confidence floor. CP-EXT forces HITL."
                ),
            }
        )
    if identity_conflict:
        matched.append(
            {
                "id": "POL-03",
                "tier": "high",
                "reason": "Fixture identity conflict across documents. HITL. The narrative does not choose this tier.",
            }
        )
    if elevated_indicators:
        matched.append(
            {
                "id": "POL-04",
                "tier": "high",
                "reason": (
                    "Fixture elevated indicator(s): "
                    f"{', '.join(elevated_indicators)}. HITL. This is demo data, not a live screening result."
                ),
            }
        )
    if not complete:
        matched.append(
            {
                "id": "POL-05",
                "tier": "medium",
                "reason": "PACK-v1 checklist has at least one missing document or field. Gap list goes to HITL.",
            }
        )

    if not matched:
        tier: RiskTier = "low"
        route: Route = "soft"
        matched.append(
            {
                "id": "POL-06",
                "tier": "low",
                "reason": (
                    "Policy table row POL-06. Low tier and complete pack. "
                    "Soft flag is non-clearing and does not retire a regulatory obligation."
                ),
            }
        )
    else:
        tier = "low"
        for row in matched:
            if _TIER_RANK[row["tier"]] > _TIER_RANK[tier]:
                tier = row["tier"]  # type: ignore[assignment]
        route = "hitl"

    open_breakers = [breaker["id"] for breaker in breakers if breaker.get("state") == "open"]
    soft_path_disabled = bool(open_breakers)
    if route == "soft" and soft_path_disabled:
        route = "hitl"
        verb = "is" if len(open_breakers) == 1 else "are"
        matched.append(
            {
                "id": "ROUTE-BREAKER",
                "tier": tier,
                "reason": (
                    f"Soft auto-path disabled because {', '.join(open_breakers)} {verb} open. "
                    f"Tier stays {tier} from the policy table. Opening a breaker never approves the case."
                ),
            }
        )

    return {
        "tier": tier,
        "route": route,
        "policyRowIds": [row["id"] for row in matched if row["id"].startswith("POL-")],
        "reasons": [f"{row['id']}: {row['reason']}" for row in matched],
        "softPathDisabled": soft_path_disabled,
        "openBreakers": open_breakers,
        "tierSource": "policy_table",
        "narrativeIgnored": True,
    }
