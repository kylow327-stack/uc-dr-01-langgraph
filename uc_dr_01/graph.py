"""LangGraph for the UC-DR-01 fixture demo.

Hard rules encoded in the edges and node bodies:

1. The soft path writes disposition ``non_clearing_soft_flag`` and
   ``clearsRegulatoryObligation`` is false. ``build_packet`` refuses anything else.
2. HITL timeout goes to the ``quarantine`` node. That node sets ``approved``
   false, clears any packet, and has no edge to ``write_case_packet`` or
   ``auto_flag_soft``. An unknown resume value raises instead of approving.
3. ``score_and_route`` calls ``score_case`` only. It does not read the narrative.

v1 extract and summary nodes validate fixture data. They do not call a model.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from uc_dr_01.completeness import check_completeness, field_citation, intake_allows
from uc_dr_01.narrative import fixture_narrative, suppressed_narrative
from uc_dr_01.packet import (
    ANALYST_DISPOSITION,
    SOFT_DISPOSITION,
    build_packet,
    build_quarantine,
    utc_now,
)
from uc_dr_01.policy import score_case

_STOP = {"killed", "rejected", "paused", "frozen"}
_HITL_ACTIONS = {"approve", "edit", "reject", "escalate", "timeout"}
_QUARANTINE_REASON = (
    "Analyst timeout. The case is in quarantine. This is not an approval and no soft flag was written."
)


class GraphState(TypedDict):
    case_file: dict[str, Any]
    pack: dict[str, Any]
    taxonomy_ids: list[str]
    breakers: list[dict[str, Any]]
    run_id: str
    trace_id: str
    phase: str
    nodes: list[dict[str, Any]]
    completeness: dict[str, Any] | None
    narrative: dict[str, Any] | None
    score: dict[str, Any] | None
    hitl: dict[str, Any]
    packet: dict[str, Any] | None
    quarantine: dict[str, Any] | None
    disposition: str | None
    security_bridge: dict[str, Any] | None
    freeze: dict[str, Any] | None


def _breaker(state: GraphState, breaker_id: str) -> str:
    for breaker in state["breakers"]:
        if breaker["id"] == breaker_id:
            return str(breaker["state"])
    return "closed"


def _append(state: GraphState, record: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [dict(node) for node in state.get("nodes") or []]
    record.setdefault("at", utc_now())
    nodes.append(record)
    return nodes


def _upsert(state: GraphState, record: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [dict(node) for node in state.get("nodes") or []]
    record.setdefault("at", utc_now())
    for index, node in enumerate(nodes):
        if node.get("nodeId") == record["nodeId"]:
            nodes[index] = record
            return nodes
    nodes.append(record)
    return nodes


def _halt_if_egress(state: GraphState) -> dict[str, Any] | None:
    if _breaker(state, "CB-DATA-EGRESS") != "open":
        return None
    reason = "CB-DATA-EGRESS is open. Run killed. Security incident bridge opened (simulated). No SoR write."
    at = utc_now()
    return {
        "phase": "killed",
        "packet": None,
        "disposition": None,
        "security_bridge": {"opened": True, "reason": reason, "at": at},
        "nodes": _append(
            state,
            {
                "nodeId": "egress_kill",
                "controls": ["CP-NET", "CB-DATA-EGRESS"],
                "status": "killed",
                "title": "Egress kill",
                "detail": reason,
                "payload": {"kind": "killed", "reason": reason},
                "at": at,
            },
        ),
    }


def _route_stop(state: GraphState, ok: str) -> str:
    if state.get("phase") in _STOP:
        return END
    return ok


def intake_folder(state: GraphState) -> dict[str, Any]:
    killed = _halt_if_egress(state)
    if killed:
        return killed
    folder = state["case_file"]["folderPath"]
    allow_prefix = state["pack"]["allowPrefix"]
    accepted = intake_allows(folder, allow_prefix)
    at = utc_now()
    if accepted:
        detail = f"Folder {folder} is inside the v1 allow-list. Named folders only."
        status = "passed"
        phase = "in_progress"
    else:
        detail = f"Folder {folder} is outside {allow_prefix}. Run rejected."
        status = "failed"
        phase = "rejected"
    return {
        "phase": phase,
        "nodes": _append(
            state,
            {
                "nodeId": "intake_folder",
                "controls": ["CP-INTAKE"],
                "status": status,
                "title": "Intake folder",
                "detail": detail,
                "payload": {
                    "kind": "intake",
                    "folderPath": folder,
                    "allowPrefix": allow_prefix,
                    "accepted": accepted,
                },
                "at": at,
            },
        ),
    }


def classify_doc_type(state: GraphState) -> dict[str, Any]:
    killed = _halt_if_egress(state)
    if killed:
        return killed
    taxonomy = set(state["taxonomy_ids"])
    documents = []
    for doc in state["case_file"]["documents"]:
        classified = doc["classifiedType"]
        documents.append(
            {
                "docId": doc["docId"],
                "fileName": doc["fileName"],
                "classifiedType": classified,
                "inTaxonomy": classified in taxonomy and classified != "unknown",
            }
        )
    unknown = [doc for doc in documents if not doc["inTaxonomy"]]
    if unknown:
        detail = f"{len(unknown)} file(s) are outside TAX-v1. They will force HITL at CP-SCORE."
        status = "attention"
    else:
        detail = "Every file maps to the frozen taxonomy."
        status = "passed"
    return {
        "phase": "in_progress",
        "nodes": _append(
            state,
            {
                "nodeId": "classify_doc_type",
                "controls": ["CP-CLS"],
                "status": status,
                "title": "Classify document type",
                "detail": detail,
                "payload": {"kind": "classify", "documents": documents},
            },
        ),
    }


def extract_fields(state: GraphState) -> dict[str, Any]:
    """Validate the fixture extract. v1 does not call a model or OCR service."""

    killed = _halt_if_egress(state)
    if killed:
        return killed
    if _breaker(state, "CB-EXTRACT") == "open":
        reason = (
            "CB-EXTRACT is open. Extract is paused and files stay queued. "
            "Nothing is approved."
        )
        return {
            "phase": "paused",
            "packet": None,
            "nodes": _append(
                state,
                {
                    "nodeId": "extract_fields",
                    "controls": ["CP-EXT", "CB-EXTRACT"],
                    "status": "paused",
                    "title": "Extract paused",
                    "detail": reason,
                    "payload": {"kind": "extract", "paused": True},
                },
            ),
        }

    floor = float(state["pack"]["confidenceFloor"])
    case_id = state["case_file"]["caseId"]
    below: list[dict[str, Any]] = []
    documents = []
    for doc in state["case_file"]["documents"]:
        fields = []
        for field in doc["fields"]:
            citation = field_citation(case_id, doc["docId"], field["id"])
            under = float(field["confidence"]) < floor
            if under:
                below.append(
                    {
                        "citationId": citation,
                        "label": field["label"],
                        "confidence": field["confidence"],
                    }
                )
            fields.append(
                {
                    "citationId": citation,
                    "label": field["label"],
                    "value": field["value"],
                    "confidence": field["confidence"],
                    "page": field["page"],
                    "belowFloor": under,
                }
            )
        documents.append(
            {
                "docId": doc["docId"],
                "fileName": doc["fileName"],
                "classifiedType": doc["classifiedType"],
                "fields": fields,
            }
        )
    if below:
        detail = f"{len(below)} field(s) are below {floor:.2f}. CP-EXT will force HITL."
        status = "attention"
    else:
        detail = f"Fixture fields are at or above {floor:.2f}. Extract was validated, not inferred."
        status = "passed"
    return {
        "phase": "in_progress",
        "nodes": _append(
            state,
            {
                "nodeId": "extract_fields",
                "controls": ["CP-EXT"],
                "status": status,
                "title": "Extract fields",
                "detail": detail,
                "payload": {
                    "kind": "extract",
                    "confidenceFloor": floor,
                    "belowFloor": below,
                    "documents": documents,
                },
            },
        ),
    }


def completeness_check(state: GraphState) -> dict[str, Any]:
    killed = _halt_if_egress(state)
    if killed:
        return killed
    result = check_completeness(state["case_file"], state["pack"], state["taxonomy_ids"])
    if result["complete"]:
        detail = f"{state['pack']['packId']} {result['profile']} checklist matched. Rules were read from the pack file."
        status = "passed"
    else:
        detail = f"{len(result['gaps'])} gap(s) against {state['pack']['packId']}. The checklist is data, outside the model."
        status = "attention"
    return {
        "phase": "in_progress",
        "completeness": result,
        "nodes": _append(
            state,
            {
                "nodeId": "completeness_check",
                "controls": ["CP-GAP", "CP-HOOK"],
                "status": status,
                "title": "Completeness check",
                "detail": detail,
                "payload": {"kind": "completeness", "result": result},
            },
        ),
    }


def risk_summarize(state: GraphState) -> dict[str, Any]:
    """Fixture briefing only. This node does not set a tier."""

    killed = _halt_if_egress(state)
    if killed:
        return killed
    completeness = state["completeness"] or check_completeness(
        state["case_file"], state["pack"], state["taxonomy_ids"]
    )
    if _breaker(state, "CB-LLM") == "open":
        narrative = suppressed_narrative()
        status = "attention"
        detail = "CB-LLM is open. No narrative was drafted. Tier is still unset here."
    else:
        narrative = fixture_narrative(state["case_file"], completeness)
        status = "passed"
        detail = (
            f"Source: {narrative['source']}. {len(narrative['factors'])} grounded factor(s). "
            f"{narrative['droppedUncited']} dropped. This node does not set the tier."
        )
    return {
        "phase": "in_progress",
        "narrative": narrative,
        "completeness": completeness,
        "nodes": _append(
            state,
            {
                "nodeId": "risk_summarize",
                "controls": ["CP-LLM"],
                "status": status,
                "title": "Grounded summary",
                "detail": detail,
                "payload": {"kind": "summary", "narrative": narrative},
            },
        ),
    }


def score_and_route(state: GraphState) -> dict[str, Any]:
    """Assign tier from the policy table. The narrative on state is not read."""

    killed = _halt_if_egress(state)
    if killed:
        return killed
    completeness = state.get("completeness")
    if not completeness:
        raise RuntimeError("score_and_route requires the completeness check.")
    score = score_case(
        unknown_type_count=len(completeness["unknownTypes"]),
        low_confidence_count=len(completeness["lowConfidenceFields"]),
        identity_conflict=bool(state["case_file"].get("identityConflict")),
        elevated_indicators=list(state["case_file"].get("elevatedIndicators") or []),
        complete=bool(completeness["complete"]),
        breakers=state["breakers"],
        confidence_floor=float(state["pack"]["confidenceFloor"]),
    )
    ids = ", ".join(score["policyRowIds"]) or "policy table"
    return {
        "phase": "in_progress",
        "score": score,
        "nodes": _append(
            state,
            {
                "nodeId": "score_and_route",
                "controls": ["CP-SCORE"],
                "status": "passed",
                "title": "Score and route",
                "detail": f"Tier {score['tier']} from {ids}. Route {score['route']}. Narrative was not an input.",
                "payload": {"kind": "score", "score": score},
            },
        ),
    }


def auto_flag_soft(state: GraphState) -> dict[str, Any]:
    """Mark the soft path. The packet writer still has to enforce the non-clearing flag."""

    killed = _halt_if_egress(state)
    if killed:
        return killed
    score = state.get("score") or {}
    if score.get("route") != "soft" or score.get("tier") != "low" or score.get("tierSource") != "policy_table":
        raise RuntimeError("Soft flag refused: the policy table did not route this case to low / soft.")
    if score.get("softPathDisabled"):
        raise RuntimeError("Soft flag refused: an open breaker disabled the soft path.")
    return {
        "phase": "soft_pending",
        "disposition": SOFT_DISPOSITION,
        "packet": None,
        "nodes": _append(
            state,
            {
                "nodeId": "auto_flag_soft",
                "controls": ["CP-SCORE", "CP-CASE"],
                "status": "passed",
                "title": "Soft flag",
                "detail": (
                    "Low and complete, every breaker that gates the soft path is closed. "
                    "Non-clearing flag only. The regulatory obligation is unchanged."
                ),
                "payload": {
                    "kind": "soft",
                    "disposition": SOFT_DISPOSITION,
                    "clearsRegulatoryObligation": False,
                },
            },
        ),
    }


def hitl_interrupt(state: GraphState) -> dict[str, Any]:
    """Commit the waiting record before the graph pauses."""

    killed = _halt_if_egress(state)
    if killed:
        return killed
    reasons = list((state.get("score") or {}).get("reasons") or [])
    return {
        "phase": "hitl_waiting",
        "packet": None,
        "disposition": None,
        "nodes": _append(
            state,
            {
                "nodeId": "hitl_interrupt",
                "controls": ["CP-HITL"],
                "status": "waiting",
                "title": "HITL interrupt",
                "detail": "Waiting for approve, edit, reject, or escalate. Timeout quarantines and does not approve.",
                "payload": {"kind": "hitl", "reasons": reasons, "approved": False},
            },
        ),
    }


def await_hitl(state: GraphState) -> dict[str, Any]:
    """Pause for a human decision. Timeout is never treated as approve."""

    score = state.get("score") or {}
    completeness = state.get("completeness") or {}
    decision = interrupt(
        {
            "kind": "hitl",
            "caseId": state["case_file"]["caseId"],
            "tier": score.get("tier"),
            "policyRowIds": score.get("policyRowIds") or [],
            "tierSource": "policy_table",
            "reasons": score.get("reasons") or [],
            "gaps": completeness.get("gaps") or [],
            "allowedActions": ["approve", "edit", "reject", "escalate", "timeout"],
            "timeoutEffect": "quarantine",
            "approved": False,
            "message": (
                "Waiting at the human gate. Timeout quarantines the case and does not approve. "
                "A soft flag is not written."
            ),
        }
    )
    if not isinstance(decision, dict):
        raise RuntimeError("HITL resume must be an object with an action. Nothing was approved.")
    action = decision.get("action")
    if action not in _HITL_ACTIONS:
        raise RuntimeError(
            f"Unrecognized HITL action {action!r}. Nothing was approved and no soft flag was written."
        )
    note = decision.get("note")
    if isinstance(note, str):
        note = note.strip()[:1000] or None
    else:
        note = None
    at = utc_now()
    hitl = {
        "action": action,
        "note": note if note is not None else state["hitl"].get("note"),
        "at": at,
        "analystAcceptedPacket": False,
    }

    if action == "timeout":
        return {
            "phase": "timeout_pending",
            "packet": None,
            "disposition": None,
            "hitl": hitl,
            "nodes": _upsert(
                state,
                {
                    "nodeId": "hitl_interrupt",
                    "controls": ["CP-HITL"],
                    "status": "attention",
                    "title": "HITL timeout",
                    "detail": "Timeout is not an approval. Routing to quarantine. No soft flag is written.",
                    "payload": {"kind": "hitl", "action": "timeout", "approved": False},
                    "at": at,
                },
            ),
        }

    if action == "edit":
        return {
            "phase": "edited",
            "packet": None,
            "disposition": None,
            "hitl": hitl,
            "nodes": _upsert(
                state,
                {
                    "nodeId": "hitl_interrupt",
                    "controls": ["CP-HITL"],
                    "status": "passed",
                    "title": "HITL edit",
                    "detail": "Edit stores the note. It does not write a packet and it does not approve.",
                    "payload": {"kind": "hitl", "action": "edit", "approved": False},
                    "at": at,
                },
            ),
        }

    if action == "reject":
        return {
            "phase": "rejected",
            "packet": None,
            "disposition": None,
            "hitl": hitl,
            "nodes": _upsert(
                state,
                {
                    "nodeId": "hitl_interrupt",
                    "controls": ["CP-HITL"],
                    "status": "passed",
                    "title": "HITL rejected",
                    "detail": "Analyst rejected the packet. No SoR flag was written. The obligation is unchanged.",
                    "payload": {"kind": "hitl", "action": "reject", "approved": False},
                    "at": at,
                },
            ),
        }

    if action == "escalate":
        return {
            "phase": "escalated",
            "packet": None,
            "disposition": None,
            "hitl": hitl,
            "nodes": _upsert(
                state,
                {
                    "nodeId": "hitl_interrupt",
                    "controls": ["CP-HITL"],
                    "status": "passed",
                    "title": "Escalated",
                    "detail": "Escalated to the Risk Ops lead queue (simulated). Not written. Not an approval.",
                    "payload": {"kind": "hitl", "action": "escalate", "approved": False},
                    "at": at,
                },
            ),
        }

    if _breaker(state, "CB-CASE-WRITE") == "open":
        reason = "CB-CASE-WRITE is open. Completions are frozen. The packet was not written and the case was not approved."
        nodes = _upsert(
            state,
            {
                "nodeId": "hitl_interrupt",
                "controls": ["CP-HITL"],
                "status": "attention",
                "title": "Approve frozen",
                "detail": reason,
                "payload": {"kind": "hitl", "action": "approve", "approved": False},
                "at": at,
            },
        )
        nodes.append(
            {
                "nodeId": "write_case_packet",
                "controls": ["CP-CASE", "CB-CASE-WRITE"],
                "status": "paused",
                "title": "Write frozen",
                "detail": reason,
                "payload": {"kind": "frozen", "reason": reason, "written": False},
                "at": at,
            }
        )
        return {
            "phase": "frozen",
            "packet": None,
            "disposition": None,
            "freeze": {"at": at, "reason": reason, "written": False},
            "hitl": hitl,
            "nodes": nodes,
        }

    hitl["analystAcceptedPacket"] = True
    return {
        "phase": "approve_pending",
        "disposition": ANALYST_DISPOSITION,
        "packet": None,
        "hitl": hitl,
        "nodes": _upsert(
            state,
            {
                "nodeId": "hitl_interrupt",
                "controls": ["CP-HITL"],
                "status": "passed",
                "title": "Analyst accepted the packet",
                "detail": "Analyst acceptance records the flag packet. It does not clear a regulatory obligation.",
                "payload": {"kind": "hitl", "action": "approve", "approved": False},
                "at": at,
            },
        ),
    }


def quarantine(state: GraphState) -> dict[str, Any]:
    """Terminal timeout path. Never writes a soft flag and never sets approved true."""

    if (state.get("hitl") or {}).get("action") != "timeout":
        raise RuntimeError("Quarantine is only reachable from an HITL timeout.")
    if state.get("packet") is not None:
        raise RuntimeError("Quarantine cannot keep a packet or a soft flag.")
    at = utc_now()
    record = build_quarantine(_QUARANTINE_REASON, at)
    hitl = dict(state.get("hitl") or {})
    hitl["action"] = "timeout"
    hitl["analystAcceptedPacket"] = False
    return {
        "phase": "quarantine",
        "quarantine": record,
        "packet": None,
        "disposition": None,
        "hitl": hitl,
        "nodes": _append(
            state,
            {
                "nodeId": "quarantine",
                "controls": ["CP-HITL"],
                "status": "attention",
                "title": "Quarantine",
                "detail": _QUARANTINE_REASON,
                "payload": {"kind": "quarantine", "approved": False, "softFlagWritten": False},
                "at": at,
            },
        ),
    }


def write_case_packet(state: GraphState) -> dict[str, Any]:
    killed = _halt_if_egress(state)
    if killed:
        return killed
    disposition = state.get("disposition")
    if not isinstance(disposition, str):
        raise RuntimeError("Packet write requires an explicit disposition.")
    packet = build_packet(state, disposition)
    phase: Literal["soft_written", "packet_written"] = (
        "soft_written" if disposition == SOFT_DISPOSITION else "packet_written"
    )
    return {
        "phase": phase,
        "packet": packet,
        "nodes": _append(
            state,
            {
                "nodeId": "write_case_packet",
                "controls": ["CP-CASE"],
                "status": "passed",
                "title": "Simulated SoR write",
                "detail": (
                    f"{packet['disposition']}. Idempotent packet {packet['packetId']}. "
                    "clearsRegulatoryObligation is false."
                ),
                "payload": {
                    "kind": "write",
                    "packetId": packet["packetId"],
                    "disposition": packet["disposition"],
                    "clearsRegulatoryObligation": False,
                },
            },
        ),
    }


def _route_after_score(state: GraphState) -> str:
    if state.get("phase") in _STOP:
        return END
    if (state.get("score") or {}).get("route") == "soft":
        return "auto_flag_soft"
    return "hitl_interrupt"


def _route_after_soft(state: GraphState) -> str:
    if state.get("phase") in _STOP or state.get("disposition") != SOFT_DISPOSITION:
        return END
    return "write_case_packet"


def _route_after_await(state: GraphState) -> str:
    if state.get("phase") in _STOP:
        return END
    action = (state.get("hitl") or {}).get("action")
    if action == "timeout":
        return "quarantine"
    if action == "approve" and state.get("disposition") == ANALYST_DISPOSITION:
        return "write_case_packet"
    return END


def build_graph():
    """Compile the demo graph with an in-memory checkpointer (required for HITL interrupt)."""

    builder = StateGraph(GraphState)
    builder.add_node("intake_folder", intake_folder)
    builder.add_node("classify_doc_type", classify_doc_type)
    builder.add_node("extract_fields", extract_fields)
    builder.add_node("completeness_check", completeness_check)
    builder.add_node("risk_summarize", risk_summarize)
    builder.add_node("score_and_route", score_and_route)
    builder.add_node("auto_flag_soft", auto_flag_soft)
    builder.add_node("hitl_interrupt", hitl_interrupt)
    builder.add_node("await_hitl", await_hitl)
    builder.add_node("quarantine", quarantine)
    builder.add_node("write_case_packet", write_case_packet)

    builder.add_edge(START, "intake_folder")
    builder.add_conditional_edges(
        "intake_folder",
        lambda state: _route_stop(state, "classify_doc_type"),
        {"classify_doc_type": "classify_doc_type", END: END},
    )
    builder.add_conditional_edges(
        "classify_doc_type",
        lambda state: _route_stop(state, "extract_fields"),
        {"extract_fields": "extract_fields", END: END},
    )
    builder.add_conditional_edges(
        "extract_fields",
        lambda state: _route_stop(state, "completeness_check"),
        {"completeness_check": "completeness_check", END: END},
    )
    builder.add_conditional_edges(
        "completeness_check",
        lambda state: _route_stop(state, "risk_summarize"),
        {"risk_summarize": "risk_summarize", END: END},
    )
    builder.add_conditional_edges(
        "risk_summarize",
        lambda state: _route_stop(state, "score_and_route"),
        {"score_and_route": "score_and_route", END: END},
    )
    builder.add_conditional_edges(
        "score_and_route",
        _route_after_score,
        {"auto_flag_soft": "auto_flag_soft", "hitl_interrupt": "hitl_interrupt", END: END},
    )
    builder.add_conditional_edges(
        "auto_flag_soft",
        _route_after_soft,
        {"write_case_packet": "write_case_packet", END: END},
    )
    builder.add_conditional_edges(
        "hitl_interrupt",
        lambda state: _route_stop(state, "await_hitl"),
        {"await_hitl": "await_hitl", END: END},
    )
    builder.add_conditional_edges(
        "await_hitl",
        _route_after_await,
        {"quarantine": "quarantine", "write_case_packet": "write_case_packet", END: END},
    )
    builder.add_edge("quarantine", END)
    builder.add_edge("write_case_packet", END)
    return builder.compile(checkpointer=InMemorySaver())
