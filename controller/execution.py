"""Controlled candidate execution and evidence capture for Phase A."""

from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ExecutionError(RuntimeError):
    """Raised when a candidate cannot be executed or evidenced safely."""


@dataclass(frozen=True)
class CommandEvidence:
    command: str
    returncode: int
    stdout: str
    stderr: str

    def as_dict(self) -> dict:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def _git(candidate: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(candidate), *arguments], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise ExecutionError(result.stderr.strip() or f"git command failed: {arguments!r}")
    return result.stdout.strip()


def changed_paths(candidate_worktree: str | Path) -> list[str]:
    """Return a deterministic list of paths changed from the candidate base."""

    candidate = Path(candidate_worktree).resolve()
    if not candidate.is_dir():
        raise ExecutionError("candidate worktree does not exist")
    base = _git(candidate, "rev-parse", "HEAD")
    output = _git(candidate, "diff", "--name-only", "--no-renames", base)
    paths = [line for line in output.splitlines() if line]
    untracked = _git(candidate, "ls-files", "--others", "--exclude-standard")
    paths.extend(line for line in untracked.splitlines() if line)
    return sorted(set(paths))


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path, pattern.rstrip("/**"))


def validate_changed_paths(paths: list[str], allowed_paths: list[str], forbidden_paths: list[str]) -> None:
    """Fail closed unless each changed path is authorised and non-protected."""

    unauthorised = []
    protected = []
    for path in paths:
        if any(_matches(path, pattern) for pattern in forbidden_paths):
            protected.append(path)
        if not any(_matches(path, pattern) for pattern in allowed_paths):
            unauthorised.append(path)
    if protected or unauthorised:
        parts = []
        if protected:
            parts.append("protected paths changed: " + ", ".join(protected))
        if unauthorised:
            parts.append("unauthorised paths changed: " + ", ".join(unauthorised))
        raise ExecutionError("; ".join(parts))


def run_acceptance_commands(candidate_worktree: str | Path, commands: list[str]) -> list[CommandEvidence]:
    """Run approved acceptance commands in the candidate, retaining all evidence."""

    candidate = Path(candidate_worktree).resolve()
    evidence = []
    for command in commands:
        result = subprocess.run(command, cwd=candidate, shell=True, capture_output=True, text=True, check=False)
        item = CommandEvidence(command, result.returncode, result.stdout, result.stderr)
        evidence.append(item)
        if result.returncode:
            break
    return evidence


def acceptance_passed(evidence: list[CommandEvidence]) -> bool:
    return bool(evidence) and all(item.returncode == 0 for item in evidence)
