#!/usr/bin/env python3
"""Export every installed APK for one package from an explicitly selected device."""
import argparse
import datetime
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile

from apk_utils import find_tool, sha256, write_json
from progress import emit


def adb_run(adb, serial, *args):
    r = subprocess.run([adb, "-s", serial, *args], capture_output=True, text=True, timeout=180)
    if r.returncode:
        raise ValueError("adb operation failed: " + r.stderr.strip()[:500])
    return r.stdout


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--serial", required=True, help="Explicit serial, even if there is only one device")
    p.add_argument("--package", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--sdk")
    p.add_argument("--version-code", type=int, help="Required versionCode, recorded for subsequent identity verification")
    args = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", args.package):
        p.error("Invalid Android package name")
    adb = find_tool("adb", args.sdk)
    if not adb:
        p.error("adb is missing; inspect existing SDK before installing platform-tools")
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {"source": "installed_device", "requested_package": args.package, "device_serial": args.serial,
              "requested_version_code": args.version_code,
              "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "files": [], "status": "attempting"}
    emit("获取安装包", "running", f"从已选择设备导出 {args.package} 的完整 APK 清单。")
    try:
        paths = [s.removeprefix("package:").strip() for s in adb_run(adb, args.serial, "shell", "pm", "path", args.package).splitlines()
                 if s.startswith("package:")]
        if not paths:
            raise ValueError("Package not installed or pm path returned no APKs")
        report["declared_files"] = [PurePosixPath(s).name for s in paths]
        if len(set(report["declared_files"])) != len(paths):
            raise ValueError("Duplicate APK basenames from device")
        (out / "apks").mkdir()
        for index, remote in enumerate(paths, 1):
            emit("获取安装包", "running", f"导出 {index}/{len(paths)}：{PurePosixPath(remote).name}，比对设备与本机哈希。")
            if not remote.startswith("/") or not remote.endswith(".apk"):
                raise ValueError("Unexpected APK path from device")
            target = out / "apks" / PurePosixPath(remote).name
            part = target.with_name(target.name + ".part")
            before = adb_run(adb, args.serial, "shell", "toybox", "sha256sum", remote)
            match = re.match(r"([a-fA-F0-9]{64})\s", before)
            if not match:
                raise ValueError("Could not obtain source device SHA-256")
            adb_run(adb, args.serial, "pull", remote, str(part))
            digest = sha256(part)
            after = adb_run(adb, args.serial, "shell", "toybox", "sha256sum", remote)
            if digest != match.group(1).lower() or before.strip() != after.strip():
                raise ValueError("Device/local hash mismatch or app changed while exporting")
            with zipfile.ZipFile(part) as z:
                if "AndroidManifest.xml" not in z.namelist() or z.testzip() is not None:
                    raise ValueError("Invalid exported APK")
            part.rename(target)
            report["files"].append({"file": str(target.relative_to(out)), "device_path": remote,
                                    "bytes": target.stat().st_size, "sha256": digest, "source_checksum_verified": True})
            write_json(out / "download.json", report)
        # Detect an install/update during extraction, including changed split sets.
        again = [s.removeprefix("package:").strip() for s in adb_run(adb, args.serial, "shell", "pm", "path", args.package).splitlines()
                 if s.startswith("package:")]
        if sorted(again) != sorted(paths):
            raise ValueError("Installed package changed while exporting; export again into a new directory")
        report["status"] = "exported_pending_identity_and_signature_verification"
        code = 0
    except Exception as exc:
        report.update(status="failed", error=str(exc), error_type=type(exc).__name__)
        code = 1
    write_json(out / "download.json", report)
    emit("获取安装包", "succeeded" if code == 0 else "failed",
         "全部设备分包已导出，等待身份与签名校验。" if code == 0 else report["error"])
    print(json.dumps({"status": report["status"], "report": str(out / "download.json")}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
