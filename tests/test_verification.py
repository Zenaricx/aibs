import subprocess, sys, tempfile, unittest
from pathlib import Path
from controller.state_store import StateStore, freeze_execution_slice
from controller.verification import VerificationError, execute_and_verify

class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); self.candidate=self.root/'candidate'; self.state=self.root/'state'; self.candidate.mkdir()
        def git(*a):
            r=subprocess.run(['git','-C',str(self.candidate),*a],capture_output=True,text=True,check=False)
            self.assertEqual(r.returncode,0,r.stderr); return r.stdout.strip()
        git('init','-q'); git('config','user.email','aibs@example.test'); git('config','user.name','AIBS Test')
        (self.candidate/'file.txt').write_text('base\n'); git('add','file.txt'); git('commit','-q','-m','base'); self.base=git('rev-parse','HEAD')
        (self.candidate/'file.txt').write_text('changed\n'); git('commit','-qam','worker change'); self.head=git('rev-parse','HEAD')
        self.doc={'schema_version':'0.1','objective':'verify','repository':{'base_commit':self.base},'scope':{'allowed_paths':['file.txt'],'forbidden_paths':['secret/**']},'acceptance':{'commands':[f'"{sys.executable}" -c "print(1)"'],'must_pass':True},'timebox':{'max_minutes':1}}
        digest,_=freeze_execution_slice(self.doc)
        self.record={'work_order_id':'WO','execution_slice_id':'ES','execution_slice_hash':digest,'repository_identifier':'Zenaricx/aibs','authorised_base_commit':self.base,'run_id':'r','state':'ADMITTED','transition_history':[],'created_at':'t','candidate_worktree':str(self.candidate),'candidate_head':self.base,'source_head':self.base}
        store=StateStore(self.state); store.write(self.record); store.write_evidence('execution-slice.json',self.doc)
    def tearDown(self): self.t.cleanup()
    def test_real_worker_commit_verifies_and_advances(self):
        result=execute_and_verify(self.state); self.assertEqual(result['candidate_commit'],self.head); self.assertEqual(StateStore(self.state).read()['state'],'CANDIDATE_READY')
    def test_forbidden_change_fails_closed(self):
        (self.candidate/'secret.txt').write_text('x\n'); subprocess.run(['git','-C',str(self.candidate),'add','.']); subprocess.run(['git','-C',str(self.candidate),'commit','-qm','bad'])
        with self.assertRaises(VerificationError): execute_and_verify(self.state)
        self.assertEqual(StateStore(self.state).read()['state'],'FAILED')

if __name__=='__main__': unittest.main()
