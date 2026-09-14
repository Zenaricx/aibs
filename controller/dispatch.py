"""Immutable, minimal handoff packets for authorised implementation harnesses."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from .lifecycle import LifecycleState
from .state_store import canonical_json_bytes, freeze_execution_slice


class DispatchError(RuntimeError):
    """Raised when a dispatch cannot be proven safe and unambiguous."""


def _git(candidate: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(candidate), *arguments], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise DispatchError(result.stderr.strip() or f"git command failed: {arguments!r}")
    return result.stdout.strip()


def validate_dispatch_inputs(document: dict, record: dict, candidate_worktree: str | Path) -> Path:
    digest, _ = freeze_execution_slice(document)
    if record.get("state") != LifecycleState.ADMITTED.value:
        raise DispatchError("only an admitted lifecycle record can be dispatched")
    if record.get("execution_slice_hash") != digest:
        raise DispatchError("execution slice does not match admitted lifecycle record")
    repository = document["repository"]
    if record.get("repository_identifier") != repository["identifier"]:
        raise DispatchError("repository identifier does not match admitted lifecycle record")
    if record.get("authorised_base_commit") != repository["base_commit"]:
        raise DispatchError("authorised base does not match admitted lifecycle record")
    candidate = Path(candidate_worktree).resolve()
    if not candidate.is_dir():
        raise DispatchError("candidate worktree does not exist")
    if _git(candidate, "rev-parse", "HEAD") != repository["base_commit"]:
        raise DispatchError("candidate worktree is not at the authorised base")
    if _git(candidate, "status", "--porcelain"):
        raise DispatchError("candidate worktree is not clean before dispatch")
    return candidate


def build_dispatch(document: dict, record: dict, candidate_worktree: str | Path) -> dict:
    """Create an explicit, capability-limited task packet for one implementation run."""

    candidate = validate_dispatch_inputs(document, record, candidate_worktree)
    return {
        "dispatch_version": "0.1",
        "run_id": record["run_id"],
        "execution_slice_hash": record["execution_slice_hash"],
        "repository": {
            "identifier": record["repository_identifier"],
            "authorised_base_commit": record["authorised_base_commit"],
            "candidate_worktree": str(candidate),
        },
        "task": {
            "work_order_id": document["work_order_id"],
            "execution_slice_id": document["execution_slice_id"],
            "objective": document["objective"],
            "scope": document["scope"],
            "acceptance": document["acceptance"],
            "timebox": document["timebox"],
            "stop_conditions": document["stop_conditions"],
            "authority": document["authority"],
            "checkpoint": document["checkpoint"],
        },
        "handoff": {
            "required_completion_action": "Run tools/aibs_verify_candidate.py with this admitted slice and run_id.",
            "forbidden_actions": [
                "merge accepted state",
                "deploy production",
                "modify secrets",
                "external communications",
                "unapproved spend",
                "scope expansion",
            ],
        },
    }


def dispatch_hash(packet: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(packet)).hexdigest()


def persist_dispatch(state_root: str | Path, packet: dict) -> Path:
    """Durably persist one immutable packet, permitting only exact retries."""

    root = Path(state_root).resolve()
    target = root / "dispatch.json"
    data = canonical_json_bytes(packet)
    if target.exists():
        try:
            existing = target.read_bytes()
        except OSError as exc:
            raise DispatchError("existing dispatch packet cannot be read") from exc
        if existing != data:
            raise DispatchError("a different dispatch packet already exists for this run")
        return target
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return persist_dispatch(root, packet)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise DispatchError("could not durably persist dispatch packet") from exc
    return target
