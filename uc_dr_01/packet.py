"""Simulated Case/GRC packet.

A soft flag is a non-clearing mark. clearsRegulatoryObligation is fixed false.
Timeout never reaches this builder.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

SOFT_DISPOSITION = "non_clearing_soft_flag"
ANALYST_DISPOSITION = "analyst_accepted_packet"
_DISPOSITIONS = {SOFT_DISPOSITION, ANALYST_DISPOSITION}

# The regulatory obligation flag cannot be switched on. Both packet kinds use this.
CLEARS_REGULATORY_OBLIGATION: Literal[False] = False

_PACKET_LABEL = "Non-clearing flag. This packet does not clear a regulatory obligation."


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_packet(state: dict[str, Any], disposition: str) -> dict[str, Any]:
    """Build a simulated packet. Refuses timeout, quarantine, and a non-policy tier."""

    hitl = state.get("hitl") or {}
    if hitl.get("action") == "timeout" or state.get("phase") == "quarantine" or state.get("quarantine"):
        raise RuntimeError("Timeout and quarantine cannot write a packet or a soft flag.")
    if disposition not in _DISPOSITIONS:
        raise RuntimeError(f"Unknown disposition {disposition!r}.")

    score = state.get("score") or {}
    if score.get("tierSource") != "policy_table":
        raise RuntimeError("Refusing to write a packet whose tier did not come from the policy table.")

    clears_regulatory_obligation: Literal[False] = CLEARS_REGULATORY_OBLIGATION
    if clears_regulatory_obligation is not False:
        raise RuntimeError("clearsRegulatoryObligation is fixed to false.")

    if disposition == SOFT_DISPOSITION:
        if hitl.get("action") not in (None,):
            raise RuntimeError("A soft flag is written only on the policy soft path, never from HITL.")
        if score.get("tier") != "low" or score.get("route") != "soft" or score.get("softPathDisabled"):
            raise RuntimeError("Soft flag refused: the policy table did not route this case to the soft path.")
    if disposition == ANALYST_DISPOSITION:
        if hitl.get("action") != "approve" or hitl.get("analystAcceptedPacket") is not True:
            raise RuntimeError("An analyst packet requires an explicit approve. Timeout is not approve.")

    case_id = state["case_file"]["caseId"]
    run_id = state["run_id"]
    packet = {
        "packetId": f"pkt_{case_id}_{run_id}",
        "auditId": f"aud_{run_id.removeprefix('run_')}",
        "caseId": case_id,
        "runId": run_id,
        "disposition": disposition,
        "clearsRegulatoryObligation": clears_regulatory_obligation,
        "tier": score["tier"],
        "policyRowIds": list(score.get("policyRowIds") or []),
        "tierSource": "policy_table",
        "narrative": state.get("narrative"),
        "analystNote": hitl.get("note"),
        "traceId": state["trace_id"],
        "writtenAt": utc_now(),
        "idempotent": True,
        "simulated": True,
        "label": _PACKET_LABEL,
    }
    if packet["clearsRegulatoryObligation"] is not False:
        raise RuntimeError("Soft flag and analyst packets must not clear a regulatory obligation.")
    if packet["disposition"] == SOFT_DISPOSITION and packet["clearsRegulatoryObligation"] is not False:
        raise RuntimeError("A soft flag never clears a regulatory obligation.")
    return packet


def build_quarantine(reason: str, at: str) -> dict[str, Any]:
    """Record a timeout. approved is fixed false. This is not a packet."""

    approved: Literal[False] = False
    if approved is not False:
        raise RuntimeError("Quarantine cannot be recorded as an approval.")
    return {"at": at, "reason": reason, "approved": approved}
