"""Optional LangSmith tracing helpers. Secrets stay in the environment and are never logged."""

from __future__ import annotations

import os
from typing import Optional

DEFAULT_PROJECT = "uc-dr-01"
_TRUE = {"1", "true", "yes", "on"}


def tracing_requested() -> bool:
    return os.environ.get("LANGSMITH_TRACING", "").strip().lower() in _TRUE


def api_key_present() -> bool:
    return bool(os.environ.get("LANGSMITH_API_KEY", "").strip())


def tracing_enabled() -> bool:
    return tracing_requested() and api_key_present()


def tracing_mode() -> str:
    if tracing_requested():
        return "langsmith_requested"
    return "off"


def _discover_workspace_id() -> Optional[str]:
    """If the key can see exactly one workspace, use it.

    Organisation-scoped service keys return 403 on traces and evals unless
    LANGSMITH_WORKSPACE_ID is set. A personal org with a single workspace
    can be resolved without asking for the id up front. The API key is sent
    as a header only and is never logged.
    """
    try:
        import requests
    except ImportError:
        return None
    key = os.environ.get("LANGSMITH_API_KEY", "").strip()
    if not key:
        return None
    endpoint = (
        os.environ.get("LANGSMITH_ENDPOINT")
        or os.environ.get("LANGCHAIN_ENDPOINT")
        or "https://api.smith.langchain.com"
    ).rstrip("/")
    try:
        response = requests.get(
            f"{endpoint}/api/v1/workspaces",
            headers={"x-api-key": key, "Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:  # noqa: BLE001 — tracing must not break the demo
        return None
    rows = payload if isinstance(payload, list) else payload.get("workspaces") or payload.get("items") or []
    active = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("id") and not row.get("is_deleted")
    ]
    if len(active) == 1:
        return str(active[0]["id"])
    return None


def configure_tracing(*, resolve_workspace: Optional[bool] = None) -> None:
    """Set the default project name, and resolve workspace id when needed.

    Does not turn tracing on. LANGSMITH_TRACING remains an explicit opt-in.
    """
    os.environ.setdefault("LANGSMITH_PROJECT", DEFAULT_PROJECT)
    if resolve_workspace is None:
        resolve_workspace = tracing_enabled()
    if resolve_workspace and not os.environ.get("LANGSMITH_WORKSPACE_ID", "").strip():
        workspace_id = _discover_workspace_id()
        if workspace_id:
            os.environ["LANGSMITH_WORKSPACE_ID"] = workspace_id


def flush_traces() -> None:
    """Flush buffered LangSmith runs so short CLI jobs are not dropped."""
    if not tracing_enabled():
        return
    try:
        from langsmith import Client

        Client().flush()
    except Exception:  # noqa: BLE001 — flushing must not fail the demo
        return
