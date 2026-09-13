# AIBS-GATE0-002 — Execution Slice Contract v0.1

## 1. Purpose

`Execution Slice` is the bounded implementation unit below a Work Order. It exists so scarce agentic execution can be interrupted safely and resumed from durable state.

Version 0.1 is intentionally narrow. It validates whether a slice is sufficiently specified and safely bounded for unattended implementation. It is not the full future AIBS governance schema.

## 2. File format

UTF-8 JSON.

No YAML dependency is required in v0.1.

## 3. Required shape

```json
{
  "schema_version": "0.1",
  "work_order_id": "WO-GATE0-001",
  "execution_slice_id": "ES-GATE0-001",
  "objective": "Implement the deterministic AIBS Execution Slice validator.",
  "repository": {
    "identifier": "owner/aibs-gate0-sandbox",
    "base_commit": "0123456789abcdef0123456789abcdef01234567"
  },
  "scope": {
    "allowed_paths": [
      "tools/validate_execution_slice.py",
      "tests/test_validate_execution_slice.py",
      "tests/fixtures/**"
    ],
    "forbidden_paths": [
      "GOVERNANCE.md",
      ".github/**",
      "secrets/**"
    ]
  },
  "acceptance": {
    "commands": ["python -m unittest discover -s tests -v"],
    "must_pass": true
  },
  "timebox": {
    "max_minutes": 30
  },
  "stop_conditions": [
    "architecture_uncertainty",
    "unexpected_scope_expansion",
    "protected_path_change_required",
    "test_environment_unavailable"
  ],
  "authority": {
    "merge_accepted_state": false,
    "deploy_production": false,
    "modify_secrets": false,
    "external_communications": false,
    "unapproved_spend": false,
    "scope_expansion": false
  },
  "checkpoint": {
    "required": true,
    "required_fields": [
      "completed_work",
      "tests_run",
      "remaining_failures",
      "discoveries",
      "base_commit",
      "candidate_commit",
      "next_action",
      "status"
    ]
  }
}
```

## 4. Validation rules

### 4.1 Structure

The validator must reject:

- malformed JSON;
- missing required keys;
- unknown keys at any defined object level;
- incorrect value types.

### 4.2 Strings

Required string values must be non-empty after trimming.

### 4.3 Repository

- `repository.identifier` must be a non-empty string.
- `repository.base_commit` must be a full hexadecimal Git object identifier of exactly 40 or 64 characters.

The validator does not contact GitHub or verify that the repository/commit exists. Existence is a dispatch-time preflight responsibility.

### 4.4 Paths

`allowed_paths` and `forbidden_paths` must each be non-empty arrays of non-empty strings.

Paths must be repository-relative and use `/` separators.

Reject a path if it:

- begins with `/`;
- begins with a Windows drive prefix such as `C:`;
- contains a `..` path segment;
- contains a backslash `\\`.

The v0.1 validator does not attempt semantic wildcard-overlap analysis.

### 4.5 Acceptance

- `acceptance.commands` must contain at least one non-empty command string.
- `acceptance.must_pass` must be exactly `true`.

The validator validates the contract only. It does not execute commands.

### 4.6 Timebox

`timebox.max_minutes` must be an integer from 1 through 120 inclusive.

Gate 0 uses 30 minutes.

### 4.7 Stop conditions

`stop_conditions` must contain at least one non-empty string.

### 4.8 Authority

All v0.1 authority fields are required and must be exactly `false`:

- `merge_accepted_state`
- `deploy_production`
- `modify_secrets`
- `external_communications`
- `unapproved_spend`
- `scope_expansion`

This makes Gate 0 fail closed on unattended authority.

### 4.9 Checkpoint

- `checkpoint.required` must be exactly `true`.
- `checkpoint.required_fields` must be an array of non-empty strings.
- It must contain all eight mandatory fields:
  - `completed_work`
  - `tests_run`
  - `remaining_failures`
  - `discoveries`
  - `base_commit`
  - `candidate_commit`
  - `next_action`
  - `status`

Additional checkpoint field names may be allowed in v0.1.

## 5. Validator CLI contract

Expected invocation:

```text
python tools/validate_execution_slice.py path/to/execution-slice.json
```

Expected exit codes:

- `0` — contract valid;
- `1` — contract parsed but failed validation;
- `2` — file could not be read or JSON could not be parsed.

Expected output behaviour:

- valid input: concise `PASS` message on stdout;
- invalid contract: deterministic human-readable validation errors on stderr;
- I/O/JSON parse error: concise error on stderr;
- never rewrite the input file.

Validation errors should be emitted in a deterministic order so tests do not depend on dictionary traversal accident.

## 6. Dependency rule

The validator must use Python standard library only unless the repository already has an explicitly approved dependency that materially simplifies implementation. Gate 0 assumes **no new dependency is necessary**.
