"""Device gate and fail-fast behavior, without changing real devices or VPNs."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import download
import preflight


def passed(stdout=""):
    return {"returncode": 0, "stdout": stdout}


class DeviceGateTests(unittest.TestCase):
    def check(self, listing, avds=None, sdk="35", qemu="0"):
        tools = {"adb": "fixture-adb", "emulator": "fixture-emulator" if avds is not None else None}
        def run(cmd):
            if cmd[1:] == ["devices", "-l"]:
                return passed("List of devices attached\n" + listing)
            if cmd[1:] == ["-list-avds"]:
                return passed("\n".join(a["name"] for a in avds))
            if cmd[-1] == "ro.build.version.sdk":
                return passed(sdk)
            if cmd[-1] == "ro.kernel.qemu":
                return passed(qemu)
            raise AssertionError(cmd)
        with mock.patch.object(preflight, "run", side_effect=run), \
             mock.patch.object(preflight, "avd_inventory", return_value=avds or []):
            return preflight.device_check(tools)

    def test_no_device_and_no_avd_fails(self):
        result = self.check("")
        self.assertEqual(result["device_gate"]["status"], "failed")
        self.assertIn("NO_ANDROID_DEVICE", [e["code"] for e in result["device_gate"]["errors"]])

    def test_emulator_binary_without_avd_fails(self):
        self.assertEqual(self.check("", avds=[])["device_gate"]["status"], "failed")

    def test_responding_authorized_phone_passes(self):
        result = self.check("phone-fixture device model:fixture\n")
        self.assertEqual(result["device_gate"]["status"], "passed")
        self.assertEqual(result["device_gate"]["online_device_count"], 1)
        self.assertFalse(result["device_gate"]["requires_emulator_start"])

    def test_responding_emulator_passes_without_avd_config(self):
        result = self.check("emulator-5554 device\n", qemu="1")
        self.assertEqual(result["device_gate"]["status"], "passed")
        self.assertEqual(result["connected_devices"][0]["kind"], "emulator")

    def test_device_label_without_responsive_android_shell_fails(self):
        self.assertEqual(self.check("phone-fixture device\n", sdk="")["device_gate"]["status"], "failed")

    def test_unauthorized_only_fails_with_actionable_reason(self):
        result = self.check("phone-fixture unauthorized\n")
        self.assertEqual(result["device_gate"]["status"], "failed")
        self.assertIn("DEVICE_UNAUTHORIZED", [e["code"] for e in result["device_gate"]["errors"]])

    def test_offline_device_does_not_pass(self):
        self.assertEqual(self.check("emulator-5554 offline\n")["device_gate"]["status"], "failed")

    def test_complete_stopped_avd_passes_as_needing_start(self):
        result = self.check("", avds=[{"name": "fixture", "configured": True, "boot_verified": False}])
        self.assertEqual(result["device_gate"]["status"], "passed")
        self.assertTrue(result["device_gate"]["requires_emulator_start"])

    def test_broken_avd_does_not_pass(self):
        result = self.check("", avds=[{"name": "fixture", "configured": False}])
        self.assertEqual(result["device_gate"]["status"], "failed")

    def test_complete_avd_can_be_used_when_phone_is_unauthorized(self):
        result = self.check("phone-fixture unauthorized\n", avds=[{"name": "fixture", "configured": True}])
        self.assertEqual(result["device_gate"]["status"], "passed")
        self.assertEqual(result["device_gate"]["online_device_count"], 0)

    def test_missing_adb_does_not_claim_a_usable_environment(self):
        with mock.patch.object(preflight, "run", return_value=passed("fixture")), \
             mock.patch.object(preflight, "avd_inventory", return_value=[{"name": "fixture", "configured": True}]):
            result = preflight.device_check({"adb": None, "emulator": "fixture-emulator"})
        self.assertEqual(result["device_gate"]["status"], "failed")
        self.assertIn("ADB_MISSING", [e["code"] for e in result["device_gate"]["errors"]])


class AvdInventoryTests(unittest.TestCase):
    def test_configuration_requires_real_image_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "avd"
            directory = home / "Fixture.avd"
            directory.mkdir(parents=True)
            image = root / "image"
            image.mkdir()
            (home / "Fixture.ini").write_text("path=" + str(directory) + "\n")
            (directory / "config.ini").write_text("image.sysdir.1=" + str(image) + "\nabi.type=arm64-v8a\nPlayStore.enabled=true\n")
            with mock.patch.dict("os.environ", {"ANDROID_AVD_HOME": str(home)}, clear=True):
                self.assertFalse(preflight.avd_inventory(["Fixture"])[0]["configured"])
                for name in ("system.img", "ramdisk.img", "kernel-ranchu"):
                    (image / name).touch()
                item = preflight.avd_inventory(["Fixture"])[0]
                self.assertTrue(item["configured"])
                self.assertTrue(item["google_play"])
                self.assertFalse(item["boot_verified"])


class FailFastTests(unittest.TestCase):
    def test_failed_preflight_returns_four_and_never_queries_vpn(self):
        failure = {"device_gate": {"status": "failed", "errors": [{"code": "NO_ANDROID_DEVICE", "message": "fixture: no Android device"}]}}
        output, progress = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "environment.json"
            with mock.patch("sys.argv", ["preflight.py", "--controller", "http://127.0.0.1:9999", "--report", str(report)]), \
                 mock.patch.object(preflight, "find_tool", return_value=None), \
                 mock.patch.object(preflight, "device_check", return_value=failure), \
                 mock.patch.object(preflight.urllib.request, "build_opener") as network, \
                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(progress):
                self.assertEqual(preflight.main(), 4)
            network.assert_not_called()
            data = json.loads(report.read_text())
            self.assertEqual(data["status"], "failed")
            self.assertFalse(data["downstream_allowed"])
        self.assertEqual(json.loads(output.getvalue())["status"], "failed")
        self.assertIn("NO_ANDROID_DEVICE", progress.getvalue())
        self.assertIn("跳过", progress.getvalue())

    def test_downloader_stops_before_network_or_attempt_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "must-not-be-created"
            output = io.StringIO()
            with mock.patch("sys.argv", ["download.py", "url", "--package", "com.example.app", "--out", str(out),
                                        "--url", "https://example.test/app.apk", "--filename", "app.apk"]), \
                 mock.patch.object(download, "require_device_environment", side_effect=ValueError("fixture device gate failed")), \
                 mock.patch.object(download, "opener") as network, \
                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(download.main(), 4)
            network.assert_not_called()
            self.assertFalse(out.exists())
            self.assertEqual(json.loads(output.getvalue())["status"], "environment_failed")


if __name__ == "__main__":
    unittest.main()
