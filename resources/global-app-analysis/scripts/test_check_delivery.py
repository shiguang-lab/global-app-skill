import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_delivery import file_hash, revision


class DeliveryGateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.facts = self.root / "flow.mmd"
        self.facts.write_text("flowchart TD\nA --> B\n")
        self.report = self.root / "report.html"
        self.report.write_text("<h1>Report</h1>")
        (self.root / "scope.json").write_text(json.dumps({
            "h5_in_scope": True, "h5_evidence": "scope.md#L1",
        }))
        (self.root / "scope.md").write_text("App uses a WebView.\nVerified subset.\n")
        (self.root / "review.md").write_text("Business review\nPage review\nH5 review\n")
        (self.root / "report-review.md").write_text("Format\nStructure\nContent\nUI\n")
        (self.root / "runtime.md").write_text("Phone screen\nHost attempt failed\n")
        version = self.current_revision()
        surfaces = ["business", "pages", "h5"]
        results = {area: {"method": "isolated", "status": "passed", "evidence": f"review.md#L{i}"}
                   for i, area in enumerate(surfaces, 1)}
        self.record = {
            "targets": ["research"],
            "facts": [self.facts.name],
            "scope": "scope.json",
            "rounds": [{"id": str(i), "revision": version, "surfaces": surfaces, "results": copy.deepcopy(results)}
                       for i in (1, 2)],
            "issues": {},
            "delivery": {
                "revision": version,
                "partial": False,
                "artifacts": [{"target": "research", "path": self.report.name, "sha256": file_hash(self.report),
                               "checks": {f"10.{i}": f"report-review.md#L{i}" for i in range(1, 5)}}],
            },
        }

    def current_revision(self):
        return revision(self.root, [self.facts.name], "scope.json", "scope.md")

    def run_gate(self, phase, *args):
        record = self.root / "review.json"
        record.write_text(json.dumps(self.record))
        return subprocess.run([sys.executable, str(Path(__file__).with_name("check_delivery.py")),
                               phase, str(record), *args], capture_output=True, text=True)

    def test_one_round_or_incomplete_round_cannot_release(self):
        second = self.record["rounds"].pop()
        self.assertIn("separate re-review", self.run_gate("review").stderr)
        second["results"].pop("h5")
        self.record["rounds"].append(second)
        self.assertIn("include every area", self.run_gate("review").stderr)

    def test_scope_catches_omitted_h5_even_if_plans_and_results_match(self):
        for wave in self.record["rounds"]:
            wave["surfaces"] = ["business", "pages"]
            del wave["results"]["h5"]
        self.assertIn("every area for the current scope", self.run_gate("review").stderr)

    def test_incomplete_round_on_an_old_revision_does_not_count(self):
        first = self.record["rounds"][0]
        first.update(revision="old", surfaces=["business", "pages"])
        del first["results"]["h5"]
        self.assertIn("two separate rounds covering every area", self.run_gate("review").stderr)
        first["surfaces"] = ["business"]
        del first["results"]["pages"]
        self.assertIn("include every area", self.run_gate("review").stderr)

    def test_review_rejects_missing_evidence_file_or_line(self):
        result = self.record["rounds"][0]["results"]["business"]
        result["evidence"] = "absent.md#L1"
        self.assertIn("evidence file not found", self.run_gate("review").stderr)
        result["evidence"] = "review.md#L99"
        self.assertIn("evidence line not found", self.run_gate("review").stderr)

    def test_corrected_flow_requires_a_new_round_and_delivery_checks(self):
        self.facts.write_text("flowchart TD\nA --> C\n")
        self.assertIn("new review from 9.1", self.run_gate("review").stderr)
        new_round = copy.deepcopy(self.record["rounds"][-1])
        new_round.update(id="3", revision=self.current_revision())
        self.record["rounds"].append(new_round)
        self.assertEqual(self.run_gate("review").returncode, 0)
        self.assertIn("delivery checks must refer to the current facts", self.run_gate("deliver").stderr)
        self.record["delivery"]["revision"] = new_round["revision"]
        self.assertEqual(self.run_gate("deliver").returncode, 0)

    def test_login_observation_requires_host_attempt_evidence_before_partial_release(self):
        issue = {"status": "open", "evidence": "runtime.md#L1"}
        self.record["issues"]["login"] = issue
        self.record["partial"] = {"reason": "blocked", "included": "scope.md#L2"}
        self.record["rounds"][-1]["results"]["business"]["status"] = "partial_passed"
        self.assertIn("close all issues", self.run_gate("review").stderr)
        self.assertIn("evidenced blockers", self.run_gate("review", "--partial").stderr)
        issue.update(status="blocked", layer="native", resume="Provide a test account")
        self.assertIn("attempt evidence", self.run_gate("review", "--partial").stderr)
        issue["attempt"] = "missing-attempt.md"
        self.assertIn("evidence file not found", self.run_gate("review", "--partial").stderr)
        issue["attempt"] = "runtime.md#L2"
        self.assertEqual(self.run_gate("review", "--partial").returncode, 0)
        self.assertIn("selected delivery type", self.run_gate("deliver", "--partial").stderr)
        self.record["delivery"]["partial"] = True
        self.assertEqual(self.run_gate("deliver", "--partial").returncode, 0)

    def test_report_needs_all_checks_and_current_file_hash(self):
        artifact = self.record["delivery"]["artifacts"][0]
        check = artifact["checks"].pop("10.3")
        self.assertIn("missing a required report", self.run_gate("deliver").stderr)
        artifact["checks"]["10.3"] = "nonexistent-report-review.md"
        self.assertIn("evidence file not found", self.run_gate("deliver").stderr)
        artifact["checks"]["10.3"] = check
        self.report.write_text("<h1>Updated report</h1>")
        self.assertIn("artifact changed", self.run_gate("deliver").stderr)

    def test_existing_report_needs_a_current_delivery_record(self):
        delivery = self.record.pop("delivery")
        self.assertIn("deliver refused", self.run_gate("deliver").stderr)
        self.record["delivery"] = delivery
        self.assertEqual(self.run_gate("deliver").returncode, 0)


if __name__ == "__main__":
    unittest.main()
