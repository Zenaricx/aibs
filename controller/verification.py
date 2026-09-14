"""Deterministic candidate execution and verification."""
from __future__ import annotations
import fnmatch, subprocess
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
    if _git(candidate, "rev-parse", "HEAD") != record["candidate_head"]:
        raise VerificationError("candidate HEAD differs from admitted identity")
    if _git(candidate, "merge-base", "--is-ancestor", base, "HEAD") is not None:
        pass
    status = _git(candidate, "status", "--porcelain")
    if status: raise VerificationError("candidate worktree is not clean")
    changed = _git(candidate, "diff", "--name-only", f"{base}..HEAD").splitlines() if _git(candidate, "rev-parse", "HEAD") != base else []
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
    return {"candidate_commit": _git(candidate,"rev-parse","HEAD"), "changed_paths": changed, "commands": results, "status":"PASS"}

def execute_and_verify(state_root: str | Path) -> dict:
    store=StateStore(state_root); record=store.read()
    if record["state"] != LifecycleState.ADMITTED.value: raise VerificationError("run is not ADMITTED")
    frozen=Path(state_root)/"execution-slice.json"
    import json
    document=json.loads(frozen.read_text(encoding="utf-8"))
    from .state_store import freeze_execution_slice
    digest,_=freeze_execution_slice(document)
    if digest != record["execution_slice_hash"]: raise VerificationError("frozen Execution Slice hash mismatch")
    record=store.transition(record,LifecycleState.RUNNING,timestamp="execution-start")
    try:
        result=verify_candidate(record,document)
        record=store.transition(record,LifecycleState.VERIFYING,timestamp="verification-start")
        store.write_evidence("verification.json",result)
        record=store.transition(record,LifecycleState.CANDIDATE_READY,timestamp="verification-pass")
        return result
    except KeyboardInterrupt:
        store.transition(record,LifecycleState.INTERRUPTED,timestamp="execution-interrupted")
        raise
    except Exception:
        try: store.transition(record,LifecycleState.FAILED,timestamp="verification-failed")
        except Exception: pass
        raise
