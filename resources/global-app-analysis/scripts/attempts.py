#!/usr/bin/env python3
"""Per-target download attempts, source deduplication and bounded Web Search batches."""
import argparse
import datetime
import json
from pathlib import Path
import re
import sys
import urllib.parse

from apk_utils import public_url, write_json


FAMILIES = {
    "google-play": ("play.google.com", "play.googleapis.com"),
    "apkpure": ("apkpure.com", "apkpure.net", "pureapk.com"),
    "aptoide": ("aptoide.com",), "apkcombo": ("apkcombo.com", "apkcombo.app"),
    "apkcube": ("apkcube.com",), "ldplayer": ("ldplayer.net",),
    "memuplay": ("memuplay.com",), "pgyer": ("pgyer.com",),
}
STATUSES = ("started", "failed", "waiting_user", "dependency_missing", "downloaded", "verified",
            "verification_failed", "unavailable", "redirected", "old_version_only")
SEARCH_ROUNDS_PER_BATCH = 3


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def host(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("Use a public HTTP(S) source page/endpoint without credentials")
    name = u.hostname.lower().rstrip(".")
    # Do not strip a two-letter registered label such as id.co.uk as a locale.
    parts = name.split(".")
    base_labels = 3 if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "net", "org", "gov", "edu", "ac") else 2
    while len(name.split(".")) > base_labels:
        prefix, rest = name.split(".", 1)
        if prefix in ("www", "m", "mobile") or re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", prefix):
            name = rest
        else:
            break
    return name


def source_key(url=None, channel=None):
    if url:
        name = host(url)
        for family, domains in FAMILIES.items():
            if any(name == d or name.endswith("." + d) for d in domains):
                return "site:" + family
        return "site:" + name
    if not channel:
        raise ValueError("Provide a source URL or a local/device channel")
    key = channel.strip().lower()
    return ("site:" if key in FAMILIES else "channel:") + key


def equivalent(a, b):
    return a == b or (a.startswith("site:") and b.startswith("site:")
                     and (a[5:].endswith("." + b[5:]) or b[5:].endswith("." + a[5:])))


def candidate(data, url):
    key = source_key(url=url)
    tried = [a for a in data["attempts"] if any(equivalent(key, s) for s in a["sources"])]
    return {"source_key": key, "eligible": not tried, "already_attempted_ids": [a["id"] for a in tried]}


def device_profile(profile):
    if profile is None:
        return None
    if not isinstance(profile, dict) or set(profile) != {"abi", "sdk_level", "density"}:
        raise ValueError("Profile must contain exactly abi, sdk_level and density")
    if not isinstance(profile["abi"], str) or not profile["abi"].strip():
        raise ValueError("Profile ABI is required")
    for key in ("sdk_level", "density"):
        if type(profile[key]) is not int or profile[key] <= 0:
            raise ValueError("Profile SDK level and density must be positive integers")
    return {**profile, "abi": profile["abi"].strip()}


def begin(data, *, channel, method, url=None, search_round=0, profile=None, parent_id=None, reason=None):
    key = source_key(url, channel)
    profile = device_profile(profile)
    if not method.strip():
        raise ValueError("An actual acquisition method is required")
    parent = None
    if parent_id is not None:
        parent = next((a for a in data["attempts"] if a["id"] == parent_id), None)
        if parent is None:
            raise ValueError("Unknown parent attempt")
        if parent["status"] not in {"verified", "verification_failed", "old_version_only", "failed", "unavailable"}:
            raise ValueError("Parent must be a completed acquisition attempt")
        if parent["method"] != method or not any(equivalent(key, s) for s in parent["sources"]):
            raise ValueError("Profile change must keep the parent source and method")
        if profile is None or parent.get("profile") is None or profile == parent["profile"]:
            raise ValueError("Profile change requires a different recorded device profile")
        if not reason or not reason.strip():
            raise ValueError("Profile change requires an evidence-based reason")
        if search_round:
            raise ValueError("Linked profile change does not reserve or reopen a search round")
    elif reason:
        raise ValueError("A profile change reason requires a parent attempt")
    current_round = len(data["search_rounds"])
    if parent is None and current_round and search_round == 0:
        raise ValueError("Search fallback has started; new sources must use the current reserved search round")
    if search_round < 0 or search_round > current_round:
        raise ValueError("Reserve the search round before beginning its candidates")
    if search_round and search_round != current_round:
        raise ValueError("Use the current search round; earlier rounds cannot be reopened for new sources")
    for a in data["attempts"]:
        same_source = any(equivalent(key, s) for s in a["sources"])
        if same_source and (search_round > 0 or a["method"] == method) and (
                parent is None or a.get("profile") == profile):
            raise ValueError(f"Source/method already attempted as id {a['id']}; do not repeat it")
    item = {"id": len(data["attempts"]) + 1, "channel": channel, "method": method,
            "sources": [key], "source_urls": [public_url(url)] if url else [],
            "search_round": parent["search_round"] if parent else search_round,
            "profile": profile, "status": "started", "started_at": now()}
    if parent:
        item.update(parent_attempt_id=parent_id, profile_change_reason=reason.strip())
    data["attempts"].append(item)
    return item


