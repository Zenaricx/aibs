#!/usr/bin/env python3
"""Prepare an immutable AIBS implementation-harness handoff packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.dispatch import build_dispatch, dispatch_hash, persist_dispatch
from controller.state_store import StateStore, StateStoreError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AIBS Phase A dispatch handoff")
    parser.add_argument("slice_json", type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--candidate-worktree", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    document = json.loads(args.slice_json.read_text(encoding="utf-8"))
    record = StateStore(args.state_root).read()
    if record["run_id"] != args.run_id:
        raise StateStoreError("run_id does not match admitted lifecycle record")
    packet = build_dispatch(document, record, args.candidate_worktree)
    path = persist_dispatch(args.state_root, packet)
    print(json.dumps({"dispatch_path": str(path), "dispatch_hash": dispatch_hash(packet)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
