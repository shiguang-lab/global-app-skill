"""Local regression checks: python3 -m unittest discover -s scripts -p 'test_*.py'."""
import argparse
import contextlib
import hashlib
import http.server
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

import apk_utils
import download
import export_device
import preflight


def apk_bytes():
    f = io.BytesIO()
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("AndroidManifest.xml", b"fixture: transport validation only")
        z.writestr("classes.dex", b"fixture")
    return f.getvalue()


APK = apk_bytes()


class Handler(http.server.BaseHTTPRequestHandler):
    ranges = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/proxies":
            body = json.dumps({"proxies": {"route": {"type": "Selector", "now": "original", "all": ["original", "菲律宾 fixture"]},
                                           "菲律宾 fixture": {"type": "ss"}}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = b"<html>captcha</html>" if self.path == "/html" else APK
        start = 0
        ranged = self.headers.get("Range")
        if ranged:
            start = int(ranged.removeprefix("bytes=").rstrip("-"))
            self.ranges.append(start)
        self.send_response(206 if ranged else 200)
        self.send_header("Content-Length", str(len(body) - start))
        if ranged:
            self.send_header("Content-Range", f"bytes {start}-{len(body)-1}/{len(body)}")
        self.end_headers()
        self.wfile.write(body[start:])


class TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = Path(self.tmp.name) / "base.apk"
        self.op = apk_utils.opener("direct")

    def test_source_digest_and_exact_size(self):
        result = apk_utils.transfer(self.op, self.url + "/apk?secret=hidden", self.dest,
                                    expected_size=len(APK), digest=hashlib.sha256(APK).hexdigest())
        self.assertTrue(result["source_checksum_verified"])
        self.assertNotIn("secret", result["source_url"])
        self.assertEqual(self.dest.read_bytes(), APK)

    def test_wrong_digest_rejects_file(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            apk_utils.transfer(self.op, self.url + "/apk", self.dest, digest="0" * 64)
        self.assertFalse(self.dest.exists())

    def test_wrong_size_rejects_file(self):
        with self.assertRaisesRegex(ValueError, "Size mismatch"):
            apk_utils.transfer(self.op, self.url + "/apk", self.dest, expected_size=len(APK) + 1)
        self.assertFalse(self.dest.exists())

    def test_captcha_html_is_not_an_apk(self):
        with self.assertRaises(zipfile.BadZipFile):
            apk_utils.transfer(self.op, self.url + "/html", self.dest)
        self.assertFalse(self.dest.exists())

    def test_resume_requires_matching_source_identity(self):
        digest = hashlib.sha256(APK).hexdigest()
        part = self.dest.with_name("base.apk.part")
        part.write_bytes(APK[:30])
        apk_utils.write_json(self.dest.with_name("base.apk.part.json"), {"size": len(APK), "md5": None, "sha256": digest})
        Handler.ranges.clear()
        apk_utils.transfer(self.op, self.url + "/apk", self.dest, expected_size=len(APK), digest=digest)
        self.assertEqual(Handler.ranges, [30])
        self.assertEqual(self.dest.read_bytes(), APK)

    def test_unknown_identity_never_appends_stale_bytes(self):
        self.dest.with_name("base.apk.part").write_bytes(b"old version")
        Handler.ranges.clear()
        apk_utils.transfer(self.op, self.url + "/apk", self.dest)
        self.assertEqual(Handler.ranges, [])
        self.assertEqual(self.dest.read_bytes(), APK)

    def test_node_inventory_is_read_only_and_secret_is_not_reported(self):
        output = io.StringIO()
        with mock.patch("sys.argv", ["preflight.py", "--controller", self.url, "--country", "PH", "--secret-env", "TEST_NODE_SECRET"]), \
             mock.patch.object(preflight.platform, "system", return_value="Linux"), \
             mock.patch.object(preflight, "find_tool", return_value=None), \
             mock.patch.object(preflight, "device_check", return_value={"device_gate": {"status": "passed", "errors": [], "online_device_count": 1, "configured_avd_count": 0}}), \
             mock.patch.dict("os.environ", {"TEST_NODE_SECRET": "private-controller-fixture"}, clear=True), \
             contextlib.redirect_stderr(io.StringIO()), \
             contextlib.redirect_stdout(output):
            self.assertEqual(preflight.main(), 0)
        result = json.loads(output.getvalue())
        self.assertFalse(result["network_changed"])
        self.assertTrue(result["vpn_nodes"][1]["matches_country_name"])
        self.assertNotIn("private-controller-fixture", output.getvalue())


class ArchiveAndMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def archive(self, names):
        source = self.root / "sample.apks"
        with zipfile.ZipFile(source, "w") as z:
            for name in names:
                z.writestr(name, APK)
        return source

    def test_all_nested_apks_extracted(self):
        files = apk_utils.unpack_apks(self.archive(["base.apk", "config.arm64_v8a.apk", "config.es.apk"]), self.root / "apks")
        self.assertEqual(len(files), 3)
        self.assertTrue(all(p.read_bytes() == APK for p in files))

    def test_path_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsafe archive"):
            apk_utils.unpack_apks(self.archive(["../outside.apk"]), self.root / "apks")
        self.assertFalse((self.root / "outside.apk").exists())

    def test_basename_collision_rejected(self):
        with self.assertRaises(FileExistsError):
            apk_utils.unpack_apks(self.archive(["one/base.apk", "two/base.apk"]), self.root / "apks")

    def test_aptoide_includes_all_splits(self):
        args = argparse.Namespace(sdk_level=35, abi="arm64-v8a", density=480, locale="es_MX", package="com.example.app")
        data = {"package": args.package, "file": {"path": "https://example.test/base.apk"},
                "aab": {"splits": [{"name": "config.arm64_v8a", "path": "https://example.test/arm.apk"},
                                   {"name": "config.es", "path": "https://example.test/es.apk"}]}}
        with mock.patch.object(download, "json_get", return_value={"nodes": {"meta": {"data": data}}}):
            _, files = download.aptoide_candidates(None, args)
        self.assertEqual([x[0] for x in files], ["base.apk", "config.arm64_v8a.apk", "config.es.apk"])

    def test_aptoide_wrong_package_rejected(self):
        args = argparse.Namespace(sdk_level=35, abi="arm64-v8a", density=480, locale="es_MX", package="com.example.app")
        with mock.patch.object(download, "json_get", return_value={"data": {"package": "com.other.app", "file": {"path": "x"}}}):
            with self.assertRaisesRegex(ValueError, "no matching"):
                download.aptoide_candidates(None, args)

    def test_truncated_protocol_does_not_produce_files(self):
        with self.assertRaisesRegex(ValueError, "Truncated"):
            download.parse_proto(b"\x0a\x10abc")

    def test_delivery_protocol_includes_base_and_split(self):
        inner = download.field(3, "https://example.test/base.apk") + download.field(15,
            download.field(1, "config.arm64_v8a") + download.field(5, "https://example.test/arm.apk"))
        response = download.field(1, download.field(21, download.field(1, 1) + download.field(2, inner)))
        profile = {k: "fixture" for k in ["Build.ID", "Build.VERSION.RELEASE", "Build.DEVICE", "Build.HARDWARE", "Build.MODEL", "Build.BRAND", "Build.PRODUCT", "Build.FINGERPRINT", "Vending.versionString"]}
        profile["Build.VERSION.SDK_INT"] = "35"
        profile_path = self.root / "profile.json"
        apk_utils.write_json(profile_path, profile)
        id_path = self.root / "id.txt"
        id_path.write_text("123")
        args = argparse.Namespace(device_profile=str(profile_path), device_id_file=str(id_path), country="PH", language="en-PH", package="com.example.app", version_code=1)
        op = mock.Mock()
        op.open.return_value = io.BytesIO(response)
        files, _ = download.play_files(op, args)
        self.assertEqual([f[0] for f in files], ["base.apk", "split_config.arm64_v8a.apk"])

    def test_device_export_pulls_every_path_with_explicit_serial(self):
        calls = []
        digest = hashlib.sha256(APK).hexdigest()
        paths = ["/data/app/fixture/base.apk", "/data/app/fixture/split_config.arm64_v8a.apk"]
        def fake_adb(adb, serial, *args):
            self.assertEqual(serial, "chosen-device")
            calls.append(args)
            if args[:3] == ("shell", "pm", "path"):
                return "\n".join("package:" + p for p in paths)
            if args[:3] == ("shell", "toybox", "sha256sum"):
                return digest + "  " + args[3] + "\n"
            if args[0] == "pull":
                Path(args[2]).write_bytes(APK)
                return ""
            raise AssertionError("Unexpected device action: " + str(args))
        out = self.root / "export"
        with mock.patch("sys.argv", ["export_device.py", "--serial", "chosen-device", "--package", "com.example.app", "--out", str(out)]), \
             mock.patch.object(export_device, "find_tool", return_value="fixture-adb"), \
             mock.patch.object(export_device, "adb_run", side_effect=fake_adb), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(export_device.main(), 0)
        data = json.loads((out / "download.json").read_text())
        self.assertEqual(len(data["files"]), 2)
        self.assertEqual(sum(c[0] == "pull" for c in calls), 2)
        self.assertTrue(all(f["source_checksum_verified"] for f in data["files"]))

    def test_device_export_hash_mismatch_does_not_finish(self):
        def fake_adb(adb, serial, *args):
            if args[:3] == ("shell", "pm", "path"):
                return "package:/data/app/fixture/base.apk"
            if args[:3] == ("shell", "toybox", "sha256sum"):
                return "0" * 64 + "  /data/app/fixture/base.apk\n"
            if args[0] == "pull":
                Path(args[2]).write_bytes(APK)
                return ""
            raise AssertionError(str(args))
        out = self.root / "failed-export"
        with mock.patch("sys.argv", ["export_device.py", "--serial", "chosen-device", "--package", "com.example.app", "--out", str(out)]), \
             mock.patch.object(export_device, "find_tool", return_value="fixture-adb"), \
             mock.patch.object(export_device, "adb_run", side_effect=fake_adb), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(export_device.main(), 1)
        self.assertEqual(json.loads((out / "download.json").read_text())["status"], "failed")
        self.assertFalse((out / "apks/base.apk").exists())


class AnonymousPlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        profile = {k: "fixture" for k in ["Build.ID", "Build.VERSION.RELEASE", "Build.DEVICE", "Build.HARDWARE", "Build.MODEL", "Build.BRAND", "Build.PRODUCT", "Build.FINGERPRINT", "Vending.versionString"]}
        profile["Build.VERSION.SDK_INT"] = "35"
        (self.root / "profile.json").write_text(json.dumps(profile))
        (self.root / "id.txt").write_text("123")
        self.args = argparse.Namespace(package="com.example.app", country="PH", language="en-PH",
            device_profile=str(self.root / "profile.json"), device_id_file=str(self.root / "id.txt"))

    def response(self, package="com.example.app", code=123):
        f = download.field
        version = f(1, code) + f(2, "1.2.3") + f(3, 1)
        metadata = f(1, f(1, package)) + f(3, f(2, version))
        return f(11, f(2, metadata))

    def test_anonymous_details_uses_getitems_and_matching_package(self):
        op = mock.Mock()
        op.open.return_value = io.BytesIO(self.response("com.other.app", 999) + self.response())
        result = download.play_details(op, self.args)
        self.assertEqual(result["source_version_code"], 123)
        req = op.open.call_args.args[0]
        self.assertEqual(req.full_url, "https://play.googleapis.com/fdfe/getItems")
        self.assertEqual(req.get_method(), "POST")
        self.assertNotIn("Authorization", req.headers)
        self.assertIn("X-ps-rh", req.headers)
        self.assertIn(b"com.example.app", req.data)

    def test_missing_target_is_not_treated_as_delivery_failure(self):
        op = mock.Mock()
        op.open.return_value = io.BytesIO(self.response("com.other.app"))
        with self.assertRaisesRegex(ValueError, "getItems returned no matching package"):
            download.play_details(op, self.args)

    def test_missing_version_is_not_guessed(self):
        op = mock.Mock()
        op.open.return_value = io.BytesIO(self.response(code=0))
        with self.assertRaisesRegex(ValueError, "no positive versionCode"):
            download.play_details(op, self.args)

    def test_cli_without_version_resolves_before_delivery(self):
        seen = []
        def details(op, args):
            seen.append("getItems")
            return {"source_version_code": 123, "source_version": "1.2.3"}
        def delivery(op, args):
            self.assertEqual(args.version_code, 123)
            seen.append("delivery")
            return [("base.apk", b"https://example.test/base.apk", b"")], {}
        out = self.root / "out"
        argv = ["download.py", "play", "--package", self.args.package, "--out", str(out),
            "--country", "PH", "--language", "en-PH", "--device-profile", self.args.device_profile,
            "--device-id-file", self.args.device_id_file]
        with mock.patch("sys.argv", argv), \
             mock.patch.object(download, "require_device_environment", return_value={}), \
             mock.patch.object(download, "play_details", side_effect=details), \
             mock.patch.object(download, "play_files", side_effect=delivery), \
             mock.patch.object(download, "transfer", return_value={}), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(download.main(), 0)
        self.assertEqual(seen, ["getItems", "delivery"])
        report = json.loads((out / "download.json").read_text())
        self.assertEqual(report["source_version_code"], 123)
        self.assertIsNone(report["requested_version_code"])
        self.assertEqual(report["declared_files"], ["base.apk"])

    def test_explicit_version_is_preserved_before_delivery(self):
        out = self.root / "explicit"
        def delivery(op, args):
            record = json.loads((out / "download.json").read_text())
            self.assertEqual(record["requested_version_code"], 123)
            self.assertEqual(args.version_code, 123)
            return [("base.apk", b"https://example.test/base.apk", b"")], {}
        argv = ["download.py", "play", "--package", self.args.package, "--out", str(out),
                "--version-code", "123", "--country", "PH", "--language", "en-PH",
                "--device-profile", self.args.device_profile, "--device-id-file", self.args.device_id_file]
        with mock.patch("sys.argv", argv), mock.patch.object(download, "require_device_environment", return_value={}), \
             mock.patch.object(download, "play_files", side_effect=delivery), \
             mock.patch.object(download, "play_details", side_effect=AssertionError("Exact version must not be replaced")), \
             mock.patch.object(download, "transfer", return_value={}), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(download.main(), 0)
        self.assertEqual(json.loads((out / "download.json").read_text())["requested_version_code"], 123)


if __name__ == "__main__":
    unittest.main()
