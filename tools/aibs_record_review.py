#!/usr/bin/env python3
"""Record an evidence-bound owner decision for an AIBS candidate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.lifecycle import LifecycleState
from controller.review import build_review_record, load_review_inputs, persist_review_record
from controller.state_store import StateStore, StateStoreError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AIBS Phase A owner acceptance")
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--decision", required=True, choices=("accept", "reject"))
    args = parser.parse_args(argv)
    store = StateStore(args.state_root)
    record = store.read()
    if record["run_id"] != args.run_id:
        raise StateStoreError("run_id does not match review-required lifecycle record")
    evidence = load_review_inputs(args.state_root)
    review = build_review_record(record, evidence, args.reviewer, args.decision)
    path = persist_review_record(args.state_root, review)
    if record["state"] == LifecycleState.REVIEW_REQUIRED.value:
        record = store.transition(record, LifecycleState.OWNER_ACCEPTANCE, timestamp=datetime.now(timezone.utc).isoformat())
    terminal = LifecycleState.ACCEPTED if args.decision == "accept" else LifecycleState.REJECTED
    record = store.transition(record, terminal, timestamp=datetime.now(timezone.utc).isoformat())
    print(json.dumps({"state": record["state"], "review_path": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
