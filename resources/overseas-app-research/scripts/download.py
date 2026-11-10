#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Download original APK artifacts; all commands require an explicit output directory."""
import argparse
import base64
import datetime
import gzip
import json
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid

from apk_utils import json_get, opener, public_url, sha256, transfer, unpack_apks, write_json
from preflight import require_device_environment
from progress import emit


PURE_API = "https://api.pureapk.com/m/v3/cms/app_version"
PURE_HEADERS = {
    "x-cv": "3172501", "x-sv": "29", "x-abis": "arm64-v8a,armeabi-v7a,armeabi", "x-gp": "1",
    "Ual-Access-Businessid": "projecta",
    "Ual-Access-ProjectA": '{"pn":"com.apkpure.aegon","vn":"3.17.25.01","lm":"1"}',
    "User-Agent": "APKPure/3.17.25.01 (Aegon)",
}


def pure_candidate(op, package):
    url = PURE_API + "?" + urllib.parse.urlencode({"hl": "en", "package_name": package})
    with op.open(urllib.request.Request(url, headers=PURE_HEADERS), timeout=35) as r:
        raw = r.read()
    matches = re.findall(rb"https://download\.pureapk\.com/b/(?:APK|XAPK)/[A-Za-z0-9_=-]+\?[^\x00-\x20\x7f-\xff\"<>]+", raw)
    if not matches:
        raise ValueError("APKPure returned no candidate; not evidence that the app does not exist")
    # Historical protobuf extraction: ordering is only a candidate, not proof of Play's latest version.
    url = matches[0].decode("ascii")
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    encoded = q.get("_fn", [""])[0]
    filename = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode() if encoded else ""
    return url, filename


def aptoide_candidates(op, args):
    profile = f"maxSdk={args.sdk_level}&maxScreen=normal&maxGles=3.2&myCPU={args.abi}&myDensity={args.density}"
    query = {"package_name": args.package, "aab": "1", "q": base64.b64encode(profile.encode()).decode(),
             "language": args.locale, "nodes": "meta,versions"}
    url = "https://ws75.aptoide.com/api/7/app/get?" + urllib.parse.urlencode(query)
    doc = json_get(op, url)
    data = (doc.get("nodes", {}).get("meta", {}).get("data") or doc.get("data") or {})
    if data.get("package") != args.package or not data.get("file", {}).get("path"):
        raise ValueError("Aptoide returned no matching downloadable package for this device profile")
    files = [("base.apk", data["file"])]
    for split in (data.get("aab") or {}).get("splits", []):
        name = split["name"]
        if not name.endswith(".apk"):
            name += ".apk"
        if Path(name).name != name or "\\" in name:
            raise ValueError("Invalid split name from source")
        files.append((name, split))
    return data, files


# The protobuf helpers and play_headers/play_files are adapted from the local
# anonymous-download.py, itself adapted from AuroraOSS/gplayapi AnonymousDeliveryApi/PsRhSigner.
# Upstream: https://gitlab.com/AuroraOSS/gplayapi
def varint(n):
    n &= (1 << 64) - 1
    out = bytearray()
    while n > 127:
        out.append((n & 127) | 128)
        n >>= 7
    return bytes(out) + bytes([n])


def field(tag, value):
    if isinstance(value, int):
        return varint(tag * 8) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint(tag * 8 + 2) + varint(len(value)) + value


def parse_proto(data):
    pos, out = 0, {}
    def vi():
        nonlocal pos
        value, shift = 0, 0
        while pos < len(data) and shift < 70:
            x = data[pos]
            pos += 1
            value |= (x & 127) << shift
            if x < 128:
                return value
            shift += 7
        raise ValueError("Invalid protobuf varint")
    while pos < len(data):
        key = vi()
        tag, typ = key >> 3, key & 7
        if not tag:
            raise ValueError("Invalid protobuf field")
        if typ == 0:
            value = vi()
        elif typ in (1, 2, 5):
            size = vi() if typ == 2 else (8 if typ == 1 else 4)
            if pos + size > len(data):
                raise ValueError("Truncated protobuf field")
            value = data[pos:pos + size]
            pos += size
        else:
            raise ValueError("Unsupported protobuf wire type")
        out.setdefault(tag, []).append(value)
    return out


def compressed(data):
    return base64.urlsafe_b64encode(gzip.compress(data, mtime=0)).decode().rstrip("=")


