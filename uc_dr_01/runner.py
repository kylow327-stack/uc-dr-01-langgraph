"""Run one fixture case through the compiled graph and return public JSON."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from uc_dr_01.catalog import breaker_states, load_case, load_pack, taxonomy_ids
from uc_dr_01.errors import DemoError
from uc_dr_01.graph import build_graph

HITL_ACTIONS = {"approve", "edit", "reject", "escalate", "timeout"}

_NOTICE = (
    "Fixtures-only interview demo. Not a bank system. "
    "The packet is simulated and does not clear a regulatory obligation."
)


def tracing_mode() -> str:
    flag = os.environ.get("LANGSMITH_TRACING", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return "langsmith_requested"
    return "off"


def _interrupt_value(item: Any) -> dict[str, Any]:
    value = getattr(item, "value", item)
    if isinstance(value, dict):
        return value
    return {"value": value}


def _decision(state: dict[str, Any], packet: dict[str, Any] | None) -> dict[str, Any]:
    score = state.get("score") or {}
    soft_written = bool(packet and packet.get("disposition") == "non_clearing_soft_flag")
    return {
        "tier": score.get("tier"),
        "route": score.get("route"),
        "policyRowIds": list(score.get("policyRowIds") or []),
        "reasons": list(score.get("reasons") or []),
        "tierSource": score.get("tierSource"),
        "narrativeIgnored": score.get("narrativeIgnored"),
        "softPathDisabled": score.get("softPathDisabled"),
        "openBreakers": list(score.get("openBreakers") or []),
        "disposition": None if packet is None else packet.get("disposition"),
        "clearsRegulatoryObligation": False,
        "softFlagWritten": soft_written,
    }


def public_result(
    state: dict[str, Any],
    *,
    phase: str | None = None,
    interrupt_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packet = None if interrupt_payload is not None else state.get("packet")
    completeness = state.get("completeness") or {}
    case_file = state.get("case_file") or {}
    return {
        "notice": _NOTICE,
        "caseId": case_file.get("caseId"),
        "title": case_file.get("title"),
        "profile": case_file.get("profile"),
        "runId": state.get("run_id"),
        "traceId": state.get("trace_id"),
        "tracing": tracing_mode(),
        "phase": phase or state.get("phase"),
        "decision": _decision(state, packet),
        "packet": packet,
        "quarantine": state.get("quarantine"),
        "interrupt": interrupt_payload,
        "gaps": list(completeness.get("gaps") or []),
        "narrative": state.get("narrative"),
        "hitl": state.get("hitl"),
        "securityBridge": state.get("security_bridge"),
        "freeze": state.get("freeze"),
        "nodes": [
            {
                "nodeId": node.get("nodeId"),
                "status": node.get("status"),
                "title": node.get("title"),
                "detail": node.get("detail"),
                "controls": node.get("controls"),
            }
            for node in state.get("nodes") or []
        ],
    }


def initial_state(
    case_file: dict[str, Any],
    *,
    run_id: str,
    breaker_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "case_file": case_file,
        "pack": load_pack(),
        "taxonomy_ids": taxonomy_ids(),
        "breakers": breaker_states(breaker_overrides),
        "run_id": run_id,
        "trace_id": f"demo-{run_id}",
        "phase": "ready",
        "nodes": [],
        "completeness": None,
        "narrative": None,
        "score": None,
        "hitl": {"action": None, "note": None, "at": None, "analystAcceptedPacket": False},
        "packet": None,
        "quarantine": None,
        "disposition": None,
        "security_bridge": None,
        "freeze": None,
    }


def run_case(
    case_file: dict[str, Any],
    *,
    action: str | None = None,
    note: str | None = None,
    breaker_overrides: dict[str, str] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Execute the graph. ``action="timeout"`` resumes a HITL wait into quarantine."""

    if action is not None and action not in HITL_ACTIONS:
        raise DemoError(
            f"Unrecognized HITL action {action!r}. Nothing was approved and no soft flag was written."
        )
    run_id = run_id or f"run_{case_file['caseId']}_{uuid4().hex[:8]}"
    graph = build_graph()
    config = {"configurable": {"thread_id": run_id}}
    result = graph.invoke(initial_state(case_file, run_id=run_id, breaker_overrides=breaker_overrides), config)
    interrupts = list(result.get("__interrupt__") or [])
    if interrupts:
        if action is None:
            return public_result(result, phase="hitl_waiting", interrupt_payload=_interrupt_value(interrupts[0]))
        resumed = graph.invoke(Command(resume={"action": action, "note": note}), config)
        if resumed.get("__interrupt__"):
            raise DemoError("HITL resume did not leave the interrupt. Nothing was approved.", exit_code=2)
        return public_result(resumed)
    if action is not None:
        raise DemoError(
            "That HITL action applies only when the run is waiting at the interrupt. "
            f"This run ended in phase {result.get('phase')!r}, so nothing was quarantined and nothing was approved.",
            exit_code=2,
        )
    return public_result(result)


def run_named_case(case_id: str, **kwargs: Any) -> dict[str, Any]:
    return run_case(load_case(case_id), **kwargs)
