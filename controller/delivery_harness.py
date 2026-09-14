"""Lean reusable planning, test-selection, and review-evidence harness."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class HarnessError(ValueError):
    """Raised when a project or feature record is not ready for harness use."""


def _read_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise HarnessError(f"{label} must be a JSON object")
    return value


def _strings(value: Any, label: str, *, required: bool = True) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise HarnessError(f"{label} must be a non-empty array of strings")
    return value


def load_project(path: str | Path) -> dict[str, Any]:
    project = _read_object(path, "project record")
    for key in ("schema_version", "project_id"):
        if not isinstance(project.get(key), str) or not project[key].strip():
            raise HarnessError(f"project record missing non-empty {key}")
    if project["schema_version"] != "0.1":
        raise HarnessError("unsupported project record schema_version")
    surfaces = project.get("protected_surfaces", [])
    if not isinstance(surfaces, list):
        raise HarnessError("protected_surfaces must be an array")
    for surface in surfaces:
        if not isinstance(surface, dict) or not isinstance(surface.get("name"), str) or not surface["name"].strip():
            raise HarnessError("protected surface requires name")
        _strings(surface.get("paths"), "protected surface paths")
        if not isinstance(surface.get("review_required"), bool):
            raise HarnessError("protected surface requires review_required")
    rules = project.get("test_rules", [])
    if not isinstance(rules, list):
        raise HarnessError("test_rules must be an array")
    for rule in rules:
        if not isinstance(rule, dict):
            raise HarnessError("test rule must be an object")
        _strings(rule.get("paths"), "test rule paths")
        _strings(rule.get("commands"), "test rule commands")
    _strings(project.get("default_test_commands"), "default_test_commands")
    return project


def load_feature(path: str | Path) -> dict[str, Any]:
    feature = _read_object(path, "feature record")
    for key in ("schema_version", "feature_id", "objective", "status"):
        if not isinstance(feature.get(key), str) or not feature[key].strip():
            raise HarnessError(f"feature record missing non-empty {key}")
    if feature["schema_version"] != "0.1":
        raise HarnessError("unsupported feature record schema_version")
    _strings(feature.get("acceptance_criteria"), "acceptance_criteria")
    _strings(feature.get("out_of_scope"), "out_of_scope")
    risk_surfaces = feature.get("risk_surfaces", [])
    if not isinstance(risk_surfaces, list) or any(not isinstance(item, str) or not item.strip() for item in risk_surfaces):
        raise HarnessError("risk_surfaces must be an array of strings")
    return feature


def changed_files(repository: str | Path, base: str) -> tuple[str, str, list[str]]:
    repo = Path(repository).resolve()
    try:
        base_commit = subprocess.run(["git", "rev-parse", "--verify", f"{base}^{{commit}}"], cwd=repo, check=True, text=True, capture_output=True).stdout.strip()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True).stdout.strip()
        result = subprocess.run(["git", "diff", "--name-only", f"{base_commit}..{head}"], cwd=repo, check=True, text=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HarnessError("could not inspect repository diff") from exc
    return base_commit, head, sorted(path for path in result.stdout.splitlines() if path)


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def build_plan(project: dict[str, Any], feature: dict[str, Any], base: str, head: str, files: list[str]) -> dict[str, Any]:
    detected = []
    review_required = False
    for surface in project["protected_surfaces"]:
        if any(_matches(path, surface["paths"]) for path in files):
            detected.append(surface["name"])
            review_required = review_required or surface["review_required"]
    for surface in feature["risk_surfaces"]:
        if surface not in detected:
            detected.append(surface)
        review_required = True
    commands: list[str] = []
    for rule in project["test_rules"]:
        if any(_matches(path, rule["paths"]) for path in files):
            commands.extend(command for command in rule["commands"] if command not in commands)
    if not commands:
        commands = list(project["default_test_commands"])
    return {
        "schema_version": "0.1",
        "kind": "aibs_delivery_plan",
        "project_id": project["project_id"],
        "feature_id": feature["feature_id"],
        "objective": feature["objective"],
        "base_commit": base,
        "candidate_commit": head,
        "changed_files": files,
        "risk_surfaces": detected,
        "review_required": review_required,
        "test_commands": commands,
    }


def plan_from_files(project_path: str | Path, feature_path: str | Path, repository: str | Path, base: str) -> dict[str, Any]:
    base_commit, head, files = changed_files(repository, base)
    return build_plan(load_project(project_path), load_feature(feature_path), base_commit, head, files)


def run_tests(repository: str | Path, commands: list[str]) -> list[dict[str, Any]]:
    results = []
    for command in commands:
        result = subprocess.run(command, cwd=Path(repository), text=True, capture_output=True, shell=True, check=False)
        results.append({"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    return results


def write_packet(packet_directory: str | Path, packet: dict[str, Any]) -> Path:
    target_directory = Path(packet_directory).resolve()
    target_directory.mkdir(parents=True, exist_ok=True)
    data = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    name = f"{packet['feature_id']}-{packet['candidate_commit'][:12]}-{digest[:12]}.json"
    target = target_directory / name
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=target_directory, prefix=".packet-", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise HarnessError("could not persist review packet") from exc
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise HarnessError("review packet verification failed")
    return target


def review(project_path: str | Path, feature_path: str | Path, repository: str | Path, base: str, packet_directory: str | Path) -> tuple[dict[str, Any], Path]:
    project = load_project(project_path)
    feature = load_feature(feature_path)
    base_commit, head, files = changed_files(repository, base)
    plan = build_plan(project, feature, base_commit, head, files)
    results = run_tests(repository, plan["test_commands"])
    packet = {**plan, "kind": "aibs_review_packet", "feature": feature, "test_results": results, "tests_passed": all(result["returncode"] == 0 for result in results)}
    return packet, write_packet(packet_directory, packet)
