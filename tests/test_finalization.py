import tempfile
import unittest
import json
from pathlib import Path

from controller.finalization import FinalizationError, record_owner_decision
from controller.state_store import StateStore


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.record = {"work_order_id":"WO","execution_slice_id":"ES","execution_slice_hash":"a"*64,"repository_identifier":"Zenaricx/aibs","authorised_base_commit":"b"*40,"run_id":"run","state":"CANDIDATE_READY","transition_history":[],"created_at":"t"}
        self.store = StateStore(self.root)
        self.store.write(self.record)
        self.store.acquire("run")

    def tearDown(self):
        self.temp.cleanup()

    def test_accept_persists_terminal_state_then_releases_lock(self):
        result = record_owner_decision(self.root, "accept")
        self.assertEqual(result["state"], "ACCEPTED")
        self.assertFalse(self.store.lock_path.exists())
        self.assertEqual(
            json.loads((self.root / "owner-decision.json").read_text(encoding="utf-8")),
            {"decision": "ACCEPTED", "run_id": "run"},
        )

    def test_reject_persists_terminal_state_then_releases_lock(self):
        result = record_owner_decision(self.root, "reject")
        self.assertEqual(result["state"], "REJECTED")
        self.assertFalse(self.store.lock_path.exists())

    def test_non_candidate_ready_state_is_rejected_without_releasing_lock(self):
        self.record["state"] = "VERIFYING"
        self.store.write(self.record)
        with self.assertRaises(FinalizationError):
            record_owner_decision(self.root, "accept")
        self.assertTrue(self.store.lock_path.exists())

    def test_matching_decision_resumes_from_review_required(self):
        self.record["state"] = "REVIEW_REQUIRED"
        self.store.write(self.record)
        self.store.write_evidence("owner-decision.json", {"decision": "ACCEPTED", "run_id": "run"})
        result = record_owner_decision(self.root, "accept")
        self.assertEqual(result["state"], "ACCEPTED")
        self.assertFalse(self.store.lock_path.exists())

    def test_conflicting_decision_is_rejected_without_releasing_lock(self):
        self.store.write_evidence("owner-decision.json", {"decision": "REJECTED", "run_id": "run"})
        with self.assertRaises(FinalizationError):
            record_owner_decision(self.root, "accept")
        self.assertTrue(self.store.lock_path.exists())
