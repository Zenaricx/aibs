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
from .verification import VerificationError, execute_and_verify, verify_candidate
from .review_packet import ReviewPacketError, build_review_packet, write_review_packet
from .finalization import FinalizationError, record_owner_decision

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
