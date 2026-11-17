"""Create the UC-DR-01 golden fixture dataset in LangSmith and run an experiment.

v1 is fixture-backed and does not call a model. The checks are the same
invariants the unit tests already lock: soft path never clears an obligation,
HITL timeout quarantines and does not approve, and high-tier waits without a packet.
"""

from __future__ import annotations

import json
import os
from typing import Any

from uc_dr_01.langsmith_tracing import DEFAULT_PROJECT, configure_tracing, tracing_enabled
from uc_dr_01.runner import run_named_case

DATASET_NAME = "uc-dr-01-golden"
EXPERIMENT_PREFIX = "uc-dr-01-golden"

# Expected outcomes taken from the existing fixture tests. Fixtures only.
GOLDEN_EXAMPLES: list[dict[str, Any]] = [
    {
        "inputs": {"case_id": "CASE-2041", "action": None},
        "outputs": {
            "phase": "soft_written",
            "tier": "low",
            "route": "soft",
            "policyRowIds": ["POL-06"],
            "disposition": "non_clearing_soft_flag",
            "clearsRegulatoryObligation": False,
            "softFlagWritten": True,
            "packetWritten": True,
        },
        "metadata": {"case_id": "CASE-2041", "flow": "soft_path"},
    },
    {
        "inputs": {"case_id": "CASE-2077", "action": None},
        "outputs": {
            "phase": "hitl_waiting",
            "tier": "medium",
            "route": "hitl",
            "policyRowIds": ["POL-05"],
            "disposition": None,
            "clearsRegulatoryObligation": False,
            "softFlagWritten": False,
            "packetWritten": False,
        },
        "metadata": {"case_id": "CASE-2077", "flow": "hitl_wait"},
    },
    {
        "inputs": {"case_id": "CASE-2077", "action": "timeout"},
        "outputs": {
            "phase": "quarantine",
            "tier": "medium",
            "route": "hitl",
            "policyRowIds": ["POL-05"],
            "disposition": None,
            "clearsRegulatoryObligation": False,
            "softFlagWritten": False,
            "packetWritten": False,
        },
        "metadata": {"case_id": "CASE-2077", "flow": "hitl_timeout"},
    },
    {
        "inputs": {"case_id": "CASE-2118", "action": None},
        "outputs": {
            "phase": "hitl_waiting",
            "tier": "high",
            "route": "hitl",
            "policyRowIds": ["POL-02", "POL-03", "POL-04"],
            "disposition": None,
            "clearsRegulatoryObligation": False,
            "softFlagWritten": False,
            "packetWritten": False,
        },
        "metadata": {"case_id": "CASE-2118", "flow": "high_tier"},
    },
    {
        "inputs": {"case_id": "CASE-PASTE", "action": None},
        "outputs": {
            "phase": "soft_written",
            "tier": "low",
            "route": "soft",
            "policyRowIds": ["POL-06"],
            "disposition": "non_clearing_soft_flag",
            "clearsRegulatoryObligation": False,
            "softFlagWritten": True,
            "packetWritten": True,
        },
        "metadata": {"case_id": "CASE-PASTE", "flow": "paste_soft_path"},
    },
]


def _walk(node: Any, visit):
    if isinstance(node, dict):
        for key, value in node.items():
            visit(key, value)
            _walk(value, visit)
    elif isinstance(node, list):
        for item in node:
            _walk(item, visit)


def _any_approved(payload: dict[str, Any]) -> bool:
    found = False

    def visit(key, value):
        nonlocal found
        if key == "approved" and value is True:
            found = True

    _walk(payload, visit)
    return found or '"approved": true' in json.dumps(payload)


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    decision = result.get("decision") or {}
    packet = result.get("packet")
    quarantine = result.get("quarantine") or {}
    return {
        "caseId": result.get("caseId"),
        "phase": result.get("phase"),
        "tier": decision.get("tier"),
        "route": decision.get("route"),
        "policyRowIds": list(decision.get("policyRowIds") or []),
        "disposition": decision.get("disposition"),
        "clearsRegulatoryObligation": decision.get("clearsRegulatoryObligation"),
        "softFlagWritten": decision.get("softFlagWritten"),
        "packetWritten": packet is not None,
        "approved": _any_approved(result),
        "quarantineApproved": quarantine.get("approved") if quarantine else None,
        "tracing": result.get("tracing"),
    }


def target(inputs: dict[str, Any]) -> dict[str, Any]:
    action = inputs.get("action") or None
    result = run_named_case(inputs["case_id"], action=action)
    return compact_result(result)


