"""Offline checks for the LangSmith golden set. These do not call LangSmith."""

from uc_dr_01.evals import GOLDEN_EXAMPLES, compact_result
from uc_dr_01.langsmith_tracing import configure_tracing, tracing_enabled
from uc_dr_01.runner import run_named_case


def test_configure_tracing_sets_default_project_without_enabling(monkeypatch):
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    configure_tracing()
    import os

    assert os.environ.get("LANGSMITH_PROJECT") == "uc-dr-01"
    assert tracing_enabled() is False


def test_golden_examples_match_fixture_invariants():
    names = {(item["inputs"]["case_id"], item["inputs"]["action"]) for item in GOLDEN_EXAMPLES}
    assert names == {
        ("CASE-2041", None),
        ("CASE-2077", None),
        ("CASE-2077", "timeout"),
        ("CASE-2118", None),
        ("CASE-PASTE", None),
    }
    for item in GOLDEN_EXAMPLES:
        assert item["outputs"]["clearsRegulatoryObligation"] is False
        if item["inputs"]["action"] == "timeout":
            assert item["outputs"]["phase"] == "quarantine"
            assert item["outputs"]["packetWritten"] is False


def test_target_compact_result_matches_soft_path_example():
    example = next(item for item in GOLDEN_EXAMPLES if item["inputs"]["case_id"] == "CASE-2041")
    result = compact_result(run_named_case("CASE-2041", run_id="run_eval_check_2041"))
    expected = example["outputs"]
    for key in expected:
        assert result[key] == expected[key]
    assert result["approved"] is False
