# AIBS tools

## Execution Slice validation

```text
python tools/validate_execution_slice.py path/to/execution-slice.json
```

This validates the governed v0.1 contract without modifying its input.

## Phase A candidate workflow

`aibs_controller.py` admits one validated Execution Slice, freezes its
canonical hash into external lifecycle state, acquires the exclusive run lock,
and creates an exact-base detached candidate worktree.

After the authorised implementation activity has finished in that candidate,
run:

```text
python tools/aibs_verify_candidate.py path/to/execution-slice.json \
  --state-root path/to/external-state \
  --candidate-worktree path/to/candidate-worktree \
  --run-id approved-run-id
```

The verifier requires the supplied slice to hash exactly to the admitted
record. It captures all approved acceptance-command output, rejects changed
paths outside the allowed scope or inside the forbidden scope, and transitions
the run to `REVIEW_REQUIRED` only when acceptance succeeds. A failed acceptance
transitions to `FAILED`; an unsafe verification condition quarantines the run.
An identity mismatch with the admitted slice leaves the existing admission and
lock intact for investigation.
