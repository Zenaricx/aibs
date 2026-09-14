"""Guarded publication of an accepted sealed candidate to a new remote branch."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .state_store import canonical_json_bytes


class PublishError(RuntimeError):
    """Raised when remote publication cannot be proven safe."""


_BRANCH = re.compile(r"^phase-a/[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _git(candidate: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(candidate), *arguments], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise PublishError(result.stderr.strip() or f"git command failed: {arguments!r}")
    return result.stdout.strip()


def validate_publication_inputs(record: dict, seal: dict, candidate_worktree: str | Path, remote_branch: str) -> Path:
    if record.get("state") != "ACCEPTED":
        raise PublishError("only an accepted candidate can be published")
    if seal.get("run_id") not in {None, record.get("run_id")}:
        raise PublishError("seal record does not match accepted lifecycle record")
    local_branch = seal.get("branch")
    commit = seal.get("candidate_commit")
    if not isinstance(local_branch, str) or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        raise PublishError("seal record has no valid candidate branch and commit")
    if not _BRANCH.fullmatch(remote_branch):
        raise PublishError("remote branch must use the phase-a/ prefix")
    candidate = Path(candidate_worktree).resolve()
    if _git(candidate, "branch", "--show-current") != local_branch:
        raise PublishError("candidate checkout is not on the sealed local branch")
    if _git(candidate, "rev-parse", "HEAD") != commit:
        raise PublishError("candidate HEAD does not match sealed commit")
    return candidate


def publish_candidate(record: dict, seal: dict, candidate_worktree: str | Path, remote_branch: str) -> dict:
    candidate = validate_publication_inputs(record, seal, candidate_worktree, remote_branch)
    remote = _git(candidate, "config", "--get", "remote.origin.url")
    if not remote:
        raise PublishError("candidate has no origin remote")
    existing = _git(candidate, "ls-remote", "--heads", "origin", f"refs/heads/{remote_branch}")
    if existing:
        raise PublishError("remote branch already exists; refusing overwrite")
    _git(candidate, "push", "origin", f"{seal['branch']}:refs/heads/{remote_branch}")
    verified = _git(candidate, "ls-remote", "--heads", "origin", f"refs/heads/{remote_branch}")
    remote_commit = verified.split()[0] if verified else ""
    if remote_commit != seal["candidate_commit"]:
        raise PublishError("remote branch did not resolve to the sealed commit")
    return {
        "remote": remote,
        "remote_branch": remote_branch,
        "candidate_commit": seal["candidate_commit"],
    }


def persist_publication(state_root: str | Path, publication: dict) -> Path:
    root = Path(state_root).resolve()
    target = root / "publication.json"
    data = canonical_json_bytes(publication)
    if target.exists():
        if target.read_bytes() == data:
            return target
        raise PublishError("a different publication record already exists for this run")
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return persist_publication(root, publication)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return target
