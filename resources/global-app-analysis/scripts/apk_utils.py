"""Shared transfer and APK archive operations; Python standard library only."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile


def opener(proxy=None):
    if proxy == "direct":
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def public_url(url):
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ""
    if p.port:
        host += ":" + str(p.port)
    path = p.path
    if host == "url-provider.aptoide.com":
        path = "/download/<opaque-link>"
    return urllib.parse.urlunsplit((p.scheme, host, path, "", ""))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_get(op, url):
    with op.open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=35) as r:
        return json.load(r)


def transfer(op, url, dest, *, expected_size=None, md5=None, digest=None, headers=None):
    """Resume only when an expected digest identifies the exact same artifact."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise ValueError("Destination exists; use a new version/attempt directory: " + str(dest))
    part = dest.with_name(dest.name + ".part")
    state = dest.with_name(dest.name + ".part.json")
    identity = {"size": expected_size, "md5": md5, "sha256": digest}
    resume = bool(md5 or digest)
    if not resume or not state.exists() or json.loads(state.read_text()) != identity:
        part.unlink(missing_ok=True)
    write_json(state, identity)
    for attempt in range(3):
        have = part.stat().st_size if part.exists() and resume else 0
        req_headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity", **(headers or {})}
        if have:
            req_headers["Range"] = f"bytes={have}-"
        try:
            with op.open(urllib.request.Request(url, headers=req_headers), timeout=45) as r:
                append = have > 0 and r.status == 206
                if append and not r.headers.get("Content-Range", "").startswith(f"bytes {have}-"):
                    raise ValueError("Invalid resume Content-Range")
                declared = r.headers.get("Content-Length")
                received = 0
                with part.open("ab" if append else "wb") as f:
                    while True:
                        block = r.read(1024 * 256)
                        if not block:
                            break
                        f.write(block)
                        received += len(block)
                if declared is not None and received != int(declared):
                    raise OSError("Truncated HTTP body")
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 416:
                part.unlink(missing_ok=True)
            elif exc.code not in (408, 429, 500, 502, 503, 504):
                raise ValueError(f"HTTP {exc.code} from {public_url(url)}") from None
            if attempt == 2:
                raise ValueError(f"HTTP {exc.code}; retry budget exhausted") from None
            time.sleep(min(2 ** attempt, 4))
        except (OSError, urllib.error.URLError):
            if attempt == 2:
                raise ValueError("Network transfer failed; partial file retained") from None
            time.sleep(2 ** attempt)
    size = part.stat().st_size
    actual = sha256(part)
    if expected_size is not None and size != int(expected_size):
        raise ValueError(f"Size mismatch: {size} != {expected_size}")
    if digest and actual.lower() != digest.lower():
        part.unlink()
        raise ValueError("Source SHA-256 mismatch; rejected downloaded bytes")
    if md5:
        h = hashlib.md5()
        with part.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        if h.hexdigest().lower() != md5.lower():
            part.unlink()
            raise ValueError("Source MD5 mismatch; rejected downloaded bytes")
    with zipfile.ZipFile(part) as z:
        if z.testzip() is not None:
            raise ValueError("ZIP CRC check failed")
        names = z.namelist()
        if "AndroidManifest.xml" not in names and not any(n.lower().endswith(".apk") for n in names):
            raise ValueError("Response is neither an APK nor an APK archive")
    part.rename(dest)
    state.unlink(missing_ok=True)
    return {"file": dest.name, "bytes": size, "sha256": actual,
            "source_url": public_url(url), "source_checksum_verified": bool(md5 or digest),
            "expected_source_bytes": expected_size, "expected_source_md5": md5, "expected_source_sha256": digest}


def unpack_apks(source, out):
    source, out = Path(source), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    with zipfile.ZipFile(source) as z:
        if z.testzip() is not None:
            raise ValueError("ZIP CRC check failed")
        if "AndroidManifest.xml" in z.namelist():
            target = out / "base.apk"
            with source.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            return [target]
        for info in z.infolist():
            if not info.filename.lower().endswith(".apk"):
                continue
            p = PurePosixPath(info.filename)
            if p.is_absolute() or ".." in p.parts or "\\" in info.filename:
                raise ValueError("Unsafe archive member")
            target = out / p.name
            with z.open(info) as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            with zipfile.ZipFile(target) as apk:
                if "AndroidManifest.xml" not in apk.namelist() or apk.testzip() is not None:
                    raise ValueError("Invalid nested APK: " + p.name)
            written.append(target)
    if not written:
        raise ValueError("Archive contains no APK files")
    return written


def sdk_roots(explicit=None):
    choices = [explicit, os.environ.get("ANDROID_SDK_ROOT"), os.environ.get("ANDROID_HOME"),
               str(Path.home() / "Library/Android/sdk"), str(Path.home() / "Android/Sdk")]
    return list(dict.fromkeys(Path(p).expanduser() for p in choices if p and Path(p).expanduser().is_dir()))


def find_tool(name, sdk=None):
    if shutil.which(name):
        return shutil.which(name)
    for root in sdk_roots(sdk):
        paths = [root / "platform-tools" / name, root / "emulator" / name]
        paths += sorted(root.glob("build-tools/*/" + name),
                        key=lambda p: tuple(int(n) for n in re.findall(r"\d+", p.parent.name)), reverse=True)
        for p in paths:
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    return None


def java_env():
    env = os.environ.copy()
    if not env.get("JAVA_HOME"):
        for jbr in [Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home"),
                    Path.home() / "Applications/Android Studio.app/Contents/jbr/Contents/Home"]:
            if jbr.is_dir():
                env["JAVA_HOME"] = str(jbr)
                env["PATH"] = str(jbr / "bin") + os.pathsep + env.get("PATH", "")
                break
    return env
