import json, tempfile, unittest
from pathlib import Path
from controller.review_packet import ReviewPacketError, build_review_packet, write_review_packet
from controller.state_store import StateStore, freeze_execution_slice

class ReviewPacketTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); doc={"objective":"x"}; digest,_=freeze_execution_slice(doc)
        self.record={"work_order_id":"WO","execution_slice_id":"ES","execution_slice_hash":digest,"repository_identifier":"Zenaricx/aibs","authorised_base_commit":"a"*40,"run_id":"r","state":"CANDIDATE_READY","transition_history":[],"created_at":"t","candidate_worktree":"C:/candidate","candidate_head":"b"*40,"source_head":"a"*40}
        store=StateStore(self.root); store.write(self.record); store.write_evidence("execution-slice.json",doc); store.write_evidence("verification.json",{"candidate_commit":"b"*40,"changed_paths":[],"commands":[],"status":"PASS"})
    def tearDown(self): self.t.cleanup()
    def test_packet_is_deterministic_and_external(self):
        first=build_review_packet(self.root); second=build_review_packet(self.root); self.assertEqual(first,second); write_review_packet(self.root); self.assertTrue((self.root/'review-packet.json').exists()); self.assertFalse((self.root/'review-packet.json').is_relative_to(Path('C:/candidate')))
    def test_non_ready_run_rejected(self):
        record=StateStore(self.root).read(); record['state']='ADMITTED'; StateStore(self.root).write(record)
        with self.assertRaises(ReviewPacketError): build_review_packet(self.root)

if __name__=='__main__': unittest.main()
