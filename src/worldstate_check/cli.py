from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .demo import run_demo
from .engine import verify
from .errors import SpecError
from .loader import load_spec
from .models import VerificationContext, Verdict
from .report import render_text, report_payload, verify_json_report, write_json_report

EXIT_BY_VERDICT = {
    Verdict.VERIFIED: 0,
    Verdict.NOT_VERIFIED: 1,
    Verdict.UNCERTAIN: 2,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="worldstate-check",
        description="Verify observed postconditions after an AI agent or autonomous system acts.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    verify_parser = sub.add_parser("verify", help="evaluate a verification specification")
    verify_parser.add_argument("spec", type=Path)
    verify_parser.add_argument("--root", type=Path, help="verification root; defaults to the specification directory")
    verify_parser.add_argument("--allow-outside-root", action="store_true", help="allow file paths outside the verification root")
    verify_parser.add_argument("--allow-command", action="store_true", help="allow command checks in a trusted specification")
    verify_parser.add_argument("--allow-network", action="store_true", help="allow HTTP and TCP checks in a trusted specification")
    verify_parser.add_argument("--wait", type=float, default=0.0, metavar="SECONDS", help="retry until verified or the timeout expires")
    verify_parser.add_argument("--poll-interval", type=float, default=0.5, metavar="SECONDS")
    verify_parser.add_argument("--report", type=Path, help="write a JSON evidence report")
    verify_parser.add_argument("--json", action="store_true", help="print the JSON report instead of text")

    validate_parser = sub.add_parser("validate", help="validate a specification without evaluating it")
    validate_parser.add_argument("spec", type=Path)

    report_parser = sub.add_parser("verify-report", help="verify the SHA-256 digest of a saved evidence report")
    report_parser.add_argument("report", type=Path)

    init_parser = sub.add_parser("init", help="write a minimal starter specification")
    init_parser.add_argument("path", type=Path, nargs="?", default=Path("worldstate.yaml"))

    demo_parser = sub.add_parser("demo", help="run a deterministic synthetic example")
    demo_parser.add_argument("--scenario", choices=["verified", "partial"], default="partial")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            load_spec(args.spec)
            print(f"VALID: {args.spec}")
            return 0
        if args.command == "verify-report":
            try:
                valid = verify_json_report(args.report)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"ERROR: could not read report: {exc}", file=sys.stderr)
                return 2
            print(f"{'VALID' if valid else 'INVALID'}: {args.report}")
            return 0 if valid else 1
        if args.command == "init":
            return _init_spec(args.path)
        if args.command == "demo":
            return EXIT_BY_VERDICT[run_demo(args.scenario)]
        if args.command == "verify":
            return _verify_command(args)
    except SpecError as exc:
        print(f"SPEC ERROR: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


def _verify_command(args: argparse.Namespace) -> int:
    spec_path = args.spec.resolve()
    spec = load_spec(spec_path)
    root = (args.root.resolve() if args.root else spec_path.parent)
    ctx = VerificationContext(
        spec_path=spec_path,
        root=root,
        allow_outside_root=args.allow_outside_root,
        allow_command=args.allow_command,
        allow_network=args.allow_network,
    )
    report = verify(spec, ctx, wait_seconds=args.wait, poll_interval=args.poll_interval)
    if args.report:
        write_json_report(report, args.report)
    if args.json:
        print(json.dumps(report_payload(report), indent=2, sort_keys=True))
    else:
        print(render_text(report))
        if args.report:
            print(f"Report: {args.report.resolve()}")
    return EXIT_BY_VERDICT[report.verdict]


def _init_spec(path: Path) -> int:
    if path.exists():
        print(f"ERROR: refusing to overwrite existing file: {path}", file=sys.stderr)
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """version: 1\ntask: verify-outcome\nchecks:\n  - id: result-file\n    type: file\n    path: result.json\n    exists: true\n\n  - id: result-state\n    type: json\n    path: result.json\n    field: status\n    operator: eq\n    value: complete\n""",
        encoding="utf-8",
    )
    print(f"Created {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
