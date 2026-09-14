#!/usr/bin/env python3
"""Horizon 0 reusable AIBS delivery-harness CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.delivery_harness import HarnessError, plan_from_files, review


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AIBS reusable delivery harness")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "review"):
        command = subcommands.add_parser(name)
        command.add_argument("--project", required=True, type=Path)
        command.add_argument("--feature", required=True, type=Path)
        command.add_argument("--repository", required=True, type=Path)
        command.add_argument("--base", required=True)
        if name == "review":
            command.add_argument("--packet-directory", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            value = plan_from_files(args.project, args.feature, args.repository, args.base)
            print(json.dumps(value, sort_keys=True, separators=(",", ":")))
            return 0
        packet, path = review(args.project, args.feature, args.repository, args.base, args.packet_directory)
        print(json.dumps({"packet": str(path), "tests_passed": packet["tests_passed"]}, sort_keys=True))
        return 0 if packet["tests_passed"] else 1
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