def finish(data, attempt_id, status, reason=None, resolved_urls=(), artifact=None, digest=None):
    item = next((a for a in data["attempts"] if a["id"] == attempt_id), None)
    if item is None:
        raise ValueError("Unknown attempt id")
    previous = item["status"]
    if previous == "downloaded":
        allowed = {"verified", "verification_failed", "old_version_only"}
    elif previous in ("waiting_user", "dependency_missing"):
        allowed = set(STATUSES)
    elif previous == "started":
        allowed = set(STATUSES) - {"started"}
    else:
        allowed = set()
    if status not in allowed:
        raise ValueError("Finished attempts cannot be restarted or overwritten; resume only a waiting attempt after its condition changes")
    keys = [source_key(url=u) for u in resolved_urls]
    if digest and not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise ValueError("Artifact SHA-256 must be a hex digest")
    duplicates = [a["id"] for a in data["attempts"] if a["id"] != attempt_id and digest
                  and a.get("sha256") == digest.lower()]
    item.update(status=status, updated_at=now())
    if reason:
        item["reason"] = reason
    for key, url in zip(keys, resolved_urls):
        if key not in item["sources"]:
            item["sources"].append(key)
        sanitized = public_url(url)
        if sanitized not in item["source_urls"]:
            item["source_urls"].append(sanitized)
    if artifact:
        item["artifact"] = artifact
    if digest:
        item["sha256"] = digest.lower()
        item["same_artifact_attempt_ids"] = duplicates
    return item


def search_rounds_remaining(data):
    resumptions = data.get("search_resumptions", [])
    batch_start = resumptions[-1]["after_round"] if resumptions else 0
    return SEARCH_ROUNDS_PER_BATCH - (len(data["search_rounds"]) - batch_start)


def resume_search(data, after_round, reason):
    if after_round != len(data["search_rounds"]) or search_rounds_remaining(data) != 0:
        raise ValueError("Resume only the current exhausted search batch")
    if not reason.strip():
        raise ValueError("Record the user's decision and the next search approach")
    item = {"after_round": after_round, "reason": reason.strip(), "resumed_at": now()}
    data.setdefault("search_resumptions", []).append(item)
    return item


def search_round(data, queries):
    if search_rounds_remaining(data) <= 0:
        raise ValueError("Three search rounds exhausted; wait for user confirmation before resuming")
    normalize = lambda s: " ".join(s.split()).casefold()
    previous = {normalize(q) for r in data["search_rounds"] for q in r["queries"]}
    fresh = []
    for query in queries:
        key = normalize(query)
        if key and key not in previous:
            fresh.append(query.strip())
            previous.add(key)
    if not fresh:
        raise ValueError("All queries were already used; choose a new search angle")
    item = {"round": len(data["search_rounds"]) + 1, "queries": fresh, "started_at": now()}
    data["search_rounds"].append(item)
    return item


def summary(data):
    domains = sorted({host(u) for a in data["attempts"] for u in a["source_urls"]})
    return {"package": data["package"], "version_policy": data["version_policy"],
            "search_rounds_used": len(data["search_rounds"]), "search_rounds_remaining": search_rounds_remaining(data),
            "attempted_sources": sorted({s for a in data["attempts"] for s in a["sources"]}),
            "search_exclusion_terms": ["-site:" + d for d in domains], "attempts": data["attempts"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("init", "begin", "finish", "candidate", "search-round", "resume-search", "summary"):
        s = sub.add_parser(name)
        s.add_argument("--ledger", required=True)
        if name == "init":
            s.add_argument("--package", required=True)
            s.add_argument("--version-policy", required=True, help="Task requirement, e.g. versionCode=128 or latest-available")
        elif name == "begin":
            s.add_argument("--channel", required=True)
            s.add_argument("--method", required=True)
            s.add_argument("--url")
            s.add_argument("--search-round", type=int, default=0)
            s.add_argument("--profile", help="JSON file with abi, sdk_level and density; no account/device credentials")
            s.add_argument("--parent-id", type=int, help="Completed attempt linked to a demonstrated device/profile change")
            s.add_argument("--reason", help="Observed reason/evidence for the profile change")
        elif name == "finish":
            s.add_argument("--id", type=int, required=True)
            s.add_argument("--status", choices=STATUSES, required=True)
            s.add_argument("--reason")
            s.add_argument("--resolved-url", action="append", default=[])
            s.add_argument("--artifact")
            s.add_argument("--sha256")
        elif name == "candidate":
            s.add_argument("--url", required=True)
        elif name == "search-round":
            s.add_argument("--query", action="append", required=True)
        elif name == "resume-search":
            s.add_argument("--after-round", type=int, required=True)
            s.add_argument("--reason", required=True, help="User's decision and the next search approach")
    args = p.parse_args()
    path = Path(args.ledger).expanduser().resolve()
    try:
        if args.command == "init" and not path.exists():
            if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", args.package):
                raise ValueError("Invalid Android package name")
            data = {"package": args.package, "version_policy": args.version_policy, "attempts": [], "search_rounds": []}
            write_json(path, data)
        else:
            data = json.loads(path.read_text())
        if args.command == "init":
            if data["package"] != args.package or data["version_policy"] != args.version_policy:
                raise ValueError("Ledger belongs to a different target/version requirement; do not overwrite it")
            result = summary(data)
        elif args.command == "begin":
            profile = json.loads(Path(args.profile).read_text()) if args.profile else None
            result = begin(data, channel=args.channel, method=args.method, url=args.url,
                           search_round=args.search_round, profile=profile, parent_id=args.parent_id, reason=args.reason)
        elif args.command == "finish":
            result = finish(data, args.id, args.status, args.reason, args.resolved_url, args.artifact, args.sha256)
        elif args.command == "candidate":
            result = candidate(data, args.url)
        elif args.command == "search-round":
            result = search_round(data, args.query)
        elif args.command == "resume-search":
            result = resume_search(data, args.after_round, args.reason)
        else:
            result = summary(data)
        if args.command in ("begin", "finish", "search-round", "resume-search"):
            write_json(path, data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
