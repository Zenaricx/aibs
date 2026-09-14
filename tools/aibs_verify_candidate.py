#!/usr/bin/env python3
"""Verify an already-admitted AIBS candidate and route it to review safely."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.execution import acceptance_passed, changed_paths, run_acceptance_commands, validate_changed_paths
from controller.evidence import build_verification_evidence, persist_verification_evidence, verification_hash
from controller.lifecycle import LifecycleState
from controller.state_store import StateStore, StateStoreError, freeze_execution_slice


def _output(record: dict, paths: list[str], evidence: list[dict], verification_digest: str | None = None) -> None:
    payload = {"state": record["state"], "changed_paths": paths, "acceptance": evidence}
    if verification_digest:
        payload["verification_hash"] = verification_digest
    print(json.dumps(payload, sort_keys=True))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AIBS Phase A candidate verifier")
    parser.add_argument("slice_json", type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--candidate-worktree", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    document = json.loads(args.slice_json.read_text(encoding="utf-8"))
    store = StateStore(args.state_root)
    record = store.read()
    if record["run_id"] != args.run_id:
        raise StateStoreError("run_id does not match admitted lifecycle record")
    digest, _ = freeze_execution_slice(document)
    if digest != record["execution_slice_hash"]:
        raise StateStoreError("execution slice does not match admitted lifecycle record")
    if record["state"] not in {LifecycleState.ADMITTED.value, LifecycleState.RUNNING.value}:
        raise StateStoreError("candidate is not in an executable lifecycle state")
    paths = []
    evidence = []
    try:
        if record["state"] == LifecycleState.ADMITTED.value:
            record = store.transition(record, LifecycleState.RUNNING, timestamp=datetime.now(timezone.utc).isoformat())
        paths = changed_paths(args.candidate_worktree)
        validate_changed_paths(paths, document["scope"]["allowed_paths"], document["scope"]["forbidden_paths"])
        record = store.transition(record, LifecycleState.VERIFYING, timestamp=datetime.now(timezone.utc).isoformat())
        evidence = run_acceptance_commands(args.candidate_worktree, document["acceptance"]["commands"])
        serialised = [item.as_dict() for item in evidence]
        if not acceptance_passed(evidence):
            persisted = build_verification_evidence(record, "FAILED", paths, serialised)
            persist_verification_evidence(args.state_root, persisted)
            record = store.transition(record, LifecycleState.FAILED, timestamp=datetime.now(timezone.utc).isoformat())
            store.release(args.run_id)
            _output(record, paths, serialised, verification_hash(persisted))
            return 1
        persisted = build_verification_evidence(record, "PASSED", paths, serialised)
        persist_verification_evidence(args.state_root, persisted)
        record = store.transition(record, LifecycleState.CANDIDATE_READY, timestamp=datetime.now(timezone.utc).isoformat())
        record = store.transition(record, LifecycleState.REVIEW_REQUIRED, timestamp=datetime.now(timezone.utc).isoformat())
        store.release(args.run_id)
        _output(record, paths, serialised, verification_hash(persisted))
        return 0
    except Exception:
        try:
            record = store.transition(record, LifecycleState.QUARANTINED, timestamp=datetime.now(timezone.utc).isoformat())
            store.release(args.run_id)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())
