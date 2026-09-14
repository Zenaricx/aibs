import json, tempfile, unittest
from pathlib import Path
from controller.handoff import CheckpointError, dispatch_packet, ingest_checkpoint
from controller.state_store import StateStore, freeze_execution_slice

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name)
        frozen={"objective":"x"}; digest,_=freeze_execution_slice(frozen)
        self.record={"work_order_id":"WO","execution_slice_id":"ES","execution_slice_hash":digest,"repository_identifier":"Zenaricx/aibs","authorised_base_commit":"b"*40,"run_id":"r","state":"ADMITTED","transition_history":[],"created_at":"t","candidate_worktree":"C:/candidate","candidate_head":"b"*40,"source_head":"b"*40}
        StateStore(self.root).write(self.record); StateStore(self.root).write_evidence("execution-slice.json",frozen)
    def tearDown(self): self.t.cleanup()
    def env(self, seq=1): return {"schema_version":"0.1","kind":"execution_checkpoint","sequence":seq,"provenance":{k:self.record[k] for k in ("work_order_id","execution_slice_id","execution_slice_hash","repository_identifier","authorised_base_commit","run_id")},"checkpoint":{"completed_work":[],"tests_run":[],"remaining_failures":[],"discoveries":[],"base_commit":"b"*40,"candidate_commit":"b"*40,"next_action":"continue","status":"IN_PROGRESS"}}
    def test_ingest_duplicate_and_stale(self):
        e=self.env(); self.assertEqual(ingest_checkpoint(self.root,e),e); self.assertEqual(ingest_checkpoint(self.root,e),e)
        with self.assertRaises(CheckpointError): ingest_checkpoint(self.root,self.env(0))
    def test_mismatch_rejected(self):
        e=self.env(); e["provenance"]["run_id"]="other"
        with self.assertRaises(CheckpointError): ingest_checkpoint(self.root,e)
    def test_sequence_conflict_rejected(self):
        ingest_checkpoint(self.root,self.env()); e=self.env(); e["checkpoint"]["next_action"]="different"
        with self.assertRaises(CheckpointError): ingest_checkpoint(self.root,e)

if __name__ == '__main__': unittest.main()
