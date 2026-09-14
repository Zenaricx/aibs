"""Durable verification evidence for one AIBS candidate run."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .state_store import canonical_json_bytes


class EvidenceError(RuntimeError):
    """Raised when verification evidence cannot be persisted unambiguously."""


def verification_hash(evidence: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()


def build_verification_evidence(record: dict, outcome: str, paths: list[str], acceptance: list[dict]) -> dict:
    return {
        "evidence_version": "0.1",
        "run_id": record["run_id"],
        "execution_slice_hash": record["execution_slice_hash"],
        "outcome": outcome,
        "changed_paths": paths,
        "acceptance": acceptance,
    }


def persist_verification_evidence(state_root: str | Path, evidence: dict) -> Path:
    """Durably write evidence once; exact retries are allowed, replacements fail."""

    root = Path(state_root).resolve()
    target = root / "verification.json"
    data = canonical_json_bytes(evidence)
    if target.exists():
        try:
            existing = target.read_bytes()
        except OSError as exc:
            raise EvidenceError("existing verification evidence cannot be read") from exc
        if existing != data:
            raise EvidenceError("different verification evidence already exists for this run")
        return target
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return persist_verification_evidence(root, evidence)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise EvidenceError("could not durably persist verification evidence") from exc
    return target


def load_verification_evidence(state_root: str | Path) -> dict:
    try:
        with (Path(state_root).resolve() / "verification.json").open("r", encoding="utf-8") as handle:
            evidence = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("verification evidence is unreadable or corrupt") from exc
    if not isinstance(evidence, dict):
        raise EvidenceError("verification evidence must be a JSON object")
    return evidence
