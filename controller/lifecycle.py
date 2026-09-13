"""Deterministic Phase A lifecycle transitions."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


class LifecycleState(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    ADMITTED = "ADMITTED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    CANDIDATE_READY = "CANDIDATE_READY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    OWNER_ACCEPTANCE = "OWNER_ACCEPTANCE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    INTERRUPTED = "INTERRUPTED"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"


TERMINAL_STATES = frozenset(
    {
        LifecycleState.ACCEPTED,
        LifecycleState.REJECTED,
        LifecycleState.BLOCKED,
        LifecycleState.QUARANTINED,
        LifecycleState.FAILED,
    }
)

ALLOWED_TRANSITIONS = {
    LifecycleState.DRAFT: frozenset({LifecycleState.READY}),
    LifecycleState.READY: frozenset({LifecycleState.ADMITTED, LifecycleState.BLOCKED}),
    LifecycleState.ADMITTED: frozenset({LifecycleState.RUNNING, LifecycleState.BLOCKED}),
    LifecycleState.RUNNING: frozenset(
        {LifecycleState.VERIFYING, LifecycleState.INTERRUPTED, LifecycleState.FAILED}
    ),
    LifecycleState.INTERRUPTED: frozenset(
        {LifecycleState.VERIFYING, LifecycleState.QUARANTINED}
    ),
    LifecycleState.VERIFYING: frozenset(
        {LifecycleState.CANDIDATE_READY, LifecycleState.FAILED, LifecycleState.QUARANTINED}
    ),
    LifecycleState.CANDIDATE_READY: frozenset({LifecycleState.REVIEW_REQUIRED}),
    LifecycleState.REVIEW_REQUIRED: frozenset({LifecycleState.OWNER_ACCEPTANCE}),
    LifecycleState.OWNER_ACCEPTANCE: frozenset(
        {LifecycleState.ACCEPTED, LifecycleState.REJECTED}
    ),
}


class InvalidTransition(ValueError):
    """Raised when a lifecycle transition is not explicitly permitted."""


def _state(value: LifecycleState | str) -> LifecycleState:
    try:
        return value if isinstance(value, LifecycleState) else LifecycleState(value)
    except ValueError as exc:
        raise InvalidTransition(f"unknown lifecycle state: {value!r}") from exc


def transition(
    current: LifecycleState | str,
    target: LifecycleState | str,
    *,
    history: list[dict] | None = None,
    timestamp: str | None = None,
) -> dict:
    """Return one durable transition record after validating it."""

    source = _state(current)
    destination = _state(target)
    if destination not in ALLOWED_TRANSITIONS.get(source, frozenset()):
        raise InvalidTransition(f"transition {source.value} -> {destination.value} is not allowed")
    if history is not None and not isinstance(history, list):
        raise InvalidTransition("transition history must be a list")
    return {
        "from": source.value,
        "to": destination.value,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }
