#!/usr/bin/env python3
"""Verify APK bytes, Android identity and signatures; never install or re-sign."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

from apk_utils import find_tool, java_env, sha256, unpack_apks, write_json
from progress import emit


def manifest_attributes(xml):
    root = re.search(r"^( *)E: manifest\b.*$", xml, re.MULTILINE)
    if not root:
        raise ValueError("Manifest root is missing")
    indent = len(root.group(1)) + 2
    attrs = {}
    for line in xml[root.end():].splitlines():
        if not line.strip():
            continue
        if len(line) - len(line.lstrip()) != indent or line.lstrip().startswith("E:"):
            break
        m = re.match(r"\s+A: ([\w:]+)(?:\([^)]*\))?=(.*)", line)
        if not m:
            continue
        name, value = m.groups()
        string = re.match(r'"((?:\\.|[^"\\])*)"', value)
        integer = re.match(r"\(type 0x1[01]\)(0x[0-9a-fA-F]+)", value)
        if string:
            attrs[name] = json.loads('"' + string.group(1) + '"')
        elif integer:
            attrs[name] = int(integer.group(1), 16)
    return attrs


def source_record_root(source):
    """Locate an acquisition record tied to the input artifact or APK directory."""
    source = Path(source).resolve()
    folders = (source, source.parent) if source.is_dir() else (source.parent, source.parent.parent)
    for folder in folders:
        record = folder / "download.json"
        if record.is_file():
            data = json.loads(record.read_text())
            if source.is_dir() and folder == source:
                return folder
            entries = data.get("files", []) + data.get("extracted_files", [])
            paths = [(folder / row["file"]).resolve() for row in entries]
            if any(path == source or (source.is_dir() and path.parent == source and path.suffix.lower() == ".apk")
                   for path in paths):
                return folder
    return None


def verify(root, package, version_code=None, reference_cert=None, sdk=None, acquisition_root=None):
    root = Path(root)
    acquisition_root = Path(acquisition_root) if acquisition_root is not None else source_record_root(root) or root
    manifest = acquisition_root / "download.json"
    data = json.loads(manifest.read_text()) if manifest.exists() else {}
    requested = data.get("requested_version_code")
    if requested is not None:
        requested = int(requested)
        if version_code is not None and int(version_code) != requested:
            raise ValueError("Requested versionCode conflicts with acquisition record")
        version_code = requested
    # Download layout intentionally keeps raw originals outside apks/.
    directory = root / "apks" if (root / "apks").is_dir() else root
    files = sorted(directory.glob("*.apk"))
    aapt, signer = find_tool("aapt", sdk), find_tool("apksigner", sdk)
    result = {"expected_package": package, "expected_version_code": version_code,
              "status": "incomplete_verification", "files": [], "errors": [],
              "missing_checks": [], "tools": {"aapt": aapt, "apksigner": signer},
              "installed": False, "launched": False,
              "official_certificate_comparison": "not_provided" if not reference_cert else "pending"}
    if not files:
        result["errors"].append("No APK files found")
    identities, cert_sets = [], []
    for index, apk in enumerate(files, 1):
        emit("校验归档", "running", f"检查 {index}/{len(files)}：{apk.name} 的完整性、Manifest 与 APK 签名。")
        rec = {"file": str(apk.relative_to(root)), "bytes": apk.stat().st_size, "sha256": sha256(apk)}
        result["files"].append(rec)
        try:
            with zipfile.ZipFile(apk) as z:
                if "AndroidManifest.xml" not in z.namelist() or z.testzip() is not None:
                    raise ValueError("Missing AndroidManifest.xml or CRC failure")
            rec["zip_valid"] = True
        except (zipfile.BadZipFile, ValueError) as exc:
            result["errors"].append(apk.name + ": " + str(exc))
            continue
        if aapt:
            # badging resolves icons/labels that may reside in resource splits.
            # Read binary Manifest attributes without requiring resource resolution.
            r = subprocess.run([aapt, "dump", "xmltree", str(apk), "AndroidManifest.xml"], capture_output=True, text=True, timeout=60)
            write_json(root / "verification-details" / (apk.name + ".manifest.json"), {"exit_code": r.returncode, "stdout": r.stdout, "stderr": r.stderr})
            attrs = manifest_attributes(r.stdout) if r.returncode == 0 else {}
            if not attrs.get("package") or "android:versionCode" not in attrs:
                result["errors"].append(apk.name + ": Android identity could not be parsed")
            else:
                code = (int(attrs.get("android:versionCodeMajor", 0)) << 32) | int(attrs["android:versionCode"])
                identity = {"package": attrs["package"], "version_code": str(code),
                            "version_name": attrs.get("android:versionName"), "split": attrs.get("split", ""),
                            "required_split_types": [s for s in attrs.get("android:requiredSplitTypes", "").split(",") if s],
                            "split_types": [s for s in attrs.get("android:splitTypes", "").split(",") if s]}
                rec.update(identity)
                identities.append(identity)
                if identity["package"] != package:
                    result["errors"].append(apk.name + ": package mismatch")
                if version_code is not None and identity["version_code"] != str(version_code):
                    result["errors"].append(apk.name + ": requested versionCode mismatch")
        if signer:
            r = subprocess.run([signer, "verify", "--verbose", "--print-certs", str(apk)],
                               capture_output=True, text=True, timeout=60, env=java_env())
            write_json(root / "verification-details" / (apk.name + ".signature.json"), {"exit_code": r.returncode, "stdout": r.stdout, "stderr": r.stderr})
            # Build Tools 37 uses 'V3.0 Signer:'; older tools use 'Signer #1'.
            # Source Stamp certificates are distribution stamps, not APK signers.
            certs = sorted(set(re.findall(
                r"^(?:Signer #\d+|V[\d.]+ Signer(?::| #\d+:?)) certificate SHA-256 digest:\s*([a-fA-F0-9]{64})",
                r.stdout, re.MULTILINE)))
            rec.update(signature_valid=r.returncode == 0 and bool(certs), signer_sha256=[s.lower() for s in certs])
            if not rec["signature_valid"]:
                result["errors"].append(apk.name + ": APK signature verification failed (check Java/tool stderr)")
            else:
                cert_sets.append(tuple(rec["signer_sha256"]))
    for name, tool in [("Android package/version identity", aapt), ("APK signatures", signer)]:
        if not tool:
            result["missing_checks"].append(name)
    if identities:
        if sum(not i["split"] for i in identities) != 1:
            result["errors"].append("Expected exactly one base APK; missing base or mixed package sets")
        if len({i["version_code"] for i in identities}) != 1:
            result["errors"].append("Mixed versionCodes")
        if len({i["split"] for i in identities}) != len(identities):
            result["errors"].append("Duplicate split identities")
        required = {t for i in identities for t in i["required_split_types"]}
        supplied = {t for i in identities for t in i["split_types"]}
        if required - supplied:
            result["errors"].append("Missing required split types: " + ", ".join(sorted(required - supplied)))
    if cert_sets and len(set(cert_sets)) != 1:
        result["errors"].append("Base/split signer sets differ")
    if reference_cert and cert_sets:
        cert = reference_cert.replace(":", "").lower()
        matched = all(cert in c for c in cert_sets)
        result["official_certificate_comparison"] = "matched_supplied_reference" if matched else "mismatch"
        if not matched:
            result["errors"].append("Signer differs from supplied reference certificate")
    if manifest.exists():
        if data.get("status") in ("attempting", "failed"):
            result["errors"].append("Source attempt did not finish successfully")
        for rec in data.get("files", []) + data.get("extracted_files", []):
            path = acquisition_root / rec["file"]
            if not path.is_file() or sha256(path) != rec["sha256"]:
                result["errors"].append("Source manifest file missing or hash mismatch: " + rec["file"])
        declared = data.get("declared_files")
        if declared is not None and sorted(declared) != sorted(x.name for x in files):
            result["errors"].append("Source-declared APK list differs from local APKs")
        result["source_declared_set_complete"] = declared is not None and not result["errors"]
    else:
        result["source_declared_set_complete"] = None
    result["status"] = "failed" if result["errors"] else ("incomplete_verification" if result["missing_checks"] else "verified")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, help="Sample directory, APK, APKS, XAPK or ZIP")
    p.add_argument("--package", required=True)
    p.add_argument("--version-code", type=int, help="Required versionCode; defaults to acquisition record, conflicts are rejected")
    p.add_argument("--reference-cert", help="Independently obtained signer SHA-256; no implicit trust in mirror records")
    p.add_argument("--sdk")
    p.add_argument("--report", help="Defaults to verification.json in directory, or next to a single input file")
    args = p.parse_args()
    if args.reference_cert and not re.fullmatch(r"[a-fA-F0-9]{64}", args.reference_cert.replace(":", "")):
        p.error("Reference certificate must be a SHA-256 hex digest")
    source = Path(args.input).expanduser().resolve()
    emit("校验归档", "running", "开始核对包名、版本、必需分包和签名。")
    report = Path(args.report) if args.report else (source / "verification.json" if source.is_dir() else source.with_name(source.name + ".verification.json"))
    try:
        if source.is_dir():
            result = verify(source, args.package, args.version_code, args.reference_cert, args.sdk)
        else:
            with tempfile.TemporaryDirectory(prefix="apk-verify-") as tmp:
                root = Path(tmp)
                unpack_apks(source, root / "apks")
                result = verify(root, args.package, args.version_code, args.reference_cert, args.sdk,
                                acquisition_root=source_record_root(source))
                result["input_archive_sha256"] = sha256(source)
                # Preserve actual tool evidence after the temporary APK extraction is removed.
                import shutil
                if (root / "verification-details").exists():
                    shutil.copytree(root / "verification-details", report.with_suffix(".details"), dirs_exist_ok=True)
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
        result = {"status": "failed", "files": [], "errors": [str(exc)], "error_type": type(exc).__name__}
    write_json(report, result)
    emit("校验归档", "succeeded" if result["status"] == "verified" else "failed",
         "身份、分包和签名校验通过。" if result["status"] == "verified" else
         "校验未通过或依赖不完整；按报告中的错误/缺失项处理。")
    print(json.dumps({"status": result["status"], "apk_count": len(result["files"]), "errors": result["errors"], "report": str(report)}, ensure_ascii=False))
    return {"verified": 0, "failed": 1, "incomplete_verification": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
