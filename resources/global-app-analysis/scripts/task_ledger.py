"""Serialize task checkpoints and replay the journal before release."""

from contextlib import contextmanager
import fcntl
import json
import os
import re
import time


LIMITS = {"technical": 2, "evidence": 3, "artifact": 3}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def limit(key):
    match = re.fullmatch(r"(technical|evidence|artifact):[\w.-]+", key)
    require(match and (match[1] != "evidence" or key == "evidence:task"),
            f"invalid budget key: {key}")
    return LIMITS[match[1]]


class Ledger:
    def __init__(self, events):
        self.events = events
        self.used = {}
        self.waiting = set()
        self.authorizations = {}
        self.pending = {}
        self.attempts = {}
        self.active = None
        self.rounds = []
        self.review_files = set()
        self.review_digests = set()
        self.last_time = 0
        for number, event in enumerate(events, 1):
            require(event["id"] == number and event["at_ns"] > self.last_time, "invalid checkpoint order")
            self.apply(event)
            self.last_time = event["at_ns"]

    def apply(self, event):
        kind = event["event"]
        if kind == "reserve":
            keys = event["keys"]
            require(keys and len(set(keys)) == len(keys) and not self.exhausted(keys),
                    "retry exceeded its batch budget")
            require(not any(set(keys) & set(p["keys"]) for p in self.pending.values()),
                    "finish the existing retry for this budget key first")
            for key in keys:
                self.used[key] = self.used.get(key, 0) + 1
            self.pending[event["id"]] = event
        elif kind == "wait":
            require(event["keys"] and set(event["keys"]) == set(self.exhausted(event["keys"])),
                    "only an exhausted batch can wait for approval")
            self.waiting.update(event["keys"])
        elif kind == "resume":
            key = event["key"]
            proof = event["evidence"]
            require(key in self.waiting, "resume only a batch waiting for the user")
            require(not any(key in p["keys"] for p in self.pending.values()),
                    "finish the existing retry before resuming")
            used = self.authorizations.setdefault(key, set())
            require(proof["ref"] not in used and proof["sha256"] not in used,
                    "record a new user approval for this batch")
            used.update((proof["ref"], proof["sha256"]))
            self.waiting.remove(key)
            self.used[key] = 0
        elif kind == "finish":
            require(event["ref_id"] in self.pending, "retry ID is not open")
            require(event["outcome"] in {"passed", "failed", "unavailable"}, "invalid retry outcome")
            start = self.pending.pop(event["ref_id"])
            require(start["at_ns"] < event["evidence"]["modified_ns"] <= event["at_ns"],
                    "retry evidence must come from its reserved attempt")
            self.attempts[event["ref_id"]] = (start, event)
        elif kind == "begin-review":
            require(self.active is None, "finish or cancel the current review before starting another")
            self.active = event
        elif kind in {"finish-review", "cancel-review"}:
            require(self.active and event["ref_id"] == self.active["id"], "review ID is not open")
            if kind == "finish-review":
                evidence = [r["evidence"] for r in event["results"].values()]
                require(all(self.active["at_ns"] < e["modified_ns"] <= event["at_ns"] for e in evidence),
                        "review evidence must come from the open round")
                require(all(e["path"] not in self.review_files and e["sha256"] not in self.review_digests
                            for e in evidence), "each round needs its own newly recorded evidence")
                self.review_files.update(e["path"] for e in evidence)
                self.review_digests.update(e["sha256"] for e in evidence)
                self.rounds.append((self.active, event))
            self.active = None
        else:
            raise ValueError(f"unknown checkpoint event: {kind}")

    def exhausted(self, keys):
        return [key for key in keys if self.used.get(key, 0) >= limit(key)]

    def add(self, kind, **data):
        event = dict(data, event=kind, id=len(self.events) + 1, at_ns=max(time.time_ns(), self.last_time + 1))
        self.apply(event)
        self.events.append(event)
        self.last_time = event["at_ns"]
        return event


@contextmanager
def open_ledger(root, *, initialize=False, write=False):
    path = root / "task-checks.jsonl"
    # The lock covers reading, checking and appending, including concurrent retry reservations.
    with path.open("a+" if initialize else ("r+" if write else "r"), encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX if write or initialize else fcntl.LOCK_SH)
        stream.seek(0)
        ledger = Ledger([json.loads(line) for line in stream])
        count = len(ledger.events)
        yield ledger
        if len(ledger.events) > count:
            stream.seek(0, os.SEEK_END)
            for event in ledger.events[count:]:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
