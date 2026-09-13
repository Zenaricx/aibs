import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from controller.git_candidate import GitCandidateError, create_candidate, repository_identity_matches
from controller.lifecycle import InvalidTransition, LifecycleState, transition
from controller.state_store import LockError, StateStore, StateStoreError, freeze_execution_slice
from tools.aibs_controller import _load_validated_slice, main, validate_operational_paths


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def git(path, *args, check=True):
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class ControllerFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_transition(self):
        self.assertEqual(transition("DRAFT", "READY", timestamp="t")["to"], "READY")

    def test_invalid_transition(self):
        with self.assertRaises(InvalidTransition):
            transition("DRAFT", "RUNNING", timestamp="t")

    def test_terminal_state_cannot_transition(self):
        with self.assertRaises(InvalidTransition):
            transition("ACCEPTED", "DRAFT", timestamp="t")

    def test_owner_acceptance_to_accepted(self):
        self.assertEqual(transition("OWNER_ACCEPTANCE", "ACCEPTED", timestamp="t")["to"], "ACCEPTED")

    def test_owner_acceptance_to_rejected(self):
        self.assertEqual(transition("OWNER_ACCEPTANCE", "REJECTED", timestamp="t")["to"], "REJECTED")

    def sample_slice(self):
        return {
            "schema_version": "0.1", "work_order_id": "WO", "execution_slice_id": "ES",
            "objective": "x", "repository": {"identifier": "Zenaricx/aibs", "base_commit": "a" * 40},
            "scope": {"allowed_paths": ["controller/**"], "forbidden_paths": [".git/**"]},
            "acceptance": {"commands": ["test"], "must_pass": True}, "timebox": {"max_minutes": 1},
            "stop_conditions": ["x"],
            "authority": {k: False for k in ("merge_accepted_state", "deploy_production", "modify_secrets", "external_communications", "unapproved_spend", "scope_expansion")},
            "checkpoint": {"required": True, "required_fields": ["completed_work", "tests_run", "remaining_failures", "discoveries", "base_commit", "candidate_commit", "next_action", "status"]},
        }

    def test_same_semantic_slice_same_hash(self):
        first = self.sample_slice()
        second = json.loads(json.dumps(first, indent=2))
        self.assertEqual(freeze_execution_slice(first)[0], freeze_execution_slice(second)[0])

    def test_different_slice_different_hash(self):
        first = self.sample_slice()
        second = self.sample_slice()
        second["objective"] = "different"
        self.assertNotEqual(freeze_execution_slice(first)[0], freeze_execution_slice(second)[0])

    def test_state_writes_and_rereads(self):
        store = StateStore(self.root / "state")
        record = self.valid_record()
        store.write(record)
        self.assertEqual(store.read(), record)

    def valid_record(self):
        return {
            "work_order_id": "WO",
            "execution_slice_id": "ES",
            "execution_slice_hash": "a" * 64,
            "repository_identifier": "Zenaricx/aibs",
            "authorised_base_commit": "b" * 40,
            "run_id": "r",
            "state": "DRAFT",
            "transition_history": [],
            "created_at": "2026-01-01T00:00:00+00:00",
        }

    def test_corrupt_state_fails_closed(self):
        state = self.root / "state"
        store = StateStore(state)
        store.state_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(StateStoreError):
            store.read()

    def test_missing_provenance_fails_closed(self):
        record = self.valid_record()
        del record["run_id"]
        with self.assertRaises(StateStoreError):
            StateStore(self.root / "state").write(record)

    def test_malformed_provenance_fails_closed(self):
        record = self.valid_record()
        record["execution_slice_hash"] = "A" * 64
        with self.assertRaises(StateStoreError):
            StateStore(self.root / "state").write(record)

    def test_first_lock_succeeds(self):
        store = StateStore(self.root / "state")
        store.acquire("r1")
        self.assertTrue(store.lock_path.exists())
        store.release("r1")

    def test_second_lock_rejected(self):
        first = StateStore(self.root / "state")
        second = StateStore(self.root / "state")
        first.acquire("r1")
        with self.assertRaises(LockError):
            second.acquire("r2")

    def test_existing_lock_not_removed(self):
        store = StateStore(self.root / "state")
        store.lock_path.write_text("not-json", encoding="utf-8")
        with self.assertRaises(LockError):
            store.acquire("r1")
        self.assertEqual(store.lock_path.read_text(encoding="utf-8"), "not-json")

    def init_repo(self):
        repo = self.root / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "aibs@example.test")
        git(repo, "config", "user.name", "AIBS Test")
        (repo / "file.txt").write_text("initial\n", encoding="utf-8")
        git(repo, "add", "file.txt")
        git(repo, "commit", "-q", "-m", "initial")
        git(repo, "remote", "add", "origin", "https://github.com/Zenaricx/aibs.git")
        return repo, git(repo, "rev-parse", "HEAD")

    def test_https_identity_accepted(self):
        repo, _ = self.init_repo()
        self.assertTrue(repository_identity_matches(repo, "https://github.com/Zenaricx/aibs.git"))

    def test_ssh_identity_accepted(self):
        repo, _ = self.init_repo()
        git(repo, "remote", "set-url", "origin", "git@github.com:Zenaricx/aibs.git")
        self.assertTrue(repository_identity_matches(repo, "Zenaricx/aibs"))

    def test_incorrect_identity_rejected(self):
        repo, _ = self.init_repo()
        self.assertFalse(repository_identity_matches(repo, "other/aibs"))

    def test_missing_base_rejected(self):
        repo, _ = self.init_repo()
        with self.assertRaises(GitCandidateError):
            create_candidate(repo, self.root / "candidate", "Zenaricx/aibs", "0" * 40)

    def test_dirty_source_rejected(self):
        repo, head = self.init_repo()
        (repo / "file.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(GitCandidateError):
            create_candidate(repo, self.root / "candidate", "Zenaricx/aibs", head)

    def test_exact_base_candidate_created_clean_and_source_unchanged(self):
        repo, head = self.init_repo()
        source_before = git(repo, "rev-parse", "HEAD")
        info = create_candidate(repo, self.root / "candidate", "Zenaricx/aibs", head)
        self.assertEqual(info["source_head"], source_before)
        self.assertEqual(git(self.root / "candidate", "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.root / "candidate", "status", "--porcelain"), "")
        self.assertEqual(git(repo, "rev-parse", "HEAD"), source_before)
        self.assertEqual(git(repo, "status", "--porcelain"), "")

    def test_preexisting_candidate_rejected(self):
        repo, head = self.init_repo()
        candidate = self.root / "candidate"
        candidate.mkdir()
        with self.assertRaises(GitCandidateError):
            create_candidate(repo, candidate, "Zenaricx/aibs", head)

    def test_snapshot_is_read_once_for_validation_and_hashing(self):
        path = self.root / "slice.json"
        path.write_text(json.dumps(self.sample_slice()), encoding="utf-8")
        captured = path.read_bytes()
        repository = self.root / "repository"
        candidate = self.root / "candidate"
        external = self.root / "external"
        repository.mkdir()
        with patch.object(Path, "read_bytes", autospec=True, return_value=captured) as read_bytes:
            document = _load_validated_slice(path, external, repository, candidate)
        self.assertEqual(document, self.sample_slice())
        self.assertEqual(read_bytes.call_count, 1)

    def test_snapshot_temp_location_is_external_to_repository_and_candidate(self):
        path = self.root / "slice.json"
        path.write_text(json.dumps(self.sample_slice()), encoding="utf-8")
        repository = self.root / "repository"
        candidate = self.root / "candidate"
        external = self.root / "external"
        repository.mkdir()
        candidate.mkdir()
        with patch("tools.aibs_controller.tempfile.NamedTemporaryFile", wraps=__import__("tempfile").NamedTemporaryFile) as temporary_file:
            _load_validated_slice(path, external, repository, candidate)
        location = Path(temporary_file.call_args.kwargs["dir"]).resolve()
        self.assertEqual(location, external.resolve())
        self.assertNotEqual(location, repository.resolve())
        self.assertNotEqual(location, candidate.resolve())

    def test_snapshot_temp_location_rejects_repository_or_candidate_containment(self):
        path = self.root / "slice.json"
        path.write_text(json.dumps(self.sample_slice()), encoding="utf-8")
        repository = self.root / "repository"
        candidate = self.root / "candidate"
        repository.mkdir()
        candidate.mkdir()
        with self.assertRaises(ValueError):
            _load_validated_slice(path, repository / "snapshot", repository, candidate)
        with self.assertRaises(ValueError):
            _load_validated_slice(path, candidate / "snapshot", repository, candidate)

    def test_operational_paths_reject_state_inside_repository_before_creation(self):
        repository = self.root / "repository"
        state_root = repository / "state"
        candidate = self.root / "candidate"
        repository.mkdir()
        with self.assertRaises(ValueError):
            validate_operational_paths(repository, state_root, candidate)
        self.assertFalse(state_root.exists())

    def test_operational_paths_reject_state_inside_candidate(self):
        repository = self.root / "repository"
        candidate = self.root / "candidate"
        repository.mkdir()
        with self.assertRaises(ValueError):
            validate_operational_paths(repository, candidate / "state", candidate)

    def test_operational_paths_reject_candidate_inside_repository(self):
        repository = self.root / "repository"
        repository.mkdir()
        with self.assertRaises(ValueError):
            validate_operational_paths(repository, self.root / "state", repository / "candidate")

    def test_independent_operational_paths_succeed(self):
        validate_operational_paths(self.root / "repository", self.root / "state", self.root / "candidate")

    def test_candidate_failure_persists_blocked_and_releases_lock(self):
        repo, head = self.init_repo()
        slice_path = self.root / "slice.json"
        document = self.sample_slice()
        document["repository"]["base_commit"] = head
        slice_path.write_text(json.dumps(document), encoding="utf-8")
        state = self.root / "state"
        candidate = self.root / "candidate"
        candidate.mkdir()
        admission_states = []

        def fail_after_admission(*args, **kwargs):
            admission_states.append(StateStore(state).read()["state"])
            raise GitCandidateError("candidate creation failed")

        with patch("tools.aibs_controller.create_candidate", side_effect=fail_after_admission):
            with self.assertRaises(GitCandidateError) as raised:
                main([
                    str(slice_path), "--repository", str(repo), "--state-root", str(state),
                    "--candidate-worktree", str(candidate), "--run-id", "run-1",
                ])
        self.assertEqual(admission_states, ["ADMITTED"])
        self.assertEqual(str(raised.exception), "candidate creation failed")
        store = StateStore(state)
        record = store.read()
        self.assertEqual(record["state"], "BLOCKED")
        self.assertEqual(record["transition_history"][-1]["from"], "ADMITTED")
        self.assertEqual(record["transition_history"][-1]["to"], "BLOCKED")
        self.assertFalse(store.lock_path.exists())

    def test_blocked_persistence_failure_retains_lock(self):
        repo, head = self.init_repo()
        slice_path = self.root / "slice.json"
        document = self.sample_slice()
        document["repository"]["base_commit"] = head
        slice_path.write_text(json.dumps(document), encoding="utf-8")
        state = self.root / "state"
        candidate = self.root / "candidate"
        candidate.mkdir()
        original = StateStore.transition
        calls = {"count": 0}

        def fail_blocked(self, record, target, *, timestamp):
            calls["count"] += 1
            if calls["count"] == 3:
                raise StateStoreError("simulated persistence failure")
            return original(self, record, target, timestamp=timestamp)

        admission_states = []

        def fail_after_admission(*args, **kwargs):
            admission_states.append(StateStore(state).read()["state"])
            raise GitCandidateError("candidate creation failed")

        with patch("tools.aibs_controller.create_candidate", side_effect=fail_after_admission):
            with patch.object(StateStore, "transition", fail_blocked):
                with self.assertRaises(GitCandidateError) as raised:
                    main([
                        str(slice_path), "--repository", str(repo), "--state-root", str(state),
                        "--candidate-worktree", str(candidate), "--run-id", "run-1",
                    ])
        self.assertEqual(admission_states, ["ADMITTED"])
        self.assertEqual(str(raised.exception), "candidate creation failed")
        self.assertTrue((state / "active-run.lock").exists())

    def test_existing_validator_regression_suite_passes(self):
        result = subprocess.run([PYTHON, str(ROOT / "tests" / "test_validate_execution_slice.py")], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
