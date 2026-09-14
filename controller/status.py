"""Read-only aggregation of one AIBS run's external state."""

from __future__ import annotations

import json
from pathlib import Path

from .state_store import StateStore, StateStoreError


class StatusError(RuntimeError):
    """Raised when run state is missing, corrupt, or internally inconsistent."""


def _optional_json(root: Path, name: str) -> dict | None:
    path = root / name
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StatusError(f"{name} is unreadable or corrupt") from exc
    if not isinstance(value, dict):
        raise StatusError(f"{name} must contain a JSON object")
    return value


def read_run_status(state_root: str | Path, run_id: str | None = None) -> dict:
    root = Path(state_root).resolve()
    if not root.is_dir() or not (root / "lifecycle.json").is_file():
        raise StatusError("lifecycle state is missing")
    try:
        lifecycle = StateStore(root).read()
    except StateStoreError as exc:
        raise StatusError(str(exc)) from exc
    if run_id is not None and lifecycle.get("run_id") != run_id:
        raise StatusError("run_id does not match lifecycle state")
    result = {
        "run_id": lifecycle["run_id"],
        "state": lifecycle["state"],
        "execution_slice_hash": lifecycle["execution_slice_hash"],
        "repository_identifier": lifecycle["repository_identifier"],
        "authorised_base_commit": lifecycle["authorised_base_commit"],
        "verification": None,
        "review": None,
        "seal": None,
        "publication": None,
    }
    verification = _optional_json(root, "verification.json")
    review = _optional_json(root, "review.json")
    seal = _optional_json(root, "seal.json")
    publication = _optional_json(root, "publication.json")
    for name, value in (("verification", verification), ("review", review), ("seal", seal), ("publication", publication)):
        if value is not None:
            if value.get("run_id") != lifecycle["run_id"]:
                raise StatusError(f"{name} record does not match lifecycle run_id")
            if value.get("execution_slice_hash") != lifecycle["execution_slice_hash"]:
                raise StatusError(f"{name} record does not match lifecycle slice hash")
            result[name] = value
    return result
