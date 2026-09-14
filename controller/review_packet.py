"""Deterministic local review-evidence packet generation."""
from __future__ import annotations
import json
from pathlib import Path
from .lifecycle import LifecycleState
from .state_store import StateStore, StateStoreError, freeze_execution_slice

class ReviewPacketError(RuntimeError):
    pass

def build_review_packet(state_root: str | Path) -> dict:
    root=Path(state_root); store=StateStore(root); record=store.read()
    if record["state"] != LifecycleState.CANDIDATE_READY.value:
        raise ReviewPacketError("run is not CANDIDATE_READY")
    try:
        slice_document=json.loads((root/"execution-slice.json").read_text(encoding="utf-8"))
        verification=json.loads((root/"verification.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewPacketError("required review evidence is unreadable") from exc
    digest,_=freeze_execution_slice(slice_document)
    if digest != record["execution_slice_hash"]: raise ReviewPacketError("frozen Execution Slice hash mismatch")
    if verification.get("candidate_commit") != record.get("candidate_head"):
        raise ReviewPacketError("verification candidate identity mismatch")
    return {"schema_version":"0.1","kind":"aibs_review_packet","provenance":{"work_order_id":record["work_order_id"],"execution_slice_id":record["execution_slice_id"],"execution_slice_hash":record["execution_slice_hash"],"run_id":record["run_id"],"repository_identifier":record["repository_identifier"],"authorised_base_commit":record["authorised_base_commit"]},"candidate":{"worktree":record["candidate_worktree"],"candidate_commit":record["candidate_head"],"source_head":record["source_head"]},"lifecycle":{"state":record["state"],"transition_history":record["transition_history"]},"verification":verification,"authority":{"publication":False,"merge":False,"deployment":False,"owner_acceptance_required":True}}

def write_review_packet(state_root: str | Path) -> dict:
    packet=build_review_packet(state_root); StateStore(state_root).write_evidence("review-packet.json",packet); return packet
