"""Independent-review and owner-acceptance records for verified AIBS candidates."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .evidence import EvidenceError, load_verification_evidence, verification_hash
from .lifecycle import LifecycleState
from .state_store import canonical_json_bytes


class ReviewError(RuntimeError):
    """Raised when a review decision is not tied to verified evidence."""


def build_review_record(record: dict, evidence: dict, reviewer: str, decision: str) -> dict:
    if record.get("state") not in {LifecycleState.REVIEW_REQUIRED.value, LifecycleState.OWNER_ACCEPTANCE.value}:
        raise ReviewError("only a review-required or owner-acceptance candidate can be decided")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ReviewError("reviewer must be a non-empty string")
    if decision not in {"accept", "reject"}:
        raise ReviewError("decision must be accept or reject")
    if evidence.get("run_id") != record.get("run_id"):
        raise ReviewError("verification evidence run_id does not match lifecycle record")
    if evidence.get("execution_slice_hash") != record.get("execution_slice_hash"):
        raise ReviewError("verification evidence slice hash does not match lifecycle record")
    if evidence.get("outcome") != "PASSED":
        raise ReviewError("only passing verification evidence can be reviewed")
    return {
        "review_version": "0.1",
        "run_id": record["run_id"],
        "execution_slice_hash": record["execution_slice_hash"],
        "verification_hash": verification_hash(evidence),
        "reviewer": reviewer.strip(),
        "decision": decision,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }


def persist_review_record(state_root: str | Path, review: dict) -> Path:
    """Persist one immutable owner decision; allow repeat invocation of that decision."""

    root = Path(state_root).resolve()
    target = root / "review.json"
    data = canonical_json_bytes(review)
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReviewError("existing review record cannot be read") from exc
        identity = ("run_id", "execution_slice_hash", "verification_hash", "reviewer", "decision")
        if not isinstance(existing, dict) or any(existing.get(key) != review.get(key) for key in identity):
            raise ReviewError("a different review record already exists for this run")
        return target
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return persist_review_record(root, review)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ReviewError("could not durably persist review record") from exc
    return target


def load_review_inputs(state_root: str | Path) -> dict:
    try:
        return load_verification_evidence(state_root)
    except EvidenceError as exc:
        raise ReviewError(str(exc)) from exc
