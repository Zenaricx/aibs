"""Exact-base Git worktree candidate isolation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitCandidateError(RuntimeError):
    """Raised when candidate isolation cannot be proven safely."""


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise GitCandidateError(result.stderr.strip() or f"git command failed: {arguments!r}")
    return result.stdout.strip()


def _normalise_origin(origin: str) -> str | None:
    value = origin.strip().lower()
    if value == "zenaricx/aibs":
        return value
    if value.startswith("https://github.com/") or value.startswith("http://github.com/"):
        path = value.split("github.com/", 1)[1]
    elif value.startswith("git@github.com:"):
        path = value.split("git@github.com:", 1)[1]
    elif value.startswith("ssh://git@github.com/"):
        path = value.split("ssh://git@github.com/", 1)[1]
    else:
        return None
    return path.rstrip("/").removesuffix(".git")


def repository_identity_matches(repository: str | os.PathLike[str], identifier: str) -> bool:
    try:
        origin = _git(Path(repository), "config", "--get", "remote.origin.url")
    except GitCandidateError:
        return False
    return _normalise_origin(origin) == _normalise_origin(identifier) == "zenaricx/aibs"


def _clean(repository: Path) -> bool:
    return _git(repository, "status", "--porcelain") == ""


def create_candidate(
    repository: str | os.PathLike[str],
    candidate_worktree: str | os.PathLike[str],
    repository_identifier: str,
    authorised_base_commit: str,
) -> dict:
    source = Path(repository).resolve()
    candidate = Path(candidate_worktree).resolve()
    if not source.is_dir() or not repository_identity_matches(source, repository_identifier):
        raise GitCandidateError("repository identity does not match")
    if candidate.exists():
        raise GitCandidateError("candidate worktree path already exists")
    if not _clean(source):
        raise GitCandidateError("source checkout is not clean")
    source_head = _git(source, "rev-parse", "HEAD")
    try:
        resolved_base = _git(source, "rev-parse", "--verify", f"{authorised_base_commit}^{{commit}}")
    except GitCandidateError as exc:
        raise GitCandidateError("authorised base commit does not exist") from exc
    if resolved_base != authorised_base_commit:
        raise GitCandidateError("authorised base commit is not the exact resolved commit")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    _git(source, "worktree", "add", "--detach", str(candidate), authorised_base_commit)
    try:
        if _git(candidate, "rev-parse", "HEAD") != authorised_base_commit:
            raise GitCandidateError("candidate HEAD does not equal authorised base")
        if not _clean(candidate):
            raise GitCandidateError("candidate worktree is not clean")
        if _git(source, "rev-parse", "HEAD") != source_head or not _clean(source):
            raise GitCandidateError("source checkout changed during candidate creation")
    except Exception:
        raise
    return {
        "repository": str(source),
        "candidate_worktree": str(candidate),
        "repository_identifier": repository_identifier,
        "base_commit": authorised_base_commit,
        "source_head": source_head,
    }
