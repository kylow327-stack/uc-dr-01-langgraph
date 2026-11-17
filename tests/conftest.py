import pytest


@pytest.fixture(autouse=True)
def _disable_langsmith_in_unit_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must stay offline and must not upload traces."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
