import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from controller.delivery_harness import HarnessError, build_plan, load_feature, load_project, review


class DeliveryHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project_path = self.root / "project.json"
        self.feature_path = self.root / "feature.json"
        self.project = {"schema_version":"0.1","project_id":"demo","protected_surfaces":[{"name":"state","paths":["controller/**"],"review_required":True}],"test_rules":[{"paths":["tests/**"],"commands":[f'"{sys.executable}" -c "print(1)"']}],"default_test_commands":[f'"{sys.executable}" -c "print(2)"']}
        self.feature = {"schema_version":"0.1","feature_id":"F-1","objective":"test","acceptance_criteria":["works"],"out_of_scope":["nothing else"],"risk_surfaces":[],"status":"READY"}
        self.project_path.write_text(json.dumps(self.project), encoding="utf-8")
        self.feature_path.write_text(json.dumps(self.feature), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_protected_change_requires_review_and_default_tests(self):
        plan = build_plan(load_project(self.project_path), load_feature(self.feature_path), "base", "head", ["controller/state_store.py"])
        self.assertEqual(plan["risk_surfaces"], ["state"])
        self.assertTrue(plan["review_required"])
        self.assertEqual(plan["test_commands"], self.project["default_test_commands"])

    def test_test_rule_is_selected_for_changed_test(self):
        plan = build_plan(load_project(self.project_path), load_feature(self.feature_path), "base", "head", ["tests/test_x.py"])
        self.assertFalse(plan["review_required"])
        self.assertEqual(plan["test_commands"], self.project["test_rules"][0]["commands"])

    def test_declared_feature_risk_requires_review(self):
        self.feature["risk_surfaces"] = ["authority"]
        self.feature_path.write_text(json.dumps(self.feature), encoding="utf-8")
        plan = build_plan(load_project(self.project_path), load_feature(self.feature_path), "base", "head", [])
        self.assertTrue(plan["review_required"])
        self.assertEqual(plan["risk_surfaces"], ["authority"])

    def test_invalid_feature_is_rejected(self):
        self.feature.pop("objective")
        self.feature_path.write_text(json.dumps(self.feature), encoding="utf-8")
        with self.assertRaises(HarnessError):
            load_feature(self.feature_path)

    def test_checked_in_starter_records_are_valid(self):
        repository_root = Path(__file__).resolve().parents[1]
        self.assertEqual(load_project(repository_root / "aibs-project-record.json")["project_id"], "aibs")
        self.assertEqual(load_feature(repository_root / "feature-record.example.json")["status"], "READY")

    def test_review_runs_tests_and_writes_verified_packet(self):
        repository = self.root / "repo"
        repository.mkdir()
        subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
        (repository / "tests").mkdir()
        (repository / "tests" / "test_x.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repository, check=True, capture_output=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, check=True, text=True, capture_output=True).stdout.strip()
        (repository / "tests" / "test_x.py").write_text("x = 2\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-m", "candidate"], cwd=repository, check=True, capture_output=True)
        packet, packet_path = review(self.project_path, self.feature_path, repository, base, self.root / "packets")
        self.assertTrue(packet["tests_passed"])
        self.assertEqual(packet["base_commit"], base)
        self.assertTrue(packet_path.is_file())
        self.assertEqual(json.loads(packet_path.read_text(encoding="utf-8"))["feature_id"], "F-1")


if __name__ == "__main__":
    unittest.main()
