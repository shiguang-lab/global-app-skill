"""Check the evidence-review and delivery records against current task files."""

import argparse
import hashlib
import json
from pathlib import Path
import re

from task_ledger import limit, open_ledger, require

CHECKS = {
    "research": {"10.1", "10.2", "10.3", "10.4"},
    "ued": {"album"},
}


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


def evidence_snapshot(root, reference, label, after=0):
    path = (root / evidence_path(root, reference, label)).resolve()
    modified = path.stat().st_mtime_ns
    require(modified > after, f"{label}: evidence must be recorded after the checkpoint began")
    return {"ref": reference, "path": str(path), "sha256": file_hash(path), "modified_ns": modified}


def check_snapshot(root, snapshot, label):
    current = evidence_snapshot(root, snapshot["ref"], label)
    require(all(current[key] == snapshot[key] for key in ("ref", "path", "sha256")),
            f"{label}: checkpoint evidence changed")


def load_scope(root, name):
    scope = json.loads((root / name).read_text(encoding="utf-8"))
    require(type(scope["h5_in_scope"]) is bool, "scope must explicitly record whether H5 is in scope")
    return scope, evidence_path(root, scope["h5_evidence"], "H5 scope")


def revision(root, files, scope, scope_evidence):
    require(isinstance(files, list) and files and all(present(p) for p in files),
            "facts must list the files that define the current facts")
    entries = [(name, file_hash(root / name)) for name in sorted(set(files) | {scope, scope_evidence})]
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def review_surfaces(record, h5_in_scope):
    targets = set(record["targets"])
    require(targets and targets <= CHECKS.keys(), "record the research and/or UED delivery targets")
    base = {"pages", "business"} if "research" in targets else {"pages"}
    return base | {"h5"} if h5_in_scope else base


def review_plan(record, scope):
    surfaces = review_surfaces(record, scope["h5_in_scope"])
    items = scope.get("review_items")
    require(isinstance(items, dict) and items.keys() == surfaces,
            "scope.review_items must list every applicable review area")
    for area, entries in items.items():
        require(isinstance(entries, dict) and entries and
                all(re.fullmatch(r"[\w.-]+", key) and present(value) for key, value in entries.items()),
                f"{area}: list required item IDs and descriptions in scope.review_items")
    return items


def check_item_results(items, results):
    for area, planned in items.items():
        result = results[area]
        entries = result.get("items")
        require(isinstance(entries, dict) and entries.keys() == planned.keys(),
                f"{area}: record exactly the planned review item IDs")
        statuses = {item["status"] for item in entries.values()}
        require(statuses <= {"passed", "needs_work", "blocked"},
                f"{area}: invalid review item status")
        require((result["status"] == "passed") == (statuses == {"passed"}),
                f"{area}: the area verdict must reflect its item results")


def check_retry_state(root, ledger, user_requested=False):
    require(not ledger.pending, "record the result of every reserved retry before delivery")
    require(not ledger.waiting or user_requested, "wait for the user's decision on: " + ", ".join(sorted(ledger.waiting)))
    for event in ledger.events:
        if event["event"] in {"finish", "resume", "cancel-review"}:
            check_snapshot(root, event["evidence"], f"checkpoint {event['id']}")


