# AIBS Gate 0 Sandbox

Sacrificial non-production repository for proving unattended AIBS implementation execution.

## Purpose

The repository is intentionally tiny. The test harness and fixtures are prepared before Codex is invoked. Codex's Gate 0 implementation task is limited to creating:

`tools/validate_execution_slice.py`

and, only if strictly needed to correct a defect in the test harness itself, stopping and reporting the blocker rather than editing the tests.

## Run acceptance tests

```text
python -m unittest discover -s tests -v
```

The initial repository is expected to fail because the validator implementation does not yet exist. That failure is intentional and forms the Gate 0 starting state.
