"""Command line: read a gitvow request on stdin, or answer one question from arguments with `ask`."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .provider import Config, answer


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="gitvow-provider-facts", description="gitvow provider over a fact store or an NDJSON code graph."
    )
    p.add_argument("--version", action="version", version=f"gitvow-provider-facts {__version__}")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--store", help="a fact store (SQLite)")
    src.add_argument("--graph", help="a code graph exported as NDJSON (nodes and edges with stable ids and file:line)")
    p.add_argument(
        "--graph-fields", default="", help="JSON field map for a graph whose record keys differ from the default"
    )
    p.add_argument("--repo", default="")
    p.add_argument("--service", default="")
    p.add_argument("--gate-file", action="append", default=[])
    p.add_argument("--max-age-days", type=float, default=14)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("ask", help="answer one question from arguments (for testing)")
    s.add_argument("question", choices=["gate_bearing", "route_gate", "route_callers"])
    s.add_argument("subject")
    s.add_argument("--path", default="")
    a = p.parse_args(argv)
    cfg = Config(
        a.store or "", a.repo, a.service, a.gate_file, a.max_age_days, graph=a.graph or "", graph_fields=a.graph_fields
    )
    if a.cmd == "ask":
        req = {
            "protocol": 1,
            "question": a.question,
            "subject": a.subject,
            "path": a.path or (a.subject if a.question == "gate_bearing" else ""),
            "repo": "",
        }
    else:
        try:
            req = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(f"bad request: {e}", file=sys.stderr)
            return 2
    try:
        out = answer(cfg, req)
    except FileNotFoundError as e:
        print(f"{'graph' if cfg.graph else 'store'} not found: {e}", file=sys.stderr)
        return 3
    json.dump(out, sys.stdout)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
