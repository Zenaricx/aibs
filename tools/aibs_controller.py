#!/usr/bin/env python3
"""Minimal Phase A foundation admission CLI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller.git_candidate import create_candidate
from controller.lifecycle import LifecycleState
from controller.state_store import StateStore, freeze_execution_slice
from controller.handoff import dispatch_packet, ingest_checkpoint
from controller.verification import execute_and_verify


def validate_operational_paths(repository: Path, state_root: Path, candidate_worktree: Path) -> None:
    paths = [Path(repository).resolve(), Path(state_root).resolve(), Path(candidate_worktree).resolve()]
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            try:
                common = os.path.normcase(os.path.commonpath([str(first), str(second)]))
            except ValueError as exc:
                raise ValueError("operational paths are on incompatible drives") from exc
            if common == os.path.normcase(str(first)) or common == os.path.normcase(str(second)):
                raise ValueError("repository, state_root, and candidate_worktree must be disjoint")


def _load_validated_slice(
    path: Path, external_root: Path, repository: Path, candidate_worktree: Path
) -> dict:
    validate_operational_paths(repository, external_root, candidate_worktree)
    external_root = Path(external_root).resolve()
    external_root.mkdir(parents=True, exist_ok=True)
    snapshot = path.read_bytes()
    validator = ROOT / "tools" / "validate_execution_slice.py"
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=external_root, prefix="aibs-slice-", suffix=".json", delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(snapshot)
            handle.flush()
            os.fsync(handle.fileno())
        result = subprocess.run(
            [sys.executable, str(validator), temporary_name],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            message = result.stderr.strip() or "Execution Slice validation failed"
            raise ValueError(message)
        return json.loads(snapshot.decode("utf-8"))
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def _record(document: dict, run_id: str, digest: str) -> dict:
    repository = document["repository"]
    return {
        "work_order_id": document["work_order_id"],
        "execution_slice_id": document["execution_slice_id"],
        "execution_slice_hash": digest,
        "repository_identifier": repository["identifier"],
        "authorised_base_commit": repository["base_commit"],
        "run_id": run_id,
        "state": LifecycleState.DRAFT.value,
        "transition_history": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_worktree": "",
        "candidate_head": "",
        "source_head": "",
    }


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "dispatch":
        parser = argparse.ArgumentParser()
        parser.add_argument("dispatch"); parser.add_argument("slice_json", type=Path); parser.add_argument("--state-root", required=True, type=Path)
        args = parser.parse_args(argv)
        store = StateStore(args.state_root); record = store.read()
        frozen = json.loads((Path(args.state_root) / "execution-slice.json").read_text(encoding="utf-8"))
        print(json.dumps(dispatch_packet(frozen, record), sort_keys=True, separators=(",", ":")))
        return 0
    if argv and argv[0] == "checkpoint":
        parser = argparse.ArgumentParser()
        parser.add_argument("checkpoint"); parser.add_argument("checkpoint_json", type=Path); parser.add_argument("--state-root", required=True, type=Path)
        args = parser.parse_args(argv)
        envelope = json.loads(args.checkpoint_json.read_text(encoding="utf-8"))
        ingest_checkpoint(args.state_root, envelope); print("PASS: checkpoint ingested"); return 0
    if argv and argv[0] == "execute":
        parser = argparse.ArgumentParser(); parser.add_argument("execute"); parser.add_argument("--state-root", required=True, type=Path)
        args = parser.parse_args(argv); print(json.dumps(execute_and_verify(args.state_root), sort_keys=True)); return 0
    parser = argparse.ArgumentParser(description="AIBS Phase A controller foundation")
    parser.add_argument("slice_json", type=Path)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--candidate-worktree", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    validate_operational_paths(args.repository, args.state_root, args.candidate_worktree)
    document = _load_validated_slice(
        args.slice_json, args.state_root, args.repository, args.candidate_worktree
    )
    digest, _ = freeze_execution_slice(document)
    store = StateStore(args.state_root)
    store.acquire(args.run_id)
    try:
        record = _record(document, args.run_id, digest)
        store.write(record)
        store.write_evidence("execution-slice.json", document)
        now = datetime.now(timezone.utc).isoformat()
        record = store.transition(record, LifecycleState.READY, timestamp=now)
        record = store.transition(record, LifecycleState.ADMITTED, timestamp=now)
        try:
            candidate = create_candidate(
                args.repository,
                args.candidate_worktree,
                document["repository"]["identifier"],
                document["repository"]["base_commit"],
            )
            record.update({"candidate_worktree": candidate["candidate_worktree"], "candidate_head": candidate["base_commit"], "source_head": candidate["source_head"]})
            store.write(record)
        except Exception as candidate_error:
            try:
                record = store.transition(
                    record, LifecycleState.BLOCKED, timestamp=datetime.now(timezone.utc).isoformat()
                )
                store.release(args.run_id)
            except Exception as blocked_error:
                raise candidate_error from blocked_error
            raise
        print(json.dumps({"state": record["state"], "candidate": candidate}, sort_keys=True))
    except Exception:
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
