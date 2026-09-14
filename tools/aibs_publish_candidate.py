#!/usr/bin/env python3
"""Publish one accepted sealed candidate to a new remote phase-a branch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.publish import persist_publication, publish_candidate
from controller.state_store import StateStore, StateStoreError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AIBS guarded remote publication")
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--candidate-worktree", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--remote-branch", required=True)
    args = parser.parse_args(argv)
    record = StateStore(args.state_root).read()
    if record.get("run_id") != args.run_id:
        raise StateStoreError("run_id does not match accepted lifecycle record")
    try:
        seal = json.loads((args.state_root / "seal.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateStoreError("seal record is unreadable or corrupt") from exc
    publication = publish_candidate(record, seal, args.candidate_worktree, args.remote_branch)
    path = persist_publication(args.state_root, publication)
    print(json.dumps({**publication, "publication_path": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
