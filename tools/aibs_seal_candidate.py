#!/usr/bin/env python3
"""Create a local branch and commit for an accepted AIBS candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.seal import persist_seal, seal_candidate
from controller.state_store import StateStore, StateStoreError, freeze_execution_slice


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AIBS candidate sealing")
    parser.add_argument("slice_json", type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--candidate-worktree", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args(argv)
    document = json.loads(args.slice_json.read_text(encoding="utf-8"))
    record = StateStore(args.state_root).read()
    if record.get("run_id") != args.run_id:
        raise StateStoreError("run_id does not match accepted lifecycle record")
    if freeze_execution_slice(document)[0] != record.get("execution_slice_hash"):
        raise StateStoreError("execution slice does not match accepted lifecycle record")
    seal = seal_candidate(document, record, args.state_root, args.candidate_worktree, args.branch)
    path = persist_seal(args.state_root, seal)
    print(json.dumps({**seal, "seal_path": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