def score_phase(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    expected = reference_outputs.get("phase")
    actual = outputs.get("phase")
    return {
        "key": "phase",
        "score": 1.0 if actual == expected else 0.0,
        "comment": f"phase={actual} expected={expected}",
    }


def score_tier(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    expected = reference_outputs.get("tier")
    actual = outputs.get("tier")
    return {
        "key": "tier",
        "score": 1.0 if actual == expected else 0.0,
        "comment": f"tier={actual} expected={expected}",
    }


def score_policy_rows(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    expected = list(reference_outputs.get("policyRowIds") or [])
    actual = list(outputs.get("policyRowIds") or [])
    return {
        "key": "policy_rows",
        "score": 1.0 if actual == expected else 0.0,
        "comment": f"policyRowIds={actual} expected={expected}",
    }


def score_obligation_uncleared(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    actual = outputs.get("clearsRegulatoryObligation")
    return {
        "key": "obligation_uncleared",
        "score": 1.0 if actual is False else 0.0,
        "comment": f"clearsRegulatoryObligation={actual}; must stay false",
    }


def score_never_approved(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    approved = bool(outputs.get("approved"))
    return {
        "key": "never_approved",
        "score": 1.0 if not approved else 0.0,
        "comment": "a timeout or soft path must not set approved=true",
    }


def score_packet(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    expected_written = bool(reference_outputs.get("packetWritten"))
    actual_written = bool(outputs.get("packetWritten"))
    expected_disp = reference_outputs.get("disposition")
    actual_disp = outputs.get("disposition")
    ok = actual_written == expected_written and actual_disp == expected_disp
    return {
        "key": "packet",
        "score": 1.0 if ok else 0.0,
        "comment": f"packetWritten={actual_written} disposition={actual_disp} expected written={expected_written} disposition={expected_disp}",
    }


EVALUATORS = [
    score_phase,
    score_tier,
    score_policy_rows,
    score_obligation_uncleared,
    score_never_approved,
    score_packet,
]


def ensure_dataset(client: Any) -> Any:
    if client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
        existing = list(client.list_examples(dataset_id=dataset.id))
        if not existing:
            client.create_examples(dataset_id=dataset.id, examples=GOLDEN_EXAMPLES)
        return dataset
    dataset = client.create_dataset(
        dataset_name=DATASET_NAME,
        description=(
            "UC-DR-01 fixture golden set. Soft path, HITL wait, HITL timeout, "
            "high tier, and the pasted pack. No live customer documents."
        ),
    )
    client.create_examples(dataset_id=dataset.id, examples=GOLDEN_EXAMPLES)
    return dataset


def run_langsmith_evals() -> dict[str, Any]:
    try:
        from langsmith import Client
    except ImportError as exc:
        raise RuntimeError(
            'The langsmith package is not installed. Run: python -m pip install -e ".[trace]"'
        ) from exc

    if not os.environ.get("LANGSMITH_API_KEY", "").strip():
        raise RuntimeError("LANGSMITH_API_KEY is not set; cannot upload a LangSmith experiment.")

    os.environ["LANGSMITH_TRACING"] = "true"
    configure_tracing(resolve_workspace=True)
    if not os.environ.get("LANGSMITH_WORKSPACE_ID", "").strip():
        raise RuntimeError(
            "LANGSMITH_WORKSPACE_ID is not set. Organisation-scoped service keys need the "
            "workspace id from LangSmith Settings → General. A personal org with a single "
            "workspace is resolved automatically when the API can list it."
        )

    ls_client = Client()
    if not ls_client.has_project(DEFAULT_PROJECT):
        ls_client.create_project(
            DEFAULT_PROJECT,
            description="UC-DR-01 document-risk LangGraph fixture demo. Traces and golden evals.",
        )
    project = ls_client.read_project(project_name=DEFAULT_PROJECT)
    dataset = ensure_dataset(ls_client)
    results = ls_client.evaluate(
        target,
        data=DATASET_NAME,
        evaluators=EVALUATORS,
        experiment_prefix=EXPERIMENT_PREFIX,
        description="Fixture invariants: uncleared obligation, no timeout approval, expected phase and tier.",
        max_concurrency=1,
        metadata={"project": DEFAULT_PROJECT, "fixtures_only": True},
    )
    return {
        "project": DEFAULT_PROJECT,
        "project_url": project.url,
        "dataset": DATASET_NAME,
        "dataset_url": dataset.url,
        "experiment_name": results.experiment_name,
        "experiment_id": str(results.experiment_id) if results.experiment_id else None,
        "experiment_url": results.url,
        "tracing_enabled": tracing_enabled(),
    }


def render_langsmith_summary(payload: dict[str, Any]) -> str:
    lines = [
        "LangSmith experiment submitted.",
        f"Project: {payload.get('project_url') or payload.get('project')}",
        f"Dataset: {payload.get('dataset_url') or payload.get('dataset')}",
        f"Experiment: {payload.get('experiment_url') or payload.get('experiment_name')}",
    ]
    return "\n".join(lines) + "\n"
