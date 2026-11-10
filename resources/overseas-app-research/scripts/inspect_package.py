#!/usr/bin/env python3
"""Inventory all APK payloads, or compare an analysis copy with an original APK."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tempfile
import zipfile

from apk_utils import sha256, unpack_apks, write_json
from progress import emit


def entry_hash(z, name):
    digest = hashlib.sha256()
    with z.open(name) as f:
        for block in iter(lambda: f.read(1024 * 256), b""):
            digest.update(block)
    return digest.hexdigest()


def unique_entries(z):
    names = [i.filename for i in z.infolist() if not i.is_dir()]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate ZIP entry names; payload comparison would be ambiguous")
    return set(names)


def inventory(apks):
    report = {"status": "inventoried", "apk_count": len(apks), "files": [],
              "framework_indicators": [], "note": "File indicators are not proof of the main architecture or active business behavior"}
    if not apks:
        raise ValueError("No APKs found in the sample")
    indicators = set()
    for apk in apks:
        row = {"file": apk.name, "bytes": apk.stat().st_size, "sha256": sha256(apk),
               "dex": [], "native_libraries": [], "frontend_assets": [], "shell_filename_signals": []}
        with zipfile.ZipFile(apk) as z:
            names = unique_entries(z)
            if "AndroidManifest.xml" not in names:
                raise ValueError("Not an APK: " + apk.name)
            for info in z.infolist():
                name = info.filename
                base = PurePosixPath(name).name
                if name.endswith(".dex"):
                    with z.open(info) as f:
                        header = f.read(112)
                    row["dex"].append({"path": name, "bytes": info.file_size,
                                       "standard_dex_magic": header.startswith(b"dex\n"), "sha256": entry_hash(z, name)})
                if name.startswith("lib/") and name.endswith(".so"):
                    row["native_libraries"].append({"path": name, "abi": name.split("/")[1], "bytes": info.file_size})
                    if base in ("libflutter.so", "libapp.so"):
                        indicators.add("flutter-runtime-or-aot")
                    if base == "libhermes.so":
                        indicators.add("hermes-runtime")
                    if base in ("libreactnative.so", "libreactnativejni.so"):
                        indicators.add("react-native-runtime")
                    if base in ("libDexHelper.so", "libDexHelper-x86.so", "libdexjni.so", "libexec.so"):
                        row["shell_filename_signals"].append(name)
                if name.startswith("assets/") and (name.endswith((".html", ".js", ".css", ".bundle")) or "flutter_assets/" in name):
                    row["frontend_assets"].append({"path": name, "bytes": info.file_size})
                    if name.endswith(".html"):
                        indicators.add("bundled-html")
                    if base in ("index.android.bundle", "main.jsbundle"):
                        indicators.add("javascript-or-hermes-bundle")
            row["entry_count"] = len(names)
        report["files"].append(row)
    report["framework_indicators"] = sorted(indicators)
    return report


def allowed_change(name):
    if name in ("AndroidManifest.xml", "stamp-cert-sha256"):
        return True
    return name.startswith("META-INF/") and (name == "META-INF/MANIFEST.MF" or
           PurePosixPath(name).suffix.upper() in (".SF", ".RSA", ".DSA", ".EC"))


def compare(original, copy):
    report = {"original_sha256": sha256(original), "copy_sha256": sha256(copy),
              "unchanged_entries": 0, "allowed_differences": [], "unexpected_differences": [],
              "note": "Entry-level comparison; inspect Manifest semantics separately. This does not preserve the original signing identity."}
    with zipfile.ZipFile(original) as a, zipfile.ZipFile(copy) as b:
        left, right = unique_entries(a), unique_entries(b)
        if "AndroidManifest.xml" not in left or "AndroidManifest.xml" not in right:
            raise ValueError("Both inputs must be APKs")
        for name in sorted(left | right):
            if name in left and name in right and entry_hash(a, name) == entry_hash(b, name):
                report["unchanged_entries"] += 1
                continue
            row = {"path": name, "kind": "added" if name not in left else "removed" if name not in right else "changed"}
            report["allowed_differences" if allowed_change(name) else "unexpected_differences"].append(row)
    report["allowed_entry_differences_only"] = not report["unexpected_differences"]
    manifest_changed = any(row["path"] == "AndroidManifest.xml" for row in report["allowed_differences"])
    report["manifest_semantic_review"] = "required" if manifest_changed else "not_needed"
    report["status"] = ("failed" if not report["allowed_entry_differences_only"] else
                        "requires_manifest_review" if manifest_changed else "passed")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--input", required=True, help="APK, APKS/XAPK/ZIP, or sample directory")
    inv.add_argument("--out", required=True, help="New analysis directory")
    diff = sub.add_parser("compare")
    diff.add_argument("--original", required=True)
    diff.add_argument("--copy", required=True)
    diff.add_argument("--out", required=True, help="New comparison directory")
    args = p.parse_args()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False)
    emit("拆包与代码恢复", "running", "盘点全部 APK 载荷。" if args.command == "inventory" else "比对原包和分析副本的 ZIP 条目。")
    try:
        if args.command == "compare":
            report = compare(Path(args.original).expanduser(), Path(args.copy).expanduser())
        else:
            source = Path(args.input).expanduser().resolve()
            if source.is_dir():
                directory = source / "apks" if (source / "apks").is_dir() else source
                report = inventory(sorted(directory.glob("*.apk")))
            else:
                with tempfile.TemporaryDirectory(prefix="apk-inventory-") as tmp:
                    apks = unpack_apks(source, Path(tmp) / "apks")
                    report = inventory(apks)
                    report["input_archive_sha256"] = sha256(source)
            report["input"] = str(source)
        code = 2 if report["status"] == "requires_manifest_review" else int(report["status"] == "failed")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        report = {"status": "failed", "error": str(exc), "error_type": type(exc).__name__}
        code = 1
    path = out / ("inventory.json" if args.command == "inventory" else "payload-comparison.json")
    write_json(path, report)
    emit("拆包与代码恢复", "running" if code == 2 else "failed" if code else "succeeded",
         "条目比对完成，仍须核对 Manifest 语义并记录结论。" if code == 2 else
         "结果已保存；此工具不自动反编译或脱壳。")
    print(json.dumps({"status": report["status"], "report": str(path)}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
