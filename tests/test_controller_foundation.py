import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from controller.git_candidate import GitCandidateError, create_candidate, repository_identity_matches
from controller.execution import ExecutionError, acceptance_passed, changed_paths, run_acceptance_commands, validate_changed_paths
from controller.dispatch import DispatchError, build_dispatch, dispatch_hash, persist_dispatch
from controller.evidence import build_verification_evidence, load_verification_evidence, persist_verification_evidence
from controller.review import ReviewError, build_review_record
from controller.publish import PublishError, validate_publication_inputs
from controller.status import StatusError, read_run_status
from controller.lifecycle import InvalidTransition, LifecycleState, transition
from controller.state_store import LockError, StateStore, StateStoreError, freeze_execution_slice
from tools.aibs_controller import _load_validated_slice, main, validate_operational_paths
from tools.aibs_verify_candidate import main as verify_candidate
from tools.aibs_record_review import main as record_review
from tools.aibs_seal_candidate import main as seal_candidate_tool


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

    def test_changed_paths_includes_tracked_and_untracked_paths(self):
        repo, _ = self.init_repo()
        (repo / "file.txt").write_text("changed\n", encoding="utf-8")
        (repo / "new.txt").write_text("new\n", encoding="utf-8")
        self.assertEqual(changed_paths(repo), ["file.txt", "new.txt"])

    def test_changed_paths_are_checked_against_scope(self):
        validate_changed_paths(["controller/run.py"], ["controller/**"], ["docs/**"])
        with self.assertRaisesRegex(ExecutionError, "unauthorised"):
            validate_changed_paths(["tools/run.py"], ["controller/**"], ["docs/**"])
        with self.assertRaisesRegex(ExecutionError, "protected"):
            validate_changed_paths(["docs/run.md"], ["docs/**"], ["docs/**"])

    def test_acceptance_evidence_stops_after_first_failure(self):
        repo, _ = self.init_repo()
        evidence = run_acceptance_commands(
            repo, ["echo first", "cmd /c exit 3", "cmd /c exit 4"]
        )
        self.assertEqual([item.returncode for item in evidence], [0, 3])
        self.assertEqual(evidence[0].stdout, "first\n")
        self.assertFalse(acceptance_passed(evidence))

    def test_acceptance_evidence_allows_all_passing_commands(self):
        repo, _ = self.init_repo()
        evidence = run_acceptance_commands(repo, ["echo ok"])
        self.assertTrue(acceptance_passed(evidence))

    def prepare_admitted_verification(self, repo, document):
        state = self.root / "state"
        store = StateStore(state)
        record = self.valid_record()
        base_commit = git(repo, "rev-parse", "HEAD")
        document["repository"]["base_commit"] = base_commit
        record["authorised_base_commit"] = base_commit
        record["execution_slice_hash"] = freeze_execution_slice(document)[0]
        store.acquire("r")
        store.write(record)
        record = store.transition(record, LifecycleState.READY, timestamp="t")
        store.transition(record, LifecycleState.ADMITTED, timestamp="t")
        slice_path = self.root / "slice.json"
        slice_path.write_text(json.dumps(document), encoding="utf-8")
        return state, slice_path

    def test_candidate_verification_routes_passing_candidate_to_review(self):
        repo, _ = self.init_repo()
        (repo / "file.txt").write_text("candidate change\n", encoding="utf-8")
        document = self.sample_slice()
        document["scope"]["allowed_paths"] = ["file.txt"]
        document["acceptance"]["commands"] = ["echo verified"]
        state, slice_path = self.prepare_admitted_verification(repo, document)
        self.assertEqual(verify_candidate([str(slice_path), "--state-root", str(state), "--candidate-worktree", str(repo), "--run-id", "r"]), 0)
        self.assertEqual(StateStore(state).read()["state"], "REVIEW_REQUIRED")
        self.assertFalse((state / "active-run.lock").exists())
        self.assertEqual(load_verification_evidence(state)["outcome"], "PASSED")

    def test_candidate_verification_records_failed_acceptance(self):
        repo, _ = self.init_repo()
        document = self.sample_slice()
        document["acceptance"]["commands"] = ["cmd /c exit 7"]
        state, slice_path = self.prepare_admitted_verification(repo, document)
        self.assertEqual(verify_candidate([str(slice_path), "--state-root", str(state), "--candidate-worktree", str(repo), "--run-id", "r"]), 1)
        self.assertEqual(StateStore(state).read()["state"], "FAILED")
        self.assertFalse((state / "active-run.lock").exists())

    def test_candidate_verification_rejects_a_replaced_slice(self):
        repo, _ = self.init_repo()
        document = self.sample_slice()
        state, slice_path = self.prepare_admitted_verification(repo, document)
        document["scope"]["allowed_paths"] = ["**"]
        slice_path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(StateStoreError, "does not match admitted"):
            verify_candidate([str(slice_path), "--state-root", str(state), "--candidate-worktree", str(repo), "--run-id", "r"])
        self.assertEqual(StateStore(state).read()["state"], "ADMITTED")
        self.assertTrue((state / "active-run.lock").exists())

    def test_dispatch_packet_is_hash_bound_and_minimal(self):
        repo, _ = self.init_repo()
        document = self.sample_slice()
        state, _ = self.prepare_admitted_verification(repo, document)
        packet = build_dispatch(document, StateStore(state).read(), repo)
        self.assertEqual(packet["run_id"], "r")
        self.assertEqual(packet["repository"]["candidate_worktree"], str(repo.resolve()))
        self.assertEqual(packet["task"]["objective"], document["objective"])
        self.assertEqual(packet["execution_slice_hash"], freeze_execution_slice(document)[0])
        self.assertEqual(len(dispatch_hash(packet)), 64)

    def test_dispatch_requires_an_unchanged_admitted_candidate(self):
        repo, _ = self.init_repo()
        document = self.sample_slice()
        state, _ = self.prepare_admitted_verification(repo, document)
        (repo / "file.txt").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(DispatchError, "not clean"):
            build_dispatch(document, StateStore(state).read(), repo)

    def test_dispatch_persistence_is_idempotent_but_cannot_be_replaced(self):
        repo, _ = self.init_repo()
        document = self.sample_slice()
        state, _ = self.prepare_admitted_verification(repo, document)
        packet = build_dispatch(document, StateStore(state).read(), repo)
        first = persist_dispatch(state, packet)
        self.assertEqual(persist_dispatch(state, packet), first)
        replacement = dict(packet)
        replacement["run_id"] = "different"
        with self.assertRaisesRegex(DispatchError, "different dispatch"):
            persist_dispatch(state, replacement)

    def test_owner_acceptance_requires_passing_evidence_and_records_decision(self):
        repo, _ = self.init_repo()
        (repo / "file.txt").write_text("candidate change\n", encoding="utf-8")
        document = self.sample_slice()
        document["scope"]["allowed_paths"] = ["file.txt"]
        document["acceptance"]["commands"] = ["echo verified"]
        state, slice_path = self.prepare_admitted_verification(repo, document)
        self.assertEqual(verify_candidate([str(slice_path), "--state-root", str(state), "--candidate-worktree", str(repo), "--run-id", "r"]), 0)
        self.assertEqual(record_review(["--state-root", str(state), "--run-id", "r", "--reviewer", "owner", "--decision", "accept"]), 0)
        self.assertEqual(StateStore(state).read()["state"], "ACCEPTED")
        review = json.loads((state / "review.json").read_text(encoding="utf-8"))
        self.assertEqual(review["reviewer"], "owner")
        self.assertEqual(review["decision"], "accept")

    def test_review_rejects_non_passing_evidence(self):
        record = self.valid_record()
        record["state"] = "REVIEW_REQUIRED"
        evidence = build_verification_evidence(record, "FAILED", [], [])
        with self.assertRaisesRegex(ReviewError, "only passing"):
            build_review_record(record, evidence, "owner", "accept")

    def test_owner_decision_resumes_from_owner_acceptance(self):
        repo, _ = self.init_repo()
        (repo / "file.txt").write_text("candidate change\n", encoding="utf-8")
        document = self.sample_slice()
        document["scope"]["allowed_paths"] = ["file.txt"]
        document["acceptance"]["commands"] = ["echo verified"]
        state, slice_path = self.prepare_admitted_verification(repo, document)
        self.assertEqual(verify_candidate([str(slice_path), "--state-root", str(state), "--candidate-worktree", str(repo), "--run-id", "r"]), 0)
        store = StateStore(state)
        record = store.read()
        evidence = load_verification_evidence(state)
        review = build_review_record(record, evidence, "owner", "accept")
        from controller.review import persist_review_record
        persist_review_record(state, review)
        store.transition(record, LifecycleState.OWNER_ACCEPTANCE, timestamp="t")
        self.assertEqual(record_review(["--state-root", str(state), "--run-id", "r", "--reviewer", "owner", "--decision", "accept"]), 0)
        self.assertEqual(StateStore(state).read()["state"], "ACCEPTED")

    def test_status_aggregates_lifecycle_and_optional_records_read_only(self):
        state = self.root / "state"
        store = StateStore(state)
        record = self.valid_record()
        store.write(record)
        status = read_run_status(state, "r")
        self.assertEqual(status["state"], "DRAFT")
        self.assertIsNone(status["verification"])
        self.assertEqual(set(status), {"run_id", "state", "execution_slice_hash", "repository_identifier", "authorised_base_commit", "verification", "review", "seal", "publication"})

    def test_status_rejects_mismatched_optional_record(self):
        state = self.root / "state"
        store = StateStore(state)
        store.write(self.valid_record())
        (state / "review.json").write_text(json.dumps({"run_id": "other", "execution_slice_hash": "a" * 64}), encoding="utf-8")
        with self.assertRaisesRegex(StatusError, "does not match lifecycle"):
            read_run_status(state)

    def test_status_does_not_create_missing_state(self):
        state = self.root / "missing"
        with self.assertRaises(StatusError):
            read_run_status(state)
        self.assertFalse(state.exists())

    def test_accepted_candidate_is_sealed_to_a_local_branch_and_commit(self):
        repo, _ = self.init_repo()
        (repo / "file.txt").write_text("candidate change\n", encoding="utf-8")
        document = self.sample_slice()
        document["scope"]["allowed_paths"] = ["file.txt"]
        document["acceptance"]["commands"] = ["echo verified"]
        state, slice_path = self.prepare_admitted_verification(repo, document)
        self.assertEqual(verify_candidate([str(slice_path), "--state-root", str(state), "--candidate-worktree", str(repo), "--run-id", "r"]), 0)
        self.assertEqual(record_review(["--state-root", str(state), "--run-id", "r", "--reviewer", "owner", "--decision", "accept"]), 0)
        self.assertEqual(seal_candidate_tool([str(slice_path), "--state-root", str(state), "--candidate-worktree", str(repo), "--run-id", "r", "--branch", "aibs/candidate/r"]), 0)
        self.assertEqual(git(repo, "branch", "--show-current"), "aibs/candidate/r")
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        sealed = json.loads((state / "seal.json").read_text(encoding="utf-8"))
        self.assertEqual(sealed["branch"], "aibs/candidate/r")
        self.assertEqual(sealed["candidate_commit"], git(repo, "rev-parse", "HEAD"))
        self.assertEqual(validate_publication_inputs(StateStore(state).read(), sealed, repo, "phase-a/r"), repo.resolve())
        with self.assertRaisesRegex(PublishError, "phase-a/ prefix"):
            validate_publication_inputs(StateStore(state).read(), sealed, repo, "main")


if __name__ == "__main__":
    unittest.main()
