"""AIBS Phase A controller foundation."""

from .lifecycle import InvalidTransition, LifecycleState, transition
from .state_store import (
    LockError,
    StateStore,
    StateStoreError,
    canonical_json_bytes,
    freeze_execution_slice,
    validate_lifecycle_record,
)

__all__ = [
    "InvalidTransition",
    "LifecycleState",
    "LockError",
    "StateStore",
    "StateStoreError",
    "canonical_json_bytes",
    "freeze_execution_slice",
    "validate_lifecycle_record",
    "transition",
]
