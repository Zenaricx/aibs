#!/usr/bin/env python3
"""Print one AIBS run's current external status as deterministic JSON."""

from __future__ import annotations

import argparse
import json

from controller.status import read_run_status


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AIBS read-only run status")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    print(json.dumps(read_run_status(args.state_root, args.run_id), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
