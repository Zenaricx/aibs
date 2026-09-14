"""Deterministic candidate execution and verification."""
from __future__ import annotations
import fnmatch, subprocess, json
from pathlib import Path
from .lifecycle import LifecycleState
from .state_store import StateStore, StateStoreError

class VerificationError(RuntimeError): pass

def _git(path: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=False)
    if r.returncode: raise VerificationError(r.stderr.strip() or "git command failed")
    return r.stdout.strip()

def verify_candidate(record: dict, slice_document: dict) -> dict:
    candidate = Path(record["candidate_worktree"])
    base = record["authorised_base_commit"]
    candidate_head = _git(candidate, "rev-parse", "HEAD")
    if candidate_head == record["candidate_head"] and candidate_head != base:
        raise VerificationError("candidate HEAD was not durably bound")
    ancestor = subprocess.run(["git", "-C", str(candidate), "merge-base", "--is-ancestor", base, "HEAD"], capture_output=True, text=True, check=False)
    if ancestor.returncode != 0:
        raise VerificationError("candidate HEAD is not descended from authorised base")
    status = _git(candidate, "status", "--porcelain")
    if status: raise VerificationError("candidate worktree is not clean")
    changed = _git(candidate, "diff", "--name-only", f"{base}..HEAD").splitlines() if candidate_head != base else []
    allowed, forbidden = slice_document["scope"]["allowed_paths"], slice_document["scope"]["forbidden_paths"]
    for path in changed:
        if any(fnmatch.fnmatch(path, p) for p in forbidden) or not any(fnmatch.fnmatch(path, p) for p in allowed):
            raise VerificationError(f"path outside authorised scope: {path}")
    results=[]
    for command in slice_document["acceptance"]["commands"]:
        try: result=subprocess.run(command, cwd=candidate, shell=True, capture_output=True, text=True, timeout=slice_document["timebox"]["max_minutes"]*60, check=False)
        except subprocess.TimeoutExpired as exc: raise VerificationError(f"acceptance command timed out: {command}") from exc
        results.append({"command":command,"returncode":result.returncode,"stdout":result.stdout,"stderr":result.stderr})
        if result.returncode != 0: raise VerificationError(f"acceptance command failed: {command}")
    return {"candidate_commit": candidate_head, "changed_paths": changed, "commands": results, "status":"PASS"}

def execute_and_verify(state_root: str | Path) -> dict:
    store=StateStore(state_root); record=store.read()
    if record["state"] != LifecycleState.ADMITTED.value: raise VerificationError("run is not ADMITTED")
    frozen=Path(state_root)/"execution-slice.json"
    document=json.loads(frozen.read_text(encoding="utf-8"))
    from .state_store import freeze_execution_slice
    digest,_=freeze_execution_slice(document)
    if digest != record["execution_slice_hash"]: raise VerificationError("frozen Execution Slice hash mismatch")
    record=store.transition(record,LifecycleState.RUNNING,timestamp="execution-start")
    try:
        record=store.transition(record,LifecycleState.VERIFYING,timestamp="verification-start")
        result=verify_candidate(record,document)
        record["candidate_head"] = result["candidate_commit"]
        store.write(record)
        store.write_evidence("verification.json",result)
        record=store.transition(record,LifecycleState.CANDIDATE_READY,timestamp="verification-pass")
        return result
    except KeyboardInterrupt:
        store.transition(record,LifecycleState.INTERRUPTED,timestamp="execution-interrupted")
        raise
    except Exception as exc:
        store.write_evidence("verification-failure.json", {"status":"FAILED", "error":str(exc)})
        try: store.transition(record,LifecycleState.FAILED,timestamp="verification-failed")
        except Exception: pass
        raise
