"""Owner-authorized terminal lifecycle finalization."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from .lifecycle import LifecycleState
from .state_store import StateStore


class FinalizationError(RuntimeError):
    """Raised when an owner decision cannot be safely recorded."""


def record_owner_decision(state_root: str | Path, decision: str) -> dict:
    """Persist and complete one explicit owner decision, resuming safely if needed."""

    target = {"accept": LifecycleState.ACCEPTED, "reject": LifecycleState.REJECTED}.get(decision)
    if target is None:
        raise FinalizationError("decision must be 'accept' or 'reject'")
    store = StateStore(state_root)
    record = store.read()
    decision_document = {"decision": target.value, "run_id": record["run_id"]}
    evidence_path = store.root / "owner-decision.json"
    if evidence_path.exists():
        try:
            with evidence_path.open("r", encoding="utf-8") as handle:
                existing = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FinalizationError("owner decision evidence is unreadable") from exc
        if existing != decision_document:
            raise FinalizationError("owner decision conflicts with existing evidence")
    elif record["state"] in {
        LifecycleState.CANDIDATE_READY.value,
        LifecycleState.REVIEW_REQUIRED.value,
        LifecycleState.OWNER_ACCEPTANCE.value,
    }:
        store.write_evidence("owner-decision.json", decision_document)
    else:
        raise FinalizationError("run is not ready for owner finalization")

    next_state = {
        LifecycleState.CANDIDATE_READY.value: LifecycleState.REVIEW_REQUIRED,
        LifecycleState.REVIEW_REQUIRED.value: LifecycleState.OWNER_ACCEPTANCE,
        LifecycleState.OWNER_ACCEPTANCE.value: target,
    }.get(record["state"])
    while next_state is not None:
        record = store.transition(record, next_state, timestamp=datetime.now(timezone.utc).isoformat())
        next_state = {
            LifecycleState.CANDIDATE_READY.value: LifecycleState.REVIEW_REQUIRED,
            LifecycleState.REVIEW_REQUIRED.value: LifecycleState.OWNER_ACCEPTANCE,
            LifecycleState.OWNER_ACCEPTANCE.value: target,
        }.get(record["state"])
    if record["state"] != target.value:
        raise FinalizationError("run has an incompatible terminal state")
    if store.lock_path.exists():
        store.release(record["run_id"])
    return record
