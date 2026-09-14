import tempfile
import unittest
from pathlib import Path

from controller.state_store import StateStore
from controller.status import StatusError, build_status


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.record = {
            "work_order_id": "WO", "execution_slice_id": "ES", "execution_slice_hash": "a" * 64,
            "repository_identifier": "Zenaricx/aibs", "authorised_base_commit": "b" * 40,
            "run_id": "run", "state": "ADMITTED", "transition_history": [], "created_at": "t",
            "candidate_worktree": "C:/candidate", "candidate_head": "b" * 40, "source_head": "b" * 40,
        }
        self.store = StateStore(self.root)
        self.store.write(self.record)

    def tearDown(self):
        self.temp.cleanup()

    def test_reconstructs_provenance_and_next_action_without_mutation(self):
        before = sorted(path.name for path in self.root.iterdir())
        result = build_status(self.root)
        self.assertEqual(result["provenance"]["run_id"], "run")
        self.assertEqual(result["candidate"]["candidate_head"], "b" * 40)
        self.assertEqual(result["next_action"], "dispatch the candidate to the Implementer")
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), before)

    def test_checkpoint_next_action_is_authoritative_worker_evidence(self):
        self.store.write_evidence("checkpoint.json", {"sequence": 1, "checkpoint": {"next_action": "continue implementation"}})
        self.assertEqual(build_status(self.root)["next_action"], "continue implementation")

    def test_terminal_lifecycle_state_overrides_historical_checkpoint_action(self):
        self.record["state"] = "ACCEPTED"
        self.store.write(self.record)
        self.store.write_evidence("checkpoint.json", {"sequence": 1, "checkpoint": {"next_action": "verify"}})
        self.assertEqual(build_status(self.root)["next_action"], "complete")

    def test_reports_available_evidence(self):
        self.store.write_evidence("review-packet.json", {})
        result = build_status(self.root)
        self.assertTrue(result["evidence"]["review-packet"])

    def test_missing_lifecycle_is_rejected_without_creating_state(self):
        empty = Path(self.temp.name) / "missing"
        with self.assertRaises(StatusError):
            build_status(empty)
        self.assertFalse(empty.exists())


if __name__ == "__main__":
    unittest.main()
