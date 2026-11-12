"""Check the evidence-review and delivery records against current task files."""

import argparse
import hashlib
import json
from pathlib import Path
import re


CHECKS = {
    "research": {"10.1", "10.2", "10.3", "10.4"},
    "ued": {"album"},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def present(value):
    return isinstance(value, str) and bool(value.strip())


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_path(root, reference, label):
    require(present(reference), f"{label}: missing evidence reference")
    name, marker, anchor = reference.partition("#")
    path = root / name
    require(name and path.is_file(), f"{label}: evidence file not found: {name}")
    if marker:
        require(re.fullmatch(r"L[1-9][0-9]*", anchor), f"{label}: use a #L<number> line reference")
        line = int(anchor[1:])
        with path.open(encoding="utf-8") as source:
            require(any(number == line for number, _ in enumerate(source, 1)),
                    f"{label}: evidence line not found: {reference}")
    else:
        with path.open("rb") as source:
            require(source.read(1), f"{label}: evidence file is empty: {name}")
    return name


def load_scope(root, name):
    scope = json.loads((root / name).read_text(encoding="utf-8"))
    require(type(scope["h5_in_scope"]) is bool, "scope must explicitly record whether H5 is in scope")
    return scope["h5_in_scope"], evidence_path(root, scope["h5_evidence"], "H5 scope")


def revision(root, files, scope, scope_evidence):
    require(isinstance(files, list) and files and all(present(p) for p in files),
            "facts must list the files that define the current facts")
    entries = [(name, file_hash(root / name)) for name in sorted(set(files) | {scope, scope_evidence})]
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def check_review(root, record, current, h5_in_scope, partial):
    targets = set(record["targets"])
    require(targets and targets <= CHECKS.keys(), "record the research and/or UED delivery targets")
    base = {"pages", "business"} if "research" in targets else {"pages"}
    required = base | {"h5"} if h5_in_scope else base
    rounds = record["rounds"]
    require(len(rounds) >= 2, "complete the first review and at least one separate re-review")
    round_ids = set()
    for wave in rounds:
        require(present(wave["id"]) and wave["id"] not in round_ids, "review round IDs must be distinct")
        round_ids.add(wave["id"])
        require(present(wave["revision"]), "record the revision reviewed by each round")
        planned = set(wave["surfaces"])
        require(base <= planned <= base | {"h5"} and planned == wave["results"].keys(),
                "a completed round must include every area planned for that round")
        for area, result in wave["results"].items():
            label = f"round {wave['id']}, {area}"
            require(result["method"] in {"isolated", "in_session"}
                    and result["status"] in {"passed", "needs_work", "partial_passed"},
                    f"{label}: review area needs a method and verdict")
            evidence_path(root, result["evidence"], label)
    latest = rounds[-1]
    require(latest["revision"] == current, "current facts require a new review from 9.1")
    for wave in rounds:
        if wave["revision"] == current:
            require(set(wave["results"]) == required, "review must cover every area for the current scope")
    require(sum(required <= wave["results"].keys() for wave in rounds) >= 2,
            "complete two separate rounds covering every area for the current scope")

    unresolved = {key: item for key, item in record["issues"].items() if item["status"] != "closed"}
    for issue_id, issue in record["issues"].items():
        require(issue["status"] in {"open", "closed", "blocked"}, f"{issue_id}: issue needs a valid status")
        evidence_path(root, issue["evidence"], issue_id)
        if issue["status"] == "blocked":
            require(all(present(issue.get(field)) for field in ("layer", "attempt", "resume")),
                    f"{issue_id}: blocker needs a layer, attempt evidence and a resumption condition")
            evidence_path(root, issue["attempt"], f"{issue_id} blocker")
    if partial:
        permission = record["partial"]
        require(unresolved, "record the verified subset and remaining gaps")
        evidence_path(root, permission["included"], "verified subset")
        require(all(result["status"] in {"passed", "partial_passed"} for result in latest["results"].values()),
                "the latest review must approve the verified subset in every area")
        if permission["reason"] == "user_request":
            evidence_path(root, permission["evidence"], "user request for partial delivery")
        else:
            require(permission["reason"] == "blocked"
                    and all(item["status"] == "blocked" for item in unresolved.values()),
                    "partial delivery requires a user request or evidenced blockers for remaining work")
    else:
        require(not unresolved, "close all issues before formal delivery: " + ", ".join(unresolved))
        require(all(result["status"] == "passed" for result in latest["results"].values()),
                "all review areas must pass for formal delivery")


def check_artifacts(root, record, current, partial):
    delivery = record["delivery"]
    require(delivery["revision"] == current and delivery["partial"] is partial,
            "delivery checks must refer to the current facts and the selected delivery type")
    targets = set(record["targets"])
    artifacts = delivery["artifacts"]
    require({item["target"] for item in artifacts} == targets, "check artifacts for every delivery target")
    for item in artifacts:
        name = item["path"]
        require(file_hash(root / name) == item["sha256"], f"{name}: artifact changed after verification")
        require(all(present(item["checks"].get(step)) for step in CHECKS[item["target"]]),
                f"{name}: missing a required report or album check")
        for step in sorted(CHECKS[item["target"]]):
            evidence_path(root, item["checks"][step], f"{name} check {step}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("revision", "review", "deliver"))
    parser.add_argument("record", type=Path)
    parser.add_argument("--partial", action="store_true")
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        root = args.record.parent
        h5_in_scope, scope_evidence = load_scope(root, record["scope"])
        current = revision(root, record["facts"], record["scope"], scope_evidence)
        if args.phase == "revision":
            print(current)
            return
        check_review(root, record, current, h5_in_scope, args.partial)
        if args.phase == "deliver":
            check_artifacts(root, record, current, args.partial)
        print(f"{args.phase} passed ({'partial' if args.partial else 'formal'})")
    except (KeyError, TypeError, AttributeError, ValueError, OSError) as error:
        parser.exit(1, f"{args.phase} refused: {error}\n")


if __name__ == "__main__":
    main()
