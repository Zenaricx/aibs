"""Read-only reconstruction of one AIBS run from durable state."""

from __future__ import annotations

import json
from pathlib import Path

from .state_store import StateStore, StateStoreError


class StatusError(RuntimeError):
    """Raised when a run status cannot be reconstructed safely."""


_EVIDENCE = ("execution-slice.json", "checkpoint.json", "verification.json", "review-packet.json", "owner-decision.json")


def _read_evidence(root: Path, name: str) -> dict | None:
    path = root / name
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StatusError(f"evidence is unreadable: {name}") from exc
    if not isinstance(value, dict):
        raise StatusError(f"evidence is not an object: {name}")
    return value


def _next_action(state: str, checkpoint: dict | None, evidence: dict[str, dict | None]) -> str:
    if state in {"ACCEPTED", "REJECTED"}:
        return "complete"
    if checkpoint and isinstance(checkpoint.get("checkpoint"), dict):
        action = checkpoint["checkpoint"].get("next_action")
        if isinstance(action, str) and action.strip():
            return action
    return {
        "DRAFT": "admit the execution slice",
        "READY": "create the admitted candidate",
        "ADMITTED": "dispatch the candidate to the Implementer",
        "RUNNING": "await the next worker checkpoint",
        "INTERRUPTED": "inspect the checkpoint and resume or quarantine",
        "VERIFYING": "await deterministic verification",
        "CANDIDATE_READY": "write the review packet" if evidence["review-packet.json"] is None else "record the owner decision",
        "REVIEW_REQUIRED": "record the owner decision",
        "OWNER_ACCEPTANCE": "resume or complete the owner decision",
        "BLOCKED": "resolve the blocking condition",
        "FAILED": "inspect the failure evidence",
        "QUARANTINED": "inspect the quarantine evidence",
    }.get(state, "inspect the lifecycle record")


def build_status(state_root: str | Path) -> dict:
    root = Path(state_root).resolve()
    if not root.is_dir() or not (root / "lifecycle.json").is_file():
        raise StatusError("lifecycle state is not present")
    try:
        record = StateStore(root).read()
    except StateStoreError as exc:
        raise StatusError(str(exc)) from exc
    evidence = {name: _read_evidence(root, name) for name in _EVIDENCE}
    return {
        "schema_version": "0.1",
        "kind": "aibs_run_status",
        "provenance": {
            key: record[key]
            for key in ("work_order_id", "execution_slice_id", "execution_slice_hash", "repository_identifier", "authorised_base_commit", "run_id")
        },
        "lifecycle": {"state": record["state"], "transition_history": record["transition_history"]},
        "candidate": {
            key: record.get(key, "")
            for key in ("candidate_worktree", "candidate_head", "source_head")
        },
        "evidence": {name[:-5]: value is not None for name, value in evidence.items()},
        "checkpoint": evidence["checkpoint.json"],
        "verification": evidence["verification.json"],
        "owner_decision": evidence["owner-decision.json"],
        "next_action": _next_action(record["state"], evidence["checkpoint.json"], evidence),
    }
