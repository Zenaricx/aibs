"""Seal an accepted AIBS worktree into a local, traceable candidate commit."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .evidence import load_verification_evidence, verification_hash
from .execution import changed_paths, validate_changed_paths
from .state_store import canonical_json_bytes


class SealError(RuntimeError):
    """Raised when an accepted candidate cannot be sealed safely."""


def _git(candidate: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(candidate), *arguments], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise SealError(result.stderr.strip() or f"git command failed: {arguments!r}")
    return result.stdout.strip()


def _load_review(state_root: str | Path) -> dict:
    try:
        return json.loads((Path(state_root).resolve() / "review.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SealError("review record is unreadable or corrupt") from exc


def seal_candidate(document: dict, record: dict, state_root: str | Path, candidate_worktree: str | Path, branch: str) -> dict:
    if record.get("state") != "ACCEPTED":
        raise SealError("only an accepted candidate can be sealed")
    candidate = Path(candidate_worktree).resolve()
    evidence = load_verification_evidence(state_root)
    review = _load_review(state_root)
    if review.get("decision") != "accept" or review.get("run_id") != record.get("run_id"):
        raise SealError("accepted lifecycle record lacks a matching acceptance decision")
    if review.get("verification_hash") != verification_hash(evidence):
        raise SealError("review record does not match verification evidence")
    if evidence.get("outcome") != "PASSED" or evidence.get("execution_slice_hash") != record.get("execution_slice_hash"):
        raise SealError("candidate lacks matching passing verification evidence")
    if _git(candidate, "rev-parse", "HEAD") != record.get("authorised_base_commit"):
        raise SealError("candidate HEAD no longer equals the authorised base")
    paths = changed_paths(candidate)
    if paths != evidence.get("changed_paths"):
        raise SealError("candidate changes no longer match reviewed verification evidence")
    validate_changed_paths(paths, document["scope"]["allowed_paths"], document["scope"]["forbidden_paths"])
    _git(candidate, "check-ref-format", "--branch", branch)
    if _git(candidate, "branch", "--list", branch):
        raise SealError("candidate branch already exists")
    _git(candidate, "switch", "-c", branch)
    try:
        _git(candidate, "add", "--all")
        _git(candidate, "commit", "-m", f"AIBS candidate {record['run_id']}")
        commit = _git(candidate, "rev-parse", "HEAD")
    except Exception:
        raise
    return {
        "run_id": record["run_id"],
        "execution_slice_hash": record["execution_slice_hash"],
        "branch": branch,
        "candidate_commit": commit,
    }


def persist_seal(state_root: str | Path, seal: dict) -> Path:
    root = Path(state_root).resolve()
    target = root / "seal.json"
    data = canonical_json_bytes(seal)
    if target.exists():
        if target.read_bytes() == data:
            return target
        raise SealError("a different seal record already exists for this run")
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return persist_seal(root, seal)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return target
