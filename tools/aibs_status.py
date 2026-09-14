#!/usr/bin/env python3
"""Print one AIBS run's current external status as deterministic JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.status import read_run_status


def summary(status: dict) -> dict:
    verification = status["verification"] or {}
    review = status["review"] or {}
    seal = status["seal"] or {}
    publication = status["publication"] or {}
    return {
        "run_id": status["run_id"],
        "state": status["state"],
        "verification_outcome": verification.get("outcome"),
        "review_decision": review.get("decision"),
        "candidate_commit": seal.get("candidate_commit"),
        "remote_branch": publication.get("remote_branch"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AIBS read-only run status")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    current = read_run_status(args.state_root, args.run_id)
    print(json.dumps(summary(current) if args.summary else current, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
