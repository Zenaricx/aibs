# AIBS-GATE0-003 — Validator Test Matrix

The following cases define Gate 0 acceptance. Codex may add useful tests, but may not weaken or remove these cases.

| ID | Case | Expected |
|---|---|---|
| T01 | Canonical valid fixture | exit 0 / PASS |
| T02 | Malformed JSON | exit 2 |
| T03 | Missing `objective` | exit 1 |
| T04 | `objective` only whitespace | exit 1 |
| T05 | Unknown top-level key | exit 1 |
| T06 | Missing nested required key | exit 1 |
| T07 | `base_commit` not hexadecimal | exit 1 |
| T08 | `base_commit` abbreviated rather than 40/64 chars | exit 1 |
| T09 | Empty `allowed_paths` | exit 1 |
| T10 | Absolute `/...` allowed path | exit 1 |
| T11 | Windows `C:` allowed path | exit 1 |
| T12 | `..` path traversal segment | exit 1 |
| T13 | Backslash path | exit 1 |
| T14 | Empty acceptance command list | exit 1 |
| T15 | Blank acceptance command | exit 1 |
| T16 | `must_pass: false` | exit 1 |
| T17 | `max_minutes: 0` | exit 1 |
| T18 | `max_minutes: 121` | exit 1 |
| T19 | Empty `stop_conditions` | exit 1 |
| T20 | Any authority field set to true | exit 1 |
| T21 | Missing authority field | exit 1 |
| T22 | `checkpoint.required: false` | exit 1 |
| T23 | Missing one mandatory checkpoint field | exit 1 |
| T24 | Valid checkpoint with an additional field name | exit 0 |
| T25 | Input file missing/unreadable | exit 2 |
| T26 | Validator does not modify canonical fixture | file hash/contents unchanged |

## Additional acceptance rules

- `python -m unittest discover -s tests -v` must pass from the documented repository root.
- Tests must not require network access.
- Tests must not require secrets.
- Tests must be deterministic and repeatable.
- No test may depend on current date/time or external service state.
