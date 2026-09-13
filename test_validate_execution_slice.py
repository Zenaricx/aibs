import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_execution_slice.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run_validator(path: Path):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class ValidatorContractTests(unittest.TestCase):
    def assertFixtureExit(self, name: str, expected: int):
        result = run_validator(FIXTURES / name)
        self.assertEqual(
            result.returncode,
            expected,
            msg=f"{name}: stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        return result

    def test_t01_valid_fixture_passes(self):
        result = self.assertFixtureExit("valid_execution_slice.json", 0)
        self.assertIn("PASS", result.stdout)

    def test_t02_malformed_json_is_exit_2(self):
        self.assertFixtureExit("invalid_malformed.json", 2)

    def test_t03_missing_objective(self):
        self.assertFixtureExit("invalid_missing_objective.json", 1)

    def test_t04_blank_objective(self):
        self.assertFixtureExit("invalid_blank_objective.json", 1)

    def test_t05_unknown_top_level_key(self):
        self.assertFixtureExit("invalid_unknown_top_level.json", 1)

    def test_t06_missing_nested_required_key(self):
        data = json.loads((FIXTURES / "valid_execution_slice.json").read_text())
        del data["repository"]["identifier"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            p = Path(f.name)
        try:
            self.assertEqual(run_validator(p).returncode, 1)
        finally:
            p.unlink(missing_ok=True)

    def test_t07_bad_base_commit(self):
        self.assertFixtureExit("invalid_bad_base_commit.json", 1)

    def test_t08_short_base_commit(self):
        self.assertFixtureExit("invalid_short_base_commit.json", 1)

    def test_t09_empty_allowed_paths(self):
        self.assertFixtureExit("invalid_empty_allowed_paths.json", 1)

    def test_t10_absolute_path(self):
        self.assertFixtureExit("invalid_absolute_path.json", 1)

    def test_t11_windows_drive_path(self):
        self.assertFixtureExit("invalid_windows_drive_path.json", 1)

    def test_t12_path_traversal(self):
        self.assertFixtureExit("invalid_path_traversal.json", 1)

    def test_t13_backslash_path(self):
        self.assertFixtureExit("invalid_backslash_path.json", 1)

    def test_t14_empty_acceptance_commands(self):
        self.assertFixtureExit("invalid_empty_acceptance_commands.json", 1)

    def test_t15_blank_acceptance_command(self):
        self.assertFixtureExit("invalid_blank_acceptance_command.json", 1)

    def test_t16_must_pass_false(self):
        self.assertFixtureExit("invalid_must_pass_false.json", 1)

    def test_t17_timebox_zero(self):
        self.assertFixtureExit("invalid_timebox_zero.json", 1)

    def test_t18_timebox_121(self):
        self.assertFixtureExit("invalid_timebox_121.json", 1)

    def test_t19_empty_stop_conditions(self):
        self.assertFixtureExit("invalid_empty_stop_conditions.json", 1)

    def test_t20_authority_true(self):
        self.assertFixtureExit("invalid_authority_merge_true.json", 1)

    def test_t21_missing_authority_field(self):
        self.assertFixtureExit("invalid_missing_authority_field.json", 1)

    def test_t22_checkpoint_not_required(self):
        self.assertFixtureExit("invalid_checkpoint_not_required.json", 1)

    def test_t23_checkpoint_missing_field(self):
        self.assertFixtureExit("invalid_checkpoint_missing_field.json", 1)

    def test_t24_checkpoint_extra_field_allowed(self):
        self.assertFixtureExit("valid_checkpoint_extra_field.json", 0)

    def test_t25_missing_file_is_exit_2(self):
        result = run_validator(FIXTURES / "this_file_does_not_exist.json")
        self.assertEqual(result.returncode, 2)

    def test_t26_input_is_not_modified(self):
        fixture = FIXTURES / "valid_execution_slice.json"
        before = hashlib.sha256(fixture.read_bytes()).hexdigest()
        result = run_validator(fixture)
        after = hashlib.sha256(fixture.read_bytes()).hexdigest()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