def play_headers(profile, device_id, country, language):
    millis = int(time.time() * 1000)
    timestamp = field(1, millis // 1000) + field(2, (millis % 1000) * 1000000)
    times = field(6, field(1, field(1, timestamp)) + field(2, timestamp))
    entry = field(1, country) + field(2, timestamp)
    locality = field(2, 1) + field(3, 2) + field(4, "") + field(8, entry) + field(9, entry) + field(11, 0)
    android = (field(1, int(profile["Build.VERSION.SDK_INT"])) + field(2, profile["Build.ID"])
               + field(3, profile["Build.VERSION.RELEASE"]) + field(4, 82201710))
    device = field(1, android) + field(2, b"") + field(3, 1)
    agent = b"".join(field(i, profile[k]) for i, k in [(1, "Build.DEVICE"), (2, "Build.HARDWARE"), (3, "Build.MODEL")])
    agent += (field(4, "Finsky/" + profile["Vending.versionString"]) + field(5, profile["Build.PRODUCT"])
              + field(6, device_id) + field(7, profile["Build.FINGERPRINT"].replace("\\:", ":")))
    head = (field(1, field(1, compressed(times))) + field(11, field(1, compressed(locality)))
            + field(12, field(1, 5)) + field(14, "") + field(20, device) + field(21, agent)
            + field(27, field(1, str(uuid.uuid4())) + field(2, 2)))
    ua = (f"Dalvik/2.1.0 (Linux; U; Android {profile['Build.VERSION.SDK_INT']}; "
          f"{profile['Build.BRAND']} {profile['Build.MODEL']} Build/{profile['Build.ID']})")
    return {"User-Agent": ua, "accept-language": language, "x-dfe-userlanguages": language, "x-ps-rh": compressed(head)}


def play_request_headers(args):
    profile = json.loads(Path(args.device_profile).read_text())
    # A registered anonymous device ID is an input, not a fabricated/random ID.
    device_id = int(Path(args.device_id_file).read_text().strip())
    return play_headers(profile, device_id, args.country.upper(), args.language)


def play_details(op, args):
    # AuroraOSS/gplayapi ItemsAppApi + v2/Item.proto, commit
    # 2f03e8babee8adf791d4f3a3b17c268a704be76c. /details requires an account;
    # /getItems supports the registered device-only X-PS-RH lane.
    headers = play_request_headers(args)
    bits = b"\xfe" + b"\xff" * 15 + b"\x01"  # Fields 1..128, BitSet byte order.
    headers["x-dfe-item-field-mask"] = base64.b64encode(field(3, bits) + field(4, bits)).decode().rstrip("=")
    headers["Content-Type"] = "application/x-protobuf"
    body = field(2, field(1, field(1, field(1, args.package))))
    request = urllib.request.Request("https://play.googleapis.com/fdfe/getItems", data=body, headers=headers)
    with op.open(request, timeout=35) as r:
        response = parse_proto(r.read())
    for item in response.get(11, []):
        metadata = parse_proto(parse_proto(item).get(2, [b""])[0])
        package = parse_proto(metadata.get(1, [b""])[0]).get(1, [b""])[0].decode()
        if package != args.package:
            continue
        generic = parse_proto(metadata.get(3, [b""])[0])
        version = parse_proto(generic.get(2, [b""])[0])
        code = version.get(1, [0])[0]
        if not isinstance(code, int) or code <= 0:
            raise ValueError("Anonymous getItems returned no positive versionCode for the target package")
        return {"source_version_code": code, "source_version": version.get(2, [b""])[0].decode(),
                "metadata_endpoint": request.full_url}
    raise ValueError("Anonymous getItems returned no matching package; check profile, locale and protocol")


def play_files(op, args):
    headers = play_request_headers(args)
    url = "https://play.googleapis.com/fdfe/delivery?" + urllib.parse.urlencode({"doc": args.package, "vc": args.version_code, "ot": 1})
    with op.open(urllib.request.Request(url, headers=headers), timeout=35) as r:
        raw = r.read()
    outer = parse_proto(raw)
    payload = parse_proto(outer.get(1, [b""])[0])
    delivery = parse_proto(payload.get(21, [b""])[0])
    if delivery.get(1, [0])[0] != 1:
        raise ValueError("Anonymous Play delivery denied; check region, profile, registration and protocol before retrying")
    data = parse_proto(delivery.get(2, [b""])[0])
    files = []
    if data.get(3):
        files.append(("base.apk", data[3][0], data.get(19, [b""])[0]))
    for raw_split in data.get(15, []):
        split = parse_proto(raw_split)
        if split.get(5):
            name = "split_" + split[1][0].decode() + ".apk"
            if Path(name).name != name or "\\" in name:
                raise ValueError("Invalid Play split name")
            files.append((name, split[5][0], split.get(9, [b""])[0]))
    if not files or files[0][0] != "base.apk":
        raise ValueError("No base APK in delivery response")
    return files, {"User-Agent": headers["User-Agent"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="source", required=True)
    for source in ("apkpure", "aptoide", "play", "url"):
        s = sub.add_parser(source)
        s.add_argument("--package", required=True)
        s.add_argument("--out", required=True, help="New directory for this source attempt")
        s.add_argument("--proxy", help="HTTP proxy URL, 'direct', or omit to use environment/system settings")
        s.add_argument("--sdk", help="Existing Android SDK root for the required device check")
        s.add_argument("--version-code", type=int, help="Required versionCode, recorded for identity verification; Play queries this version")
        if source == "aptoide":
            s.add_argument("--sdk-level", type=int, default=35)
            s.add_argument("--abi", default="arm64-v8a")
            s.add_argument("--density", type=int, default=480)
            s.add_argument("--locale", default="en_US")
        if source == "play":
            s.add_argument("--device-profile", required=True)
            s.add_argument("--device-id-file", required=True)
            s.add_argument("--country", required=True, help="ISO country code, e.g. PH")
            s.add_argument("--language", required=True, help="Language/region, e.g. en-PH")
        if source == "url":
            s.add_argument("--url", required=True)
            s.add_argument("--filename", required=True, help="APK/APKS/XAPK/ZIP basename")
            s.add_argument("--size", type=int)
            s.add_argument("--sha256")
            s.add_argument("--md5")
    args = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", args.package):
        p.error("Invalid Android package name")
    try:
        environment = require_device_environment(args.sdk)
    except ValueError as exc:
        emit("环境检查", "failed", str(exc))
        print(json.dumps({"status": "environment_failed", "error": str(exc), "downstream_allowed": False}, ensure_ascii=False))
        return 4
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False)
    op = opener(args.proxy)
    report = {"source": args.source, "requested_package": args.package,
              "requested_version_code": args.version_code,
              "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "status": "attempting", "files": [], "installed": False, "launched": False,
              "device_gate": environment}
    report_path = out / "download.json"
    write_json(report_path, report)
    emit("获取安装包", "running", f"通过 {args.source} 获取 {args.package}。")
    try:
        if args.source == "aptoide":
            data, files = aptoide_candidates(op, args)
            report.update(source_version=data["file"].get("vername"), source_version_code=data["file"].get("vercode"),
                          source_certificate_sha1=(data["file"].get("signature") or {}).get("sha1"),
                          declared_files=[name for name, _ in files])
            for index, (name, meta) in enumerate(files, 1):
                emit("获取安装包", "running", f"{args.source}：下载 {index}/{len(files)}，{name}。")
                rec = transfer(op, meta["path"], out / "apks" / name,
                               expected_size=meta.get("filesize") or meta.get("size"), md5=meta.get("md5sum"))
                rec["file"] = "apks/" + name
                report["files"].append(rec)
                write_json(report_path, report)
        elif args.source == "play":
            if args.version_code is None:
                emit("获取安装包", "running", "通过匿名 getItems 查询目标 versionCode。")
                report.update(play_details(op, args))
                args.version_code = report["source_version_code"]
                write_json(report_path, report)
            report["delivery_endpoint"] = "https://play.googleapis.com/fdfe/delivery"
            files, headers = play_files(op, args)
            report.update(source_version_code=args.version_code, declared_files=[name for name, _, _ in files], country=args.country.upper())
            for index, (name, url, digest) in enumerate(files, 1):
                emit("获取安装包", "running", f"Google Play：下载 {index}/{len(files)}，{name}。")
                expected = base64.urlsafe_b64decode(digest + b"=" * (-len(digest) % 4)).hex() if digest else None
                rec = transfer(op, url.decode(), out / "apks" / name, digest=expected, headers=headers)
                rec["file"] = "apks/" + name
                report["files"].append(rec)
                write_json(report_path, report)
        else:
            if args.source == "apkpure":
                url, original_name = pure_candidate(op, args.package)
                filename = args.package + (".xapk" if "/XAPK/" in url else ".apk")
                report["source_filename"] = original_name
                options = {"headers": {"User-Agent": PURE_HEADERS["User-Agent"]}}
            else:
                url, filename = args.url, args.filename
                options = {"expected_size": args.size, "md5": args.md5, "digest": args.sha256}
            if Path(filename).name != filename or "\\" in filename or not filename.lower().endswith((".apk", ".apks", ".xapk", ".zip")):
                raise ValueError("Expected an APK archive basename")
            raw = out / "raw" / filename
            emit("获取安装包", "running", f"下载原始文件 {filename}，完成后提取 APK 清单。")
            rec = transfer(op, url, raw, **options)
            rec["file"] = "raw/" + filename
            report["files"].append(rec)
            apks = unpack_apks(raw, out / "apks")
            report["extracted_files"] = [{"file": str(x.relative_to(out)), "bytes": x.stat().st_size, "sha256": sha256(x)} for x in apks]
        report["status"] = "downloaded_pending_identity_and_signature_verification"
        write_json(report_path, report)
        emit("获取安装包", "succeeded", "原始文件已保存；等待第 4 步身份、分包和签名校验。")
        print(json.dumps({"status": report["status"], "report": str(report_path)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        # Do not echo signed links, proxy credentials or raw server payloads in logs.
        report["error"] = (f"HTTP {exc.code}" if hasattr(exc, "code") else
                           re.sub(r"https?://[^\s]+", "<url>", str(exc)))
        write_json(report_path, report)
        emit("获取安装包 · 渠道尝试", "failed", report["error"] + "；由主流程决定是否换源。")
        print(json.dumps({"status": "failed", "report": str(report_path), "error": report["error"]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
