"""Atomic JSON state and exclusive-run protection for Phase A."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any
import re

from .lifecycle import LifecycleState, TERMINAL_STATES, transition


class StateStoreError(RuntimeError):
    """Raised when durable state is missing, invalid, or cannot be written."""


class LockError(StateStoreError):
    """Raised when the state root is already locked or ambiguously locked."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$")
_PROVENANCE_FIELDS = (
    "work_order_id",
    "execution_slice_id",
    "execution_slice_hash",
    "repository_identifier",
    "authorised_base_commit",
    "run_id",
    "state",
    "transition_history",
    "created_at",
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def freeze_execution_slice(document: dict) -> tuple[str, bytes]:
    payload = canonical_json_bytes(document)
    return hashlib.sha256(payload).hexdigest(), payload


def validate_lifecycle_record(record: dict) -> None:
    if not isinstance(record, dict):
        raise StateStoreError("lifecycle state must be a JSON object")
    for field in _PROVENANCE_FIELDS:
        if field not in record:
            raise StateStoreError(f"lifecycle state missing required field: {field}")
    for field in ("work_order_id", "execution_slice_id", "repository_identifier", "run_id", "created_at"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise StateStoreError(f"lifecycle field must be a non-empty string: {field}")
    if not isinstance(record["execution_slice_hash"], str) or not _SHA256.fullmatch(
        record["execution_slice_hash"]
    ):
        raise StateStoreError("execution_slice_hash must be lowercase hexadecimal SHA-256")
    if not isinstance(record["authorised_base_commit"], str) or not _COMMIT.fullmatch(
        record["authorised_base_commit"]
    ):
        raise StateStoreError("authorised_base_commit must be a 40 or 64 character hexadecimal commit")
    try:
        LifecycleState(record["state"])
    except (TypeError, ValueError) as exc:
        raise StateStoreError("lifecycle state has an invalid state") from exc
    if not isinstance(record["transition_history"], list):
        raise StateStoreError("transition_history must be a list")


class StateStore:
    """Store one run's operational record outside the candidate repository."""

    def __init__(self, state_root: str | os.PathLike[str]):
        self.root = Path(state_root)
        if self.root.exists() and not self.root.is_dir():
            raise StateStoreError(f"state root is not a directory: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "lifecycle.json"
        self.lock_path = self.root / "active-run.lock"

    def acquire(self, run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise LockError("run_id must be a non-empty string")
        payload = {"run_id": run_id, "lock_version": 1}
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise LockError(f"active-run lock already exists: {self.lock_path}") from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
        except Exception as exc:
            try:
                self.lock_path.unlink()
            except OSError:
                pass
            raise LockError(f"could not persist active-run lock: {exc}") from exc

    def release(self, run_id: str) -> None:
        try:
            with self.lock_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LockError("active-run lock is unreadable; refusing removal") from exc
        if not isinstance(payload, dict) or payload.get("run_id") != run_id:
            raise LockError("active-run lock identity does not match")
        try:
            self.lock_path.unlink()
        except OSError as exc:
            raise LockError(f"could not release active-run lock: {exc}") from exc

    def write(self, record: dict) -> None:
        validate_lifecycle_record(record)
        data = canonical_json_bytes(record)
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.root, prefix=".lifecycle-", suffix=".tmp", delete=False
            ) as handle:
                temporary_name = handle.name
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.state_path)
        except OSError as exc:
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
            raise StateStoreError(f"could not atomically persist lifecycle state: {exc}") from exc

    def read(self) -> dict:
        try:
            with self.state_path.open("r", encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StateStoreError("lifecycle state is unreadable or corrupt") from exc
        validate_lifecycle_record(record)
        return record

    def transition(self, record: dict, target: LifecycleState | str, *, timestamp: str) -> dict:
        current = LifecycleState(record["state"])
        if current in TERMINAL_STATES:
            raise StateStoreError("terminal lifecycle state cannot transition")
        event = transition(current, target, timestamp=timestamp)
        updated = dict(record)
        updated["state"] = event["to"]
        updated["transition_history"] = list(record.get("transition_history", [])) + [event]
        self.write(updated)
        return updated