def check_review(root, ledger, record, current, items, partial):
    rounds = ledger.rounds
    require(ledger.active is None, "finish the open review before delivery")
    check_retry_state(root, ledger, partial and record.get("partial", {}).get("reason") == "user_request")
    require(len(rounds) >= 2, "complete the first review and at least one separate re-review")
    for start, finish in rounds:
        require(set(start["surfaces"]) == finish["results"].keys(),
                "a completed round must include every area planned for that round")
        for area, result in finish["results"].items():
            check_snapshot(root, result["evidence"], f"round {start['id']}, {area}")
    latest_start, latest = rounds[-1]
    require(latest_start["revision"] == current, "current facts require a new review from 9.1")
    require(latest_start.get("items") == items and latest["results"].keys() == items.keys(),
            "review must cover every area and item for the current scope")
    check_item_results(items, latest["results"])
    require(sum(all(planned.keys() <= wave["results"].get(area, {}).get("items", {}).keys()
                    for area, planned in items.items()) for _, wave in rounds) >= 2,
            "complete two separate rounds covering every area and item for the current scope")

    unresolved = {key: item for key, item in record["issues"].items() if item["status"] != "closed"}
    for issue_id, issue in record["issues"].items():
        require(issue["status"] in {"open", "closed", "blocked"}, f"{issue_id}: issue needs a valid status")
        evidence_path(root, issue["evidence"], issue_id)
        if issue["status"] == "blocked":
            check_blocker(root, ledger, issue_id, issue)
    approved = set()
    reviewed_issues = set()
    for area, result in latest["results"].items():
        for item_id, item in result["items"].items():
            label = f"{area}/{item_id}"
            check_snapshot(root, item["evidence"], label)
            if item["status"] == "passed":
                approved.add(label)
                continue
            issue_id = item.get("issue")
            require(issue_id in unresolved, f"{label}: link unfinished work to an unresolved issue")
            reviewed_issues.add(issue_id)
            issue = unresolved[issue_id]
            require((item["status"] == "blocked") == (issue["status"] == "blocked"),
                    f"{label}: item and issue disagree about whether work is blocked")
            if item["status"] == "blocked":
                require(item["blocker"] == issue, f"{label}: blocker changed after review")
                for confirmation in item["unavailable_paths"].values():
                    check_snapshot(root, confirmation["evidence"], label)
    require(reviewed_issues == unresolved.keys(), "re-review every unresolved issue before delivery")
    if partial:
        permission = record["partial"]
        require(approved and unresolved, "record passed items and remaining gaps")
        evidence_path(root, permission["included"], "verified subset")
        require(all(result["status"] in {"passed", "partial_passed"} for result in latest["results"].values()),
                "the latest review must approve the verified subset in every area")
        if permission["reason"] == "user_request":
            last_wait = max((e["at_ns"] for e in ledger.events if e["event"] == "wait"
                             and ledger.waiting.intersection(e["keys"])), default=0)
            evidence_snapshot(root, permission["evidence"], "user request for partial delivery", after=last_wait)
        else:
            require(permission["reason"] == "blocked"
                    and all(item["status"] == "blocked" for item in unresolved.values()),
                    "partial delivery requires a user request or evidenced blockers for remaining work")
    else:
        require(not unresolved, "close all issues before formal delivery: " + ", ".join(unresolved))
        require(all(result["status"] == "passed" for result in latest["results"].values()),
                "all review areas must pass for formal delivery")


def check_blocker(root, ledger, issue_id, issue):
    require(all(present(issue.get(field)) for field in ("layer", "resume")),
            f"{issue_id}: blocker needs a layer and a resumption condition")
    kind, paths = issue["kind"], issue["paths"]
    require(kind in {"app_host", "other"} and paths, f"{issue_id}: record the blocker and evaluated paths")
    if kind == "app_host":
        require({"original_host", "isolated_host"} <= paths.keys(),
                f"{issue_id}: evaluate the original host and an isolated App host path")
    refs = set()
    for name, path in paths.items():
        label = f"{issue_id}, {name}"
        if path["status"] == "attempted":
            key = path["key"]
            require(key.startswith("technical:") and key not in ledger.waiting,
                    f"{label}: a pending budget decision is not a blocker")
            attempt = max(((start, end) for start, end in ledger.attempts.values()
                           if key in start["keys"] and start.get("path") == name),
                          key=lambda pair: pair[0]["id"], default=None)
            require(attempt and attempt[0]["id"] == path["attempt"] and attempt[1]["outcome"] == "failed",
                    f"{label}: cite the latest completed failed attempt on this path")
            ref = attempt[1]["evidence"]["ref"]
        else:
            require(path["status"] == "unavailable" and present(path.get("reason")),
                    f"{label}: provide a verified reason the path cannot run")
            ref = path["evidence"]
            evidence_path(root, ref, label)
        require(ref not in refs, f"{label}: provide distinct evidence for each path")
        refs.add(ref)


def seal_item(root, record, label, item):
    require(present(item.get("assessment")), f"{label}: record the review finding or why prior evidence still applies")
    sealed = {**item, "evidence": evidence_snapshot(root, item["evidence"], label)}
    if item["status"] != "blocked":
        return sealed
    issue = record["issues"].get(item.get("issue"))
    require(issue and issue["status"] == "blocked", f"{label}: reference the blocked issue reviewed")
    paths = {name: path for name, path in issue["paths"].items() if path["status"] == "unavailable"}
    confirmations = item.get("unavailable_paths", {})
    require(isinstance(confirmations, dict) and confirmations.keys() == paths.keys(),
            f"{label}: reviewer must verify every unavailable path")
    verified = {}
    for name, path in paths.items():
        confirmation = confirmations[name]
        require(present(confirmation.get("prerequisite")) and present(confirmation.get("observation"))
                and confirmation.get("evidence") == path["evidence"],
                f"{label}/{name}: record the checked prerequisite, observed limit and matching evidence")
        verified[name] = {**confirmation,
                          "evidence": evidence_snapshot(root, path["evidence"], f"{label}/{name}")}
    return {**sealed, "blocker": issue, "unavailable_paths": verified}


