"""Deterministic Slice 2 dispatch and checkpoint evidence."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .state_store import StateStore, StateStoreError, canonical_json_bytes
from .state_store import freeze_execution_slice

STATUSES = frozenset({"IN_PROGRESS", "WORK_COMPLETE", "BLOCKED", "FAILED", "INTERRUPTED"})
COMMIT = re.compile(r"^[0-9a-fA-F]+$")
REQUIRED = ("completed_work", "tests_run", "remaining_failures", "discoveries", "base_commit", "candidate_commit", "next_action", "status")

class CheckpointError(ValueError):
    pass

def dispatch_packet(slice_document: dict, record: dict) -> dict:
    digest, _ = freeze_execution_slice(slice_document)
    if digest != record["execution_slice_hash"]:
        raise CheckpointError("frozen Execution Slice hash mismatch")
    return {"schema_version": "0.1", "kind": "execution_dispatch", "work_order_id": record["work_order_id"], "execution_slice_id": record["execution_slice_id"], "execution_slice_hash": record["execution_slice_hash"], "repository_identifier": record["repository_identifier"], "authorised_base_commit": record["authorised_base_commit"], "run_id": record["run_id"], "candidate": {"worktree": record["candidate_worktree"], "base_commit": record["authorised_base_commit"], "candidate_commit": record["candidate_head"], "source_head": record["source_head"]}, "objective": slice_document["objective"], "scope": slice_document["scope"], "acceptance": slice_document["acceptance"], "timebox": slice_document["timebox"], "stop_conditions": slice_document["stop_conditions"], "checkpoint": slice_document["checkpoint"]}

def _validate(envelope: dict, record: dict) -> dict:
    if not isinstance(envelope, dict) or envelope.get("schema_version") != "0.1" or envelope.get("kind") != "execution_checkpoint":
        raise CheckpointError("invalid checkpoint envelope")
    provenance = envelope.get("provenance")
    expected = {"work_order_id": record["work_order_id"], "execution_slice_id": record["execution_slice_id"], "execution_slice_hash": record["execution_slice_hash"], "repository_identifier": record["repository_identifier"], "authorised_base_commit": record["authorised_base_commit"], "run_id": record["run_id"]}
    if provenance != expected:
        raise CheckpointError("checkpoint provenance mismatch")
    sequence = envelope.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise CheckpointError("checkpoint sequence must be a positive integer")
    body = envelope.get("checkpoint")
    if not isinstance(body, dict) or any(k not in body for k in REQUIRED):
        raise CheckpointError("checkpoint missing required field")
    if body["status"] not in STATUSES or not isinstance(body["next_action"], str) or not body["next_action"].strip():
        raise CheckpointError("invalid checkpoint status or next_action")
    if body["base_commit"] != record["authorised_base_commit"] or not isinstance(body["candidate_commit"], str) or len(body["candidate_commit"]) not in (40, 64) or not COMMIT.fullmatch(body["candidate_commit"]):
        raise CheckpointError("checkpoint commit provenance mismatch")
    for field in ("completed_work", "tests_run", "remaining_failures", "discoveries"):
        if not isinstance(body[field], list):
            raise CheckpointError(f"checkpoint field must be an array: {field}")
    return envelope

def ingest_checkpoint(state_root: str | Path, envelope: dict) -> dict:
    store = StateStore(state_root)
    record = store.read()
    frozen_path = Path(state_root) / "execution-slice.json"
    try:
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateStoreError("frozen Execution Slice is unreadable") from exc
    digest, _ = freeze_execution_slice(frozen)
    if digest != record["execution_slice_hash"]:
        raise CheckpointError("frozen Execution Slice hash mismatch")
    _validate(envelope, record)
    path = Path(state_root) / "checkpoint.json"
    if path.exists():
        try: old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc: raise StateStoreError("checkpoint evidence is unreadable") from exc
        if old.get("sequence", 0) > envelope["sequence"]: raise CheckpointError("stale checkpoint")
        if old.get("sequence") == envelope["sequence"]:
            if canonical_json_bytes(old) == canonical_json_bytes(envelope): return old
            raise CheckpointError("checkpoint sequence conflict")
    store.write_evidence("checkpoint.json", envelope)
    return envelope
