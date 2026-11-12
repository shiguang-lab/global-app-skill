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
        self.set_h5(True)
        (self.root / "scope.md").write_text("App uses a WebView.\nVerified subset.\n")
        (self.root / "report-review.md").write_text("Format\nStructure\nContent\nUI\n")
        (self.root / "runtime.md").write_text("Phone screen\nOriginal host unavailable\n")
        self.record = {
            "targets": ["research"],
            "facts": [self.facts.name],
            "scope": "scope.json",
            "issues": {},
            "delivery": {
                "revision": self.current_revision(),
                "partial": False,
                "artifacts": [{"target": "research", "path": self.report.name, "sha256": file_hash(self.report),
                               "checks": {f"10.{i}": f"report-review.md#L{i}" for i in range(1, 5)}}],
            },
        }
        self.run_gate("init").check_returncode()

    def set_h5(self, enabled):
        items = {"business": {"credit": "Submit a credit application", "login": "Continue after sign-in"},
                 "pages": {"home": "Inspect the home page"}}
        if enabled:
            items["h5"] = {"withdraw": "Submit the loan from the H5 form"}
        (self.root / "scope.json").write_text(json.dumps({
            "h5_in_scope": enabled, "h5_evidence": "scope.md#L1", "review_items": items,
        }))

    def current_revision(self):
        return revision(self.root, [self.facts.name], "scope.json", "scope.md")

    def run_gate(self, phase, *args):
        record = self.root / "review.json"
        record.write_text(json.dumps(self.record))
        return subprocess.run([sys.executable, str(Path(__file__).with_name("check_delivery.py")),
                               phase, str(record), *args], capture_output=True, text=True)

    def begin(self):
        return json.loads(self.run_gate("begin-review").stdout)

    def write_results(self, wave, evidence=None, blocked=None):
        name = f"review-{wave['id']}.md"
        if evidence is None:
            (self.root / name).write_text(f"Review {wave['id']}\nBusiness\nPages\nH5\n")
            evidence = f"{name}#L2"
        results = {
            area: {"method": "in_session", "status": "passed", "evidence": evidence,
                   "items": {key: {"status": "passed", "assessment": "Prior evidence covers the current item.",
                                   "evidence": "runtime.md#L1"} for key in wave["items"][area]}}
            for area in wave["surfaces"]
        }
        if blocked is not None:
            results["business"]["status"] = "partial_passed"
            results["business"]["items"]["login"] = {
                "status": "blocked", "assessment": "The post-login path lacks a required test input.",
                "evidence": "runtime.md#L1", "issue": "login", "unavailable_paths": blocked,
            }
        (self.root / "results.json").write_text(json.dumps(results))

    def finish_review(self, wave):
        return self.run_gate("finish-review", "--id", str(wave["id"]), "--results", "results.json")

    def seal(self, *, blocked=None):
        wave = self.begin()
        self.write_results(wave, blocked=blocked)
        self.finish_review(wave).check_returncode()
        return wave

    def retry(self, *keys, outcome="failed", path=None):
        args = [item for key in keys for item in ("--key", key)]
        if path:
            args += ["--path", path]
        start = self.run_gate("reserve", *args, "--action", "Check the observed issue")
        start.check_returncode()
        attempt = json.loads(start.stdout)["id"]
        evidence = f"attempt-{attempt}.txt"
        (self.root / evidence).write_text(f"Attempt {attempt}: {outcome}\n")
        self.run_gate("finish", "--id", str(attempt), "--outcome", outcome, "--evidence", evidence).check_returncode()
        return attempt

    def test_editable_rounds_do_not_count_and_rounds_cannot_overlap(self):
        self.record["rounds"] = [{"id": 1}, {"id": 2}]
        self.assertIn("separate re-review", self.run_gate("review").stderr)
        wave = self.begin()
        self.assertIn("finish or cancel", self.run_gate("begin-review").stderr)
        self.write_results(wave)
        self.finish_review(wave).check_returncode()
        self.assertIn("separate re-review", self.run_gate("review").stderr)

    def test_round_requires_all_areas_and_fresh_distinct_evidence(self):
        first = self.seal()
        wave = self.begin()
        self.write_results(wave, evidence=f"review-{first['id']}.md#L2")
        self.assertIn("after the checkpoint began", self.finish_review(wave).stderr)
        (self.root / f"review-{first['id']}.md").touch()
        self.assertIn("its own newly recorded evidence", self.finish_review(wave).stderr)
        self.write_results({**wave, "surfaces": ["business", "pages"]})
        self.assertIn("include every planned area", self.finish_review(wave).stderr)
        self.write_results(wave, evidence="absent.md#L1")
        self.assertIn("evidence file not found", self.finish_review(wave).stderr)
        self.write_results(wave, evidence="runtime.md#L99")
        self.assertIn("evidence line not found", self.finish_review(wave).stderr)
        self.write_results(wave)
        self.finish_review(wave).check_returncode()
        self.assertEqual(self.run_gate("review").returncode, 0)

    def test_new_h5_scope_requires_two_rounds_that_cover_it(self):
        self.set_h5(False)
        self.seal()
        self.set_h5(True)
        self.seal()
        self.assertIn("two separate rounds covering every area", self.run_gate("review").stderr)
        self.seal()
        self.assertEqual(self.run_gate("review").returncode, 0)

    def test_new_item_in_existing_area_also_requires_two_rounds(self):
        self.seal()
        scope = self.root / "scope.json"
        content = json.loads(scope.read_text())
        content["review_items"]["business"]["retry"] = "Retry when the offer fails to load"
        scope.write_text(json.dumps(content))
        self.seal()
        self.assertIn("covering every area and item", self.run_gate("review").stderr)
        self.seal()
        self.assertEqual(self.run_gate("review").returncode, 0)

    def test_corrected_flow_requires_a_new_round_and_delivery_checks(self):
        self.seal()
        self.seal()
        self.facts.write_text("flowchart TD\nA --> C\n")
        self.assertIn("new review from 9.1", self.run_gate("review").stderr)
        self.seal()
        self.assertEqual(self.run_gate("review").returncode, 0)
        self.assertIn("delivery checks must refer to the current facts", self.run_gate("deliver").stderr)
        self.record["delivery"]["revision"] = self.current_revision()
        self.assertEqual(self.run_gate("deliver").returncode, 0)

    def test_corrected_round_cannot_omit_unchanged_items(self):
        self.seal()
        self.facts.write_text("flowchart TD\nA --> C\n")
        wave = self.begin()
        self.write_results(wave)
        path = self.root / "results.json"
        results = json.loads(path.read_text())
        del results["business"]["items"]["login"]
        path.write_text(json.dumps(results))
        self.assertIn("exactly the planned review item IDs", self.finish_review(wave).stderr)
        self.assertIn("finish the open review", self.run_gate("review").stderr)
        self.write_results(wave)
        self.finish_review(wave).check_returncode()
        self.assertEqual(self.run_gate("review").returncode, 0)

    def test_exhausted_batch_waits_and_each_new_batch_needs_approval(self):
        key = "technical:loan"
        self.seal()
        self.seal()
        for _ in range(2):
            self.retry(key, "evidence:task")
        denied = self.run_gate("reserve", "--key", key, "--key", "evidence:task", "--action", "Try next hypothesis")
        self.assertEqual(denied.returncode, 3)
        self.assertIn("wait for the user's decision", self.run_gate("deliver").stderr)
        self.assertIn("evidence file not found", self.run_gate("resume", "--key", key, "--evidence", "absent.txt").stderr)
        (self.root / "approval.txt").write_text("User approves one new batch for the loan case.")
        self.run_gate("resume", "--key", key, "--evidence", "approval.txt").check_returncode()
        self.retry(key, "evidence:task")
        self.retry(key)
        self.assertEqual(self.run_gate("reserve", "--key", key, "--action", "Retry").returncode, 3)
        (self.root / "copy.txt").write_bytes((self.root / "approval.txt").read_bytes())
        self.assertIn("new user approval", self.run_gate("resume", "--key", key, "--evidence", "copy.txt").stderr)
        self.assertEqual(self.run_gate("reserve", "--key", "evidence:task", "--action", "Retry").returncode, 3)

    def test_blocker_requires_distinct_original_and_isolated_host_proof(self):
        self.seal()
        issue = {
            "status": "blocked", "evidence": "runtime.md#L1", "kind": "app_host", "layer": "native",
            "resume": "Provide a test account.",
            "paths": {"original_host": {"status": "unavailable", "reason": "Original host does not expose test inputs",
                                        "evidence": "runtime.md#L2"}},
        }
        self.record["issues"]["login"] = issue
        self.record["partial"] = {"reason": "blocked", "included": "scope.md#L2"}
        proof = {"original_host": {"prerequisite": "An App test session or a supported test input",
                                   "observation": "The original host stops at the phone screen.",
                                   "evidence": "runtime.md#L2"}}
        self.seal(blocked=proof)
        self.assertIn("original host and an isolated App host", self.run_gate("review", "--partial").stderr)
        issue["paths"]["isolated_host"] = {"status": "attempted", "key": "technical:login", "attempt": 42}
        self.assertIn("completed failed attempt", self.run_gate("review", "--partial").stderr)
        issue["paths"]["isolated_host"]["attempt"] = self.retry("technical:login", path="isolated_host")
        self.assertIn("blocker changed after review", self.run_gate("review", "--partial").stderr)
        self.seal(blocked=proof)
        self.assertEqual(self.run_gate("review", "--partial").returncode, 0)
        self.assertIn("selected delivery type", self.run_gate("deliver", "--partial").stderr)
        self.record["delivery"]["partial"] = True
        self.assertEqual(self.run_gate("deliver", "--partial").returncode, 0)
        self.retry("technical:login", outcome="passed", path="isolated_host")
        self.assertIn("latest completed failed attempt", self.run_gate("deliver", "--partial").stderr)

    def test_unavailable_paths_require_item_level_review_of_prerequisites(self):
        self.seal()
        self.record["issues"]["login"] = {
            "status": "blocked", "evidence": "runtime.md#L1", "kind": "app_host", "layer": "native",
            "resume": "Provide an authorized test session.",
            "paths": {
                "original_host": {"status": "unavailable", "reason": "No authorized test session",
                                  "evidence": "runtime.md#L2"},
                "isolated_host": {"status": "unavailable", "reason": "Missing isolated test configuration",
                                  "evidence": "isolated.md"},
            },
        }
        isolated = self.root / "isolated.md"
        isolated.write_text("The test build's config loader reports missing fixture source.\n")
        self.record["partial"] = {"reason": "blocked", "included": "scope.md#L2"}
        wave = self.begin()
        proof = {"original_host": {"prerequisite": "Authorized test session",
                                   "observation": "The App has no test session and requires a phone sign-in.",
                                   "evidence": "runtime.md#L2"}}
        self.write_results(wave, blocked=proof)
        self.assertIn("reviewer must verify every unavailable path", self.finish_review(wave).stderr)
        proof["isolated_host"] = {"prerequisite": "Configured isolated fixture source",
                                  "observation": "The test build reports that no fixture source is configured.",
                                  "evidence": "runtime.md#L2"}
        self.write_results(wave, blocked=proof)
        self.assertIn("matching evidence", self.finish_review(wave).stderr)
        proof["isolated_host"]["evidence"] = "isolated.md"
        self.write_results(wave, blocked=proof)
        self.finish_review(wave).check_returncode()
        self.assertEqual(self.run_gate("review", "--partial").returncode, 0)
        isolated.write_text("Replaced after the review.\n")
        self.assertIn("checkpoint evidence changed", self.run_gate("review", "--partial").stderr)

    def test_open_retry_and_changed_evidence_stop_delivery(self):
        self.seal()
        self.seal()
        started = self.run_gate("reserve", "--key", "technical:h5", "--action", "Verify the H5 flow")
        attempt = str(json.loads(started.stdout)["id"])
        self.assertIn("result of every reserved retry", self.run_gate("check-ledger").stderr)
        self.assertIn("result of every reserved retry", self.run_gate("deliver").stderr)
        evidence = self.root / "new-result.txt"
        evidence.write_text("Observed result of the reserved retry")
        self.run_gate("finish", "--id", attempt, "--outcome", "passed", "--evidence", evidence.name).check_returncode()
        self.assertEqual(self.run_gate("check-ledger").returncode, 0)
        self.assertEqual(self.run_gate("deliver").returncode, 0)
        evidence.write_text("Overwritten outcome")
        self.assertIn("checkpoint evidence changed", self.run_gate("deliver").stderr)

    def test_report_needs_all_checks_and_current_file_hash(self):
        self.seal()
        self.seal()
        artifact = self.record["delivery"]["artifacts"][0]
        check = artifact["checks"].pop("10.3")
        self.assertIn("missing a required report", self.run_gate("deliver").stderr)
        artifact["checks"]["10.3"] = "nonexistent-report-review.md"
        self.assertIn("evidence file not found", self.run_gate("deliver").stderr)
        artifact["checks"]["10.3"] = check
        self.report.write_text("<h1>Updated report</h1>")
        self.assertIn("artifact changed", self.run_gate("deliver").stderr)

    def test_existing_report_needs_a_current_delivery_record(self):
        self.seal()
        self.seal()
        delivery = self.record.pop("delivery")
        self.assertIn("deliver refused", self.run_gate("deliver").stderr)
        self.record["delivery"] = delivery
        self.assertEqual(self.run_gate("deliver").returncode, 0)

    def test_check_ledger_needs_no_review_record(self):
        record = self.root / "not-created.json"
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("check_delivery.py")),
                                 "check-ledger", str(record)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("check-ledger passed", result.stdout)

    def test_review_record_examples_are_consistent(self):
        example = Path(__file__).resolve().parent.parent / "examples/review-record"
        record = json.loads((example / "review.json").read_text(encoding="utf-8"))
        mixed = json.loads((example / "review-mixed.json").read_text(encoding="utf-8"))
        scope = json.loads((example / "scope.json").read_text(encoding="utf-8"))
        results = json.loads((example / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(set(record), {"targets", "facts", "scope", "issues", "delivery"})
        self.assertEqual(set(mixed["targets"]), {"research", "ued"})
        self.assertEqual({item["target"] for item in mixed["delivery"]["artifacts"]}, {"research", "ued"})
        self.assertEqual(set(scope["review_items"]), set(results))
        for area, items in scope["review_items"].items():
            self.assertEqual(set(results[area]["items"]), set(items))


if __name__ == "__main__":
    unittest.main()
