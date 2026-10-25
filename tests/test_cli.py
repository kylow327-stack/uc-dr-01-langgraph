import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "uc_dr_01", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_soft_path_case_2041():
    completed = _run("run", "--case", "CASE-2041")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["caseId"] == "CASE-2041"
    assert payload["phase"] == "soft_written"
    assert payload["decision"]["policyRowIds"] == ["POL-06"]
    assert payload["packet"]["disposition"] == "non_clearing_soft_flag"
    assert payload["packet"]["clearsRegulatoryObligation"] is False
    assert '"approved": true' not in completed.stdout


def test_cli_hitl_timeout_case_2077():
    completed = _run("run", "--case", "CASE-2077", "--timeout")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["phase"] == "quarantine"
    assert payload["quarantine"]["approved"] is False
    assert payload["packet"] is None
    assert payload["decision"]["softFlagWritten"] is False
    assert payload["decision"]["tier"] == "medium"
    gap_ids = [gap["citationId"] for gap in payload["gaps"]]
    assert "gap:CASE-2077:missing_doc:proof_of_address" in gap_ids
    assert "gap:CASE-2077:missing_field:passport:expiry_date" in gap_ids
    assert "non_clearing_soft_flag" not in completed.stdout
    assert '"approved": true' not in completed.stdout


def test_cli_paste_fixture():
    completed = _run("run", "--fixture", "fixtures/cases/case-paste.json")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["caseId"] == "CASE-PASTE"
    assert payload["phase"] == "soft_written"
    assert payload["packet"]["clearsRegulatoryObligation"] is False
    assert payload["packet"]["disposition"] == "non_clearing_soft_flag"


def test_cli_timeout_on_soft_path_does_not_approve():
    completed = _run("run", "--case", "CASE-2041", "--timeout")
    assert completed.returncode == 2
    assert "nothing was approved" in completed.stderr.lower()
    assert completed.stdout == ""
