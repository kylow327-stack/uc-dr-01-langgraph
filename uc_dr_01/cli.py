"""CLI for the fixture demo.

Examples:
  python -m uc_dr_01 run --case CASE-2041
  python -m uc_dr_01 run --case CASE-2077 --timeout
  python -m uc_dr_01 run --fixture fixtures/cases/case-paste.json
"""

from __future__ import annotations

import argparse
import json
import sys

from uc_dr_01.catalog import NAMED_CASES, load_case, load_fixture
from uc_dr_01.errors import DemoError
from uc_dr_01.runner import HITL_ACTIONS, run_case


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m uc_dr_01",
        description="UC-DR-01 document-risk LangGraph demo. Fixtures only. Not a bank system.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run one fixture case and print the decision JSON.")
    choice = run.add_mutually_exclusive_group(required=True)
    choice.add_argument(
        "--case",
        help=f"Named fixture. One of: {', '.join(NAMED_CASES)}.",
    )
    choice.add_argument("--fixture", help="Path to a case JSON pack in the fixture shape.")
    run.add_argument(
        "--timeout",
        action="store_true",
        help="If the run waits at HITL, resume with timeout. Timeout quarantines and does not approve.",
    )
    run.add_argument(
        "--action",
        choices=sorted(HITL_ACTIONS),
        help="Resume a waiting HITL run with approve, edit, reject, escalate, or timeout.",
    )
    run.add_argument("--note", default=None, help="Optional analyst note stored on an HITL action.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout and args.action and args.action != "timeout":
        parser.error("--timeout quarantines a waiting run. It cannot be combined with another --action.")
    action = "timeout" if args.timeout else args.action
    try:
        case_file = load_case(args.case) if args.case else load_fixture(args.fixture)
        payload = run_case(case_file, action=action, note=args.note)
    except DemoError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    print(json.dumps(payload, indent=2))
    return 0