def finish_review(root, ledger, args, current, record):
    start = ledger.active
    require(start and start["id"] == args.id, "review ID is not open")
    require(start["revision"] == current, "facts changed during review; cancel it and start a new round")
    results = json.loads((root / args.results).read_text(encoding="utf-8"))
    require(results.keys() == set(start["surfaces"]), "a completed round must include every planned area")
    require("items" in start, "restart review from 9.1 with a review item plan")
    check_item_results(start["items"], results)
    for area, result in results.items():
        require(result["method"] in {"isolated", "in_session"}
                and result["status"] in {"passed", "needs_work", "partial_passed"},
                f"{area}: review area needs a method and verdict")
        evidence = evidence_snapshot(root, result["evidence"], area, after=start["at_ns"])
        entries = {key: seal_item(root, record, f"{area}/{key}", item)
                   for key, item in result["items"].items()}
        results[area] = {**result, "evidence": evidence, "items": entries}
    return ledger.add("finish-review", ref_id=args.id, results=results)


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
    parser.add_argument("phase", choices=("init", "reserve", "finish", "resume", "revision", "begin-review",
                                          "finish-review", "cancel-review", "check-ledger", "review", "deliver"))
    parser.add_argument("record", type=Path)
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--key", action="append", help="Budget key; repeat to reserve both applicable budgets")
    parser.add_argument("--action", help="The next action and what it will verify")
    parser.add_argument("--path", help="Path ID for an attempt cited in blocker evidence")
    parser.add_argument("--id", type=int, help="Checkpoint ID returned when the operation began")
    parser.add_argument("--outcome", choices=("passed", "failed", "unavailable"))
    parser.add_argument("--evidence", help="Evidence file or file#L<number>, relative to the task directory")
    parser.add_argument("--results", help="JSON object of review results, keyed by review area")
    args = parser.parse_args()
    try:
        root = args.record.parent
        phase = args.phase
        if phase in {"revision", "begin-review", "finish-review", "review", "deliver"}:
            record = json.loads(args.record.read_text(encoding="utf-8"))
            scope, scope_evidence = load_scope(root, record["scope"])
            current = revision(root, record["facts"], record["scope"], scope_evidence)
            if phase == "revision":
                print(current)
                return
            items = review_plan(record, scope)
        waiting = []
        with open_ledger(root, initialize=phase == "init",
                         write=phase not in {"check-ledger", "review", "deliver"}) as ledger:
            if phase == "init":
                print("task-checks.jsonl ready")
            elif phase == "reserve":
                require(args.key and present(args.action), "reserve requires --key and --action")
                waiting = ledger.exhausted(args.key)
                if waiting:
                    ledger.add("wait", keys=waiting)
                else:
                    event = ledger.add("reserve", keys=args.key, action=args.action, path=args.path)
                    print(json.dumps({"id": event["id"],
                                      "remaining": {k: limit(k) - ledger.used[k] for k in args.key}}))
            elif phase == "finish":
                start = ledger.pending.get(args.id)
                require(start and args.outcome, "finish requires an open --id and --outcome")
                proof = evidence_snapshot(root, args.evidence, "retry result", after=start["at_ns"])
                ledger.add("finish", ref_id=args.id, outcome=args.outcome, evidence=proof)
            elif phase == "resume":
                require(args.key and len(args.key) == 1, "resume requires one --key")
                key = args.key[0]
                wait = next((e["at_ns"] for e in reversed(ledger.events)
                             if e["event"] == "wait" and key in e["keys"]), 0)
                proof = evidence_snapshot(root, args.evidence, "user approval", after=wait)
                ledger.add("resume", key=key, evidence=proof)
            elif phase == "begin-review":
                event = ledger.add("begin-review", revision=current, surfaces=sorted(items), items=items)
                print(json.dumps({"id": event["id"], "revision": current, "surfaces": event["surfaces"],
                                  "items": items}, ensure_ascii=False))
            elif phase == "finish-review":
                print(f"review checkpoint {finish_review(root, ledger, args, current, record)['id']} sealed")
            elif phase == "cancel-review":
                proof = evidence_snapshot(root, args.evidence, "review cancellation")
                ledger.add("cancel-review", ref_id=args.id, evidence=proof)
            elif phase == "check-ledger":
                check_retry_state(root, ledger)
                print("check-ledger passed")
            else:
                check_review(root, ledger, record, current, items, args.partial)
                if phase == "deliver":
                    check_artifacts(root, record, current, args.partial)
                print(f"{phase} passed ({'partial' if args.partial else 'formal'})")
        if waiting:
            parser.exit(3, "waiting for user approval: " + ", ".join(waiting) + "\n")
    except (KeyError, TypeError, AttributeError, ValueError, OSError) as error:
        parser.exit(1, f"{args.phase} refused: {error}\n")


if __name__ == "__main__":
    main()
