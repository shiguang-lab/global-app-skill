"""Payload inventory, original-UI preservation checks, and research progress scope."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import inspect_package
import progress


class PackageAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def apk(self, name, entries):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("AndroidManifest.xml", entries.get("AndroidManifest.xml", b"manifest fixture"))
            for key, value in entries.items():
                if key != "AndroidManifest.xml":
                    z.writestr(key, value)
        return path

    def test_inventory_reads_framework_and_libraries_from_all_splits(self):
        base = self.apk("base.apk", {"classes.dex": b"dex\n035\0" + bytes(104),
                                    "assets/flutter_assets/FontManifest.json": b"[]"})
        split = self.apk("config.arm64_v8a.apk", {"lib/arm64-v8a/libflutter.so": b"fixture",
                                                "lib/arm64-v8a/libapp.so": b"fixture"})
        report = inspect_package.inventory([base, split])
        self.assertEqual(report["apk_count"], 2)
        self.assertIn("flutter-runtime-or-aot", report["framework_indicators"])
        self.assertEqual(len(report["files"][1]["native_libraries"]), 2)
        self.assertTrue(report["files"][0]["dex"][0]["standard_dex_magic"])

    def test_inventory_distinguishes_shell_signals_and_frontend_assets(self):
        apk = self.apk("base.apk", {"assets/index.android.bundle": b"binary fixture", "assets/web/index.html": b"<html/>",
                                    "lib/arm64-v8a/libhermes.so": b"fixture", "lib/arm64-v8a/libDexHelper.so": b"fixture"})
        report = inspect_package.inventory([apk])
        self.assertIn("hermes-runtime", report["framework_indicators"])
        self.assertIn("bundled-html", report["framework_indicators"])
        self.assertEqual(report["files"][0]["shell_filename_signals"], ["lib/arm64-v8a/libDexHelper.so"])

    def test_identical_apk_copy_has_no_payload_differences(self):
        a = self.apk("one.apk", {"classes.dex": b"fixture"})
        b = self.apk("two.apk", {"classes.dex": b"fixture"})
        self.assertEqual(inspect_package.compare(a, b)["status"], "passed")

    def test_manifest_and_signing_changes_are_separated_from_business_payload(self):
        a = self.apk("one.apk", {"AndroidManifest.xml": b"original", "classes.dex": b"business",
                                 "META-INF/CERT.RSA": b"old signature"})
        b = self.apk("two.apk", {"AndroidManifest.xml": b"debug copy", "classes.dex": b"business",
                                 "META-INF/NEW.SF": b"new signature"})
        report = inspect_package.compare(a, b)
        self.assertEqual(report["status"], "requires_manifest_review")
        self.assertEqual(report["manifest_semantic_review"], "required")
        self.assertEqual(report["unchanged_entries"], 1)
        self.assertEqual(len(report["allowed_differences"]), 3)

    def test_navigation_manifest_change_cannot_pass_as_debug_only_change(self):
        a = self.apk("one.apk", {"AndroidManifest.xml": b"original Activity/permissions", "classes.dex": b"same"})
        b = self.apk("two.apk", {"AndroidManifest.xml": b"different Activity/permissions", "classes.dex": b"same"})
        report = inspect_package.compare(a, b)
        self.assertEqual(report["status"], "requires_manifest_review")
        self.assertTrue(report["allowed_entry_differences_only"])
        out = self.root / "compare"
        run = subprocess.run([sys.executable, inspect_package.__file__, "compare", "--original", str(a),
                              "--copy", str(b), "--out", str(out)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(json.loads((out / "payload-comparison.json").read_text())["manifest_semantic_review"], "required")

    def test_signing_changes_with_unchanged_manifest_can_pass(self):
        a = self.apk("one.apk", {"META-INF/CERT.RSA": b"original"})
        b = self.apk("two.apk", {"META-INF/CERT.RSA": b"test signature"})
        report = inspect_package.compare(a, b)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["manifest_semantic_review"], "not_needed")

    def test_business_dex_change_fails_original_payload_check(self):
        a = self.apk("one.apk", {"classes.dex": b"original"})
        b = self.apk("two.apk", {"classes.dex": b"changed"})
        self.assertEqual(inspect_package.compare(a, b)["status"], "failed")

    def test_ui_css_and_custom_meta_inf_cannot_be_hidden_as_signing_changes(self):
        for name in ["assets/page.css", "assets/page.js", "res/layout/page.xml", "META-INF/custom.json"]:
            with self.subTest(name=name):
                a = self.apk("one.apk", {name: b"original"})
                b = self.apk("two.apk", {name: b"changed"})
                report = inspect_package.compare(a, b)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["unexpected_differences"][0]["path"], name)

    def test_missing_native_library_is_rejected(self):
        a = self.apk("one.apk", {"lib/arm64-v8a/libapp.so": b"fixture"})
        b = self.apk("two.apk", {})
        self.assertEqual(inspect_package.compare(a, b)["unexpected_differences"][0]["kind"], "removed")

    def test_duplicate_zip_entry_is_not_silently_compared(self):
        a = self.apk("one.apk", {"classes.dex": b"original"})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(a, "a") as z:
                z.writestr("classes.dex", b"hidden duplicate")
        with self.assertRaisesRegex(ValueError, "Duplicate ZIP entry"):
            inspect_package.inventory([a])

    def test_archive_cli_keeps_input_unchanged_and_inventories_every_apk(self):
        base = self.apk("base.apk", {"classes.dex": b"fixture"})
        split = self.apk("split.apk", {"lib/arm64-v8a/libapp.so": b"fixture"})
        archive = self.root / "source.apks"
        with zipfile.ZipFile(archive, "w") as z:
            z.write(base, "base.apk")
            z.write(split, "config.arm64_v8a.apk")
        original = archive.read_bytes()
        out = self.root / "inventory"
        r = subprocess.run([sys.executable, inspect_package.__file__, "inventory", "--input", str(archive), "--out", str(out)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((out / "inventory.json").read_text())["apk_count"], 2)
        self.assertEqual(archive.read_bytes(), original)
        self.assertIn("5/10", r.stderr)


class ProgressScopeTests(unittest.TestCase):
    def test_download_mode_keeps_four_stages(self):
        output = io.StringIO()
        with mock.patch.dict("os.environ", {}, clear=True), contextlib.redirect_stderr(output):
            progress.emit("获取安装包", "running", "fixture")
        self.assertIn("3/4", output.getvalue())

    def test_full_research_mode_covers_download_and_later_stages(self):
        output = io.StringIO()
        with mock.patch.dict("os.environ", {"APP_RESEARCH_TOTAL_STAGES": "10"}, clear=True), contextlib.redirect_stderr(output):
            progress.emit("环境检查 · 设备", "running", "fixture")
            progress.emit("调研执行", "skipped", "fixture failed gate")
            progress.emit("拆包与代码恢复", "running", "fixture")
        self.assertIn("1/10", output.getvalue())
        self.assertIn("2–10/10", output.getvalue())
        self.assertIn("5/10", output.getvalue())

    def test_page_extraction_progress_uses_stage_eight_for_ued(self):
        output = io.StringIO()
        with mock.patch.dict("os.environ", {"APP_RESEARCH_TOTAL_STAGES": "10"}), contextlib.redirect_stderr(output):
            progress.emit("页面提取与场景走查 · UED", "running", "正在提取 H5 路由页面。")
        self.assertIn("8/10 页面提取与场景走查 · UED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
