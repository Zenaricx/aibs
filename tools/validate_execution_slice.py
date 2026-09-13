#!/usr/bin/env python3
"""Validate an AIBS Execution Slice contract v0.1."""

import json
import re
import sys
from pathlib import Path


EXIT_VALIDATION_ERROR = 1
EXIT_INPUT_ERROR = 2

TOP_LEVEL_KEYS = (
    "schema_version",
    "work_order_id",
    "execution_slice_id",
    "objective",
    "repository",
    "scope",
    "acceptance",
    "timebox",
    "stop_conditions",
    "authority",
    "checkpoint",
)
REPOSITORY_KEYS = ("identifier", "base_commit")
SCOPE_KEYS = ("allowed_paths", "forbidden_paths")
ACCEPTANCE_KEYS = ("commands", "must_pass")
TIMEBOX_KEYS = ("max_minutes",)
AUTHORITY_KEYS = (
    "merge_accepted_state",
    "deploy_production",
    "modify_secrets",
    "external_communications",
    "unapproved_spend",
    "scope_expansion",
)
CHECKPOINT_KEYS = ("required", "required_fields")
MANDATORY_CHECKPOINT_FIELDS = (
    "completed_work",
    "tests_run",
    "remaining_failures",
    "discoveries",
    "base_commit",
    "candidate_commit",
    "next_action",
    "status",
)
HEX_COMMIT = re.compile(r"^[0-9a-fA-F]+$")
WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def _unknown_keys(value, allowed, location, errors):
    if isinstance(value, dict):
        for key in sorted(set(value) - set(allowed)):
            errors.append(f"{location}: unknown key {key!r}")


def _required_keys(value, required, location, errors):
    if isinstance(value, dict):
        for key in required:
            if key not in value:
                errors.append(f"{location}: missing required key {key!r}")


def _non_empty_string(value, location, errors):
    if not isinstance(value, str):
        errors.append(f"{location}: expected a string")
    elif not value.strip():
        errors.append(f"{location}: must be a non-empty string")


def _string_array(value, location, errors, non_empty=True):
    if not isinstance(value, list):
        errors.append(f"{location}: expected an array")
        return
    if non_empty and not value:
        errors.append(f"{location}: must not be empty")
    for index, item in enumerate(value):
        _non_empty_string(item, f"{location}[{index}]", errors)


def _validate_paths(value, location, errors):
    before = len(errors)
    _string_array(value, location, errors)
    if len(errors) != before or not isinstance(value, list):
        return
    for index, path in enumerate(value):
        if path.startswith("/"):
            errors.append(f"{location}[{index}]: must be repository-relative")
        if WINDOWS_DRIVE.match(path):
            errors.append(f"{location}[{index}]: must not have a Windows drive prefix")
        if "\\" in path:
            errors.append(f"{location}[{index}]: must use '/' separators")
        if ".." in path.split("/"):
            errors.append(f"{location}[{index}]: must not contain '..' path segments")


def validate(document):
    errors = []
    if not isinstance(document, dict):
        return ["root: expected a JSON object"]

    _unknown_keys(document, TOP_LEVEL_KEYS, "root", errors)
    _required_keys(document, TOP_LEVEL_KEYS, "root", errors)

    for key in ("schema_version", "work_order_id", "execution_slice_id", "objective"):
        if key in document:
            _non_empty_string(document[key], key, errors)
    if isinstance(document.get("schema_version"), str) and document["schema_version"] != "0.1":
        errors.append("schema_version: must be exactly '0.1'")

    repository = document.get("repository")
    if not isinstance(repository, dict):
        if "repository" in document:
            errors.append("repository: expected an object")
    else:
        _unknown_keys(repository, REPOSITORY_KEYS, "repository", errors)
        _required_keys(repository, REPOSITORY_KEYS, "repository", errors)
        if "identifier" in repository:
            _non_empty_string(repository["identifier"], "repository.identifier", errors)
        if "base_commit" in repository:
            base_commit = repository["base_commit"]
            if not isinstance(base_commit, str):
                errors.append("repository.base_commit: expected a string")
            elif len(base_commit) not in (40, 64) or not HEX_COMMIT.fullmatch(base_commit):
                errors.append("repository.base_commit: must be 40 or 64 hexadecimal characters")

    scope = document.get("scope")
    if not isinstance(scope, dict):
        if "scope" in document:
            errors.append("scope: expected an object")
    else:
        _unknown_keys(scope, SCOPE_KEYS, "scope", errors)
        _required_keys(scope, SCOPE_KEYS, "scope", errors)
        if "allowed_paths" in scope:
            _validate_paths(scope["allowed_paths"], "scope.allowed_paths", errors)
        if "forbidden_paths" in scope:
            _validate_paths(scope["forbidden_paths"], "scope.forbidden_paths", errors)

    acceptance = document.get("acceptance")
    if not isinstance(acceptance, dict):
        if "acceptance" in document:
            errors.append("acceptance: expected an object")
    else:
        _unknown_keys(acceptance, ACCEPTANCE_KEYS, "acceptance", errors)
        _required_keys(acceptance, ACCEPTANCE_KEYS, "acceptance", errors)
        if "commands" in acceptance:
            _string_array(acceptance["commands"], "acceptance.commands", errors)
        if "must_pass" in acceptance and acceptance["must_pass"] is not True:
            errors.append("acceptance.must_pass: must be exactly true")

    timebox = document.get("timebox")
    if not isinstance(timebox, dict):
        if "timebox" in document:
            errors.append("timebox: expected an object")
    else:
        _unknown_keys(timebox, TIMEBOX_KEYS, "timebox", errors)
        _required_keys(timebox, TIMEBOX_KEYS, "timebox", errors)
        if "max_minutes" in timebox:
            minutes = timebox["max_minutes"]
            if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= 120:
                errors.append("timebox.max_minutes: must be an integer from 1 through 120")

    if "stop_conditions" in document:
        _string_array(document["stop_conditions"], "stop_conditions", errors)

    authority = document.get("authority")
    if not isinstance(authority, dict):
        if "authority" in document:
            errors.append("authority: expected an object")
    else:
        _unknown_keys(authority, AUTHORITY_KEYS, "authority", errors)
        _required_keys(authority, AUTHORITY_KEYS, "authority", errors)
        for key in AUTHORITY_KEYS:
            if key in authority and authority[key] is not False:
                errors.append(f"authority.{key}: must be exactly false")

    checkpoint = document.get("checkpoint")
    if not isinstance(checkpoint, dict):
        if "checkpoint" in document:
            errors.append("checkpoint: expected an object")
    else:
        _unknown_keys(checkpoint, CHECKPOINT_KEYS, "checkpoint", errors)
        _required_keys(checkpoint, CHECKPOINT_KEYS, "checkpoint", errors)
        if "required" in checkpoint and checkpoint["required"] is not True:
            errors.append("checkpoint.required: must be exactly true")
        if "required_fields" in checkpoint:
            _string_array(checkpoint["required_fields"], "checkpoint.required_fields", errors)
            if isinstance(checkpoint["required_fields"], list):
                present = set(checkpoint["required_fields"])
                for field in MANDATORY_CHECKPOINT_FIELDS:
                    if field not in present:
                        errors.append(f"checkpoint.required_fields: missing mandatory field {field!r}")

    return errors


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python tools/validate_execution_slice.py path/to/execution-slice.json", file=sys.stderr)
        return EXIT_INPUT_ERROR

    try:
        with Path(argv[0]).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: unable to read or parse JSON: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    errors = validate(document)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_VALIDATION_ERROR

    print("VALID: valid AIBS Execution Slice contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
