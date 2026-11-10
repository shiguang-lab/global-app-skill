"""Acquisition-to-verification requirements and Manifest parsing regressions."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

from apk_utils import sha256, write_json
import verify


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "apks").mkdir()
        self.apk = self.root / "apks/base.apk"
        with zipfile.ZipFile(self.apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"tool-output fixture")
        self.actual_version = 123
        self.version_name = "PRE: 1.2.3"

    def xml(self):
        return ('N: android=http://schemas.android.com/apk/res/android\n'
                '  E: manifest (line=1)\n'
                f'    A: android:versionCode(0x0101021b)=(type 0x10)0x{self.actual_version:x}\n'
                f'    A: android:versionName(0x0101021c)="{self.version_name}"\n'
                '    A: package="com.example.app" (Raw: "com.example.app")\n'
                '    E: application (line=2)\n'
                '      A: android:label="Child attributes must not become root attributes"\n')

    def record(self, requested=123):
        data = {"status": "downloaded_pending_identity_and_signature_verification",
                "requested_version_code": requested, "source_version_code": 123,
                "files": [{"file": "apks/base.apk", "sha256": sha256(self.apk)}],
                "declared_files": ["base.apk"]}
        write_json(self.root / "download.json", data)
        return data

    def tool(self, args, **kwargs):
        if args[0] == "aapt":
            return subprocess.CompletedProcess(args, 0, self.xml(), "")
        self.assertEqual(args[0], "apksigner")
        return subprocess.CompletedProcess(args, 0, "Signer #1 certificate SHA-256 digest: " + "a" * 64 + "\n", "")

    def run_verify(self, version=None):
        with mock.patch.object(verify, "find_tool", side_effect=lambda name, sdk: name), \
             mock.patch.object(verify.subprocess, "run", side_effect=self.tool), \
             contextlib.redirect_stderr(io.StringIO()):
            return verify.verify(self.root, "com.example.app", version)

    def cli(self, source, *extra):
        with mock.patch("sys.argv", ["verify.py", "--input", str(source), "--package", "com.example.app", *extra]), \
             mock.patch.object(verify, "find_tool", side_effect=lambda name, sdk: name), \
             mock.patch.object(verify.subprocess, "run", side_effect=self.tool), \
             contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return verify.main()

    def test_attribute_value_containing_element_marker_does_not_stop_root_parsing(self):
        attrs = verify.manifest_attributes(self.xml())
        self.assertEqual(attrs["package"], "com.example.app")
        self.assertEqual(attrs["android:versionName"], "PRE: 1.2.3")
        self.assertNotIn("android:label", attrs)
        self.assertEqual(self.run_verify()["status"], "verified")

    def test_default_verification_rejects_wrong_acquired_version(self):
        self.record(123)
        self.actual_version = 122
        result = self.run_verify()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["expected_version_code"], 123)
        self.assertIn("base.apk: requested versionCode mismatch", result["errors"])
        self.assertFalse(result["source_declared_set_complete"])

    def test_apk_subdirectory_cannot_bypass_acquisition_requirement(self):
        self.record(123)
        self.actual_version = 122
        self.assertEqual(self.cli(self.root / "apks"), 1)
        report = json.loads((self.root / "apks/verification.json").read_text())
        self.assertEqual(report["expected_version_code"], 123)
        self.assertEqual(report["status"], "failed")

    def test_apk_subdirectory_with_no_related_record_uses_explicit_target(self):
        data = self.record(999)
        data["files"][0]["file"] = "another-dir/base.apk"
        write_json(self.root / "download.json", data)
        self.assertIsNone(verify.source_record_root(self.root / "apks"))
        self.assertEqual(self.cli(self.root / "apks", "--version-code", "123"), 0)

    def test_matching_recorded_and_explicit_versions_succeed(self):
        self.record(123)
        for explicit in (None, 123):
            with self.subTest(explicit=explicit):
                self.assertEqual(self.run_verify(explicit)["status"], "verified")

    def test_explicit_version_cannot_override_acquisition_requirement(self):
        self.record(123)
        self.assertEqual(self.cli(self.root, "--version-code", "122"), 1)
        report = json.loads((self.root / "verification.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertIn("conflicts", report["errors"][0])

    def test_source_version_claim_is_not_silently_used_as_user_requirement(self):
        self.record(None)
        self.actual_version = 122
        result = self.run_verify()
        self.assertIsNone(result["expected_version_code"])
        self.assertEqual(result["status"], "verified")

    def test_standalone_apk_explicit_requirement_is_checked(self):
        self.actual_version = 122
        self.assertEqual(self.cli(self.apk, "--version-code", "123"), 1)

    def test_single_artifact_input_inherits_its_acquisition_requirement(self):
        self.record(123)
        self.actual_version = 122
        self.assertEqual(self.cli(self.apk), 1)
        report = json.loads(self.apk.with_name("base.apk.verification.json").read_text())
        self.assertEqual(report["expected_version_code"], 123)
        self.assertEqual(report["status"], "failed")

    def test_raw_archive_input_inherits_record_and_preserves_tool_evidence(self):
        (self.root / "raw").mkdir()
        archive = self.root / "raw/sample.apks"
        with zipfile.ZipFile(archive, "w") as output:
            output.write(self.apk, "base.apk")
        write_json(self.root / "download.json", {
            "status": "downloaded_pending_identity_and_signature_verification", "requested_version_code": 123,
            "files": [{"file": "raw/sample.apks", "sha256": sha256(archive)}]})
        self.actual_version = 122
        self.assertEqual(self.cli(archive), 1)
        report_path = archive.with_name("sample.apks.verification.json")
        report = json.loads(report_path.read_text())
        self.assertEqual(report["expected_version_code"], 123)
        self.assertTrue(report_path.with_suffix(".details").joinpath("base.apk.manifest.json").exists())

    def test_unrelated_adjacent_record_does_not_set_standalone_target(self):
        data = self.record(999)
        data["files"][0]["file"] = "apks/unrelated.apk"
        write_json(self.root / "download.json", data)
        self.assertIsNone(verify.source_record_root(self.apk.resolve()))

    def test_missing_tools_remain_incomplete(self):
        self.record(123)
        with mock.patch.object(verify, "find_tool", return_value=None), contextlib.redirect_stderr(io.StringIO()):
            result = verify.verify(self.root, "com.example.app")
        self.assertEqual(result["status"], "incomplete_verification")


if __name__ == "__main__":
    unittest.main()
