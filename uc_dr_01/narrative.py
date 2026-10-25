"""CP-LLM fixture briefing.

v1 does not call a model. Factors must cite an extract field, a gap, or a
fixture indicator. A tier on the draft is ignored. Clearance language is dropped.
The score node does not read this text.
"""

from __future__ import annotations

import re
from typing import Any

from uc_dr_01.completeness import field_citation

_CLEARANCE = re.compile(
    r"auto-?approv|(?:regulatory\s+)?obligation\s+is\s+cleared|"
    r"cleared\s+the\s+(?:regulatory\s+)?obligation|(?:has\s+been|is|was)\s+cleared|"
    r"clears\s+(?:the\s+)?(?:regulatory\s+)?obligation|regulatory\s+clearance",
    re.IGNORECASE,
)

_WITHHELD = (
    "Summary withheld. A grounded briefing may only describe cited fields, gaps, and fixture indicators."
)


def allowed_citations(case_file: dict[str, Any], completeness: dict[str, Any]) -> list[str]:
    cites: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value not in seen:
            seen.add(value)
            cites.append(value)

    for doc in case_file["documents"]:
        for field in doc["fields"]:
            add(field_citation(case_file["caseId"], doc["docId"], field["id"]))
    for gap in completeness["gaps"]:
        add(gap["citationId"])
    if case_file.get("identityConflict"):
        add(f"conflict:{case_file['caseId']}:identity")
    for indicator in case_file.get("elevatedIndicators") or []:
        add(f"indicator:{case_file['caseId']}:{indicator}")
    return cites


def ground_narrative(
    draft: dict[str, Any],
    allowed: list[str],
    source: str,
) -> dict[str, Any]:
    allow = set(allowed)
    dropped = 0
    factors: list[dict[str, Any]] = []
    raw_factors = draft.get("factors")
    if not isinstance(raw_factors, list):
        raw_factors = []

    for index, factor in enumerate(raw_factors, start=1):
        if not isinstance(factor, dict):
            dropped += 1
            continue
        text = factor.get("text")
        text = text.strip() if isinstance(text, str) else ""
        citations = [
            cite
            for cite in (factor.get("citations") or [])
            if isinstance(cite, str) and cite
        ]
        grounded = bool(citations) and all(cite in allow for cite in citations)
        if not text or not grounded or _CLEARANCE.search(text):
            dropped += 1
            continue
        factor_id = factor.get("id")
        if not isinstance(factor_id, str) or not factor_id.strip():
            factor_id = f"RF-{index}"
        factors.append({"id": factor_id.strip(), "text": text, "citations": citations})
        if len(factors) == 8:
            break

    summary = draft.get("summary")
    summary = summary.strip()[:700] if isinstance(summary, str) else ""
    note: str | None = None
    if not summary or _CLEARANCE.search(summary):
        summary = _WITHHELD
        note = "Summary failed the grounding check."
    if "tier" in draft:
        tier_note = "A tier field on the narrative payload was ignored."
        note = f"{note} {tier_note}" if note else tier_note
    if dropped:
        drop_note = (
            f"{dropped} factor(s) dropped because a citation was missing, unknown, "
            "or the text claimed a clearance."
        )
        note = f"{note} {drop_note}" if note else drop_note

    return {
        "summary": summary,
        "factors": factors,
        "source": source,
        "droppedUncited": dropped,
        "note": note,
    }


def fixture_narrative(case_file: dict[str, Any], completeness: dict[str, Any]) -> dict[str, Any]:
    """Build the v1 briefing from the fixture. No model call."""

    allowed = allowed_citations(case_file, completeness)
    draft = dict(case_file.get("fixtureNarrative") or {})
    return ground_narrative(draft, allowed, "fixture")


def suppressed_narrative() -> dict[str, Any]:
    return {
        "summary": "Narrative suppressed. CB-LLM is open, so this packet goes to HITL without a model briefing.",
        "factors": [],
        "source": "suppressed",
        "droppedUncited": 0,
        "note": "CB-LLM degrade: stop the summarize node.",
    }
