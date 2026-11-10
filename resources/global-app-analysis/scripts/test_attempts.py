"""The search fallback must remain bounded and never recycle attempted sources."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import attempts


class AttemptLedgerTests(unittest.TestCase):
    def setUp(self):
        self.data = {"package": "com.example.app", "version_policy": "latest-available", "attempts": [], "search_rounds": []}

    def test_api_cdn_and_webpage_are_the_same_fallback_source(self):
        item = attempts.begin(self.data, channel="apkpure", method="client-api", url="https://api.pureapk.com/m/v3/cms/app_version")
        attempts.finish(self.data, item["id"], "failed", "no candidate")
        for url in ["https://apkpure.com/app/download", "https://d.apkpure.net/b/APK/app", "https://download.pureapk.com/b/XAPK/app"]:
            self.assertFalse(attempts.candidate(self.data, url)["eligible"])

    def test_changed_query_path_language_or_mobile_site_is_not_new(self):
        attempts.begin(self.data, channel="mirror", method="web", url="https://www.example.test/old?token=one")
        for url in ["http://example.test/new?token=two", "https://m.example.test/app", "https://es.example.test/app"]:
            self.assertFalse(attempts.candidate(self.data, url)["eligible"])

    def test_untried_source_is_eligible(self):
        attempts.begin(self.data, channel="mirror", method="web", url="https://one.test/app")
        self.assertTrue(attempts.candidate(self.data, "https://two.test/app")["eligible"])

    def test_two_letter_registered_domains_are_not_treated_as_locales(self):
        attempts.begin(self.data, channel="mirror", method="web", url="https://id.co.uk/app")
        self.assertTrue(attempts.candidate(self.data, "https://us.co.uk/app")["eligible"])
        self.assertFalse(attempts.candidate(self.data, "https://en.id.co.uk/app")["eligible"])

    def test_redirect_records_both_origins_for_future_exclusion(self):
        item = attempts.begin(self.data, channel="discovered", method="web", url="https://one.test/app")
        attempts.finish(self.data, item["id"], "redirected", "only redirects", ["https://play.google.com/store/apps/details?id=com.example.app"])
        self.assertFalse(attempts.candidate(self.data, "https://play.googleapis.com/fdfe/delivery")["eligible"])
        self.assertFalse(attempts.candidate(self.data, "https://one.test/other")["eligible"])

    def test_known_play_methods_can_differ_but_the_same_method_cannot_repeat(self):
        attempts.begin(self.data, channel="google-play", method="emulator-store")
        attempts.begin(self.data, channel="google-play", method="anonymous-delivery")
        with self.assertRaisesRegex(ValueError, "already attempted"):
            attempts.begin(self.data, channel="google-play", method="anonymous-delivery")

    def test_fallback_cannot_reuse_tried_source_via_a_new_method(self):
        attempts.begin(self.data, channel="aptoide", method="app-get-aab", url="https://ws75.aptoide.com/api/7/app/get")
        attempts.search_round(self.data, ["com.example.app apk mirror"])
        with self.assertRaisesRegex(ValueError, "already attempted"):
            attempts.begin(self.data, channel="new-result", method="browser", url="https://example.en.aptoide.com/app", search_round=1)

    def test_waiting_sources_are_also_excluded(self):
        item = attempts.begin(self.data, channel="apkcube", method="browser", url="https://apkcube.com/app/download")
        attempts.finish(self.data, item["id"], "waiting_user", "captcha required")
        self.assertFalse(attempts.candidate(self.data, "https://apkcube.com/other")["eligible"])
        attempts.finish(self.data, item["id"], "started", "user completed captcha; continuing original attempt")
        self.assertEqual(len(self.data["attempts"]), 1)

    def test_three_rounds_without_new_candidates_still_exhaust_budget(self):
        for n in range(1, 4):
            self.assertEqual(attempts.search_round(self.data, [f"com.example.app mirror angle {n}"])["round"], n)
        with self.assertRaisesRegex(ValueError, "Three search rounds exhausted"):
            attempts.search_round(self.data, ["another query"])
        self.assertEqual(len(self.data["search_rounds"]), 3)
        self.assertEqual(attempts.summary(self.data)["search_rounds_remaining"], 0)

    def test_omitting_round_does_not_bypass_search_limit(self):
        for n in range(1, 4):
            attempts.search_round(self.data, [f"com.example.app mirror angle {n}"])
        with self.assertRaisesRegex(ValueError, "current reserved search round"):
            attempts.begin(self.data, channel="fresh", method="web", url="https://fresh.example/app")

    def test_prior_round_cannot_be_reopened_for_new_candidates(self):
        attempts.search_round(self.data, ["com.example.app first angle"])
        attempts.search_round(self.data, ["com.example.app second angle"])
        with self.assertRaisesRegex(ValueError, "earlier rounds cannot be reopened"):
            attempts.begin(self.data, channel="fresh", method="web", url="https://fresh.example/app", search_round=1)

    def test_waiting_known_attempt_can_resume_after_search_has_started(self):
        item = attempts.begin(self.data, channel="google-play", method="emulator-store")
        attempts.finish(self.data, item["id"], "waiting_user", "login required")
        attempts.search_round(self.data, ["com.example.app mirror"])
        resumed = attempts.finish(self.data, item["id"], "started", "user finished login")
        self.assertEqual(resumed["status"], "started")
        self.assertEqual(len(self.data["attempts"]), 1)

    def test_repeated_queries_do_not_masquerade_as_new_exploration(self):
        attempts.search_round(self.data, ["  com.example.app  APK mirror "])
        with self.assertRaisesRegex(ValueError, "already used"):
            attempts.search_round(self.data, ["com.example.app apk MIRROR"])
        self.assertEqual(len(self.data["search_rounds"]), 1)

    def test_failed_verification_does_not_reset_rounds_or_allow_retry(self):
        attempts.search_round(self.data, ["com.example.app APK mirror"])
        item = attempts.begin(self.data, channel="mirror", method="web", url="https://one.test/app", search_round=1)
        attempts.finish(self.data, item["id"], "downloaded", artifact="/fixture/sample.apk", digest="a" * 64)
        attempts.finish(self.data, item["id"], "verification_failed", "wrong signer")
        self.assertFalse(attempts.candidate(self.data, "https://one.test/new")["eligible"])
        self.assertEqual(len(self.data["search_rounds"]), 1)
        with self.assertRaisesRegex(ValueError, "cannot be restarted"):
            attempts.finish(self.data, item["id"], "started")

    def test_duplicate_artifact_is_flagged_across_different_domains(self):
        a = attempts.begin(self.data, channel="one", method="web", url="https://one.test/app")
        attempts.finish(self.data, a["id"], "downloaded", digest="a" * 64)
        attempts.finish(self.data, a["id"], "verification_failed", "wrong version")
        b = attempts.begin(self.data, channel="two", method="web", url="https://two.test/app")
        item = attempts.finish(self.data, b["id"], "downloaded", digest="a" * 64)
        self.assertEqual(item["same_artifact_attempt_ids"], [a["id"]])

    def test_search_round_must_be_reserved_before_using_it(self):
        with self.assertRaisesRegex(ValueError, "Reserve"):
            attempts.begin(self.data, channel="mirror", method="web", url="https://one.test/app", search_round=1)

    def profile_attempt(self):
        profile = {"abi": "arm64-v8a", "sdk_level": 35, "density": 480}
        parent = attempts.begin(self.data, channel="aptoide", method="app-get-aab", profile=profile)
        attempts.finish(self.data, parent["id"], "downloaded")
        attempts.finish(self.data, parent["id"], "verified")
        return parent, {**profile, "abi": "x86_64"}

    def test_linked_profile_change_preserves_completed_attempt_and_search_budget(self):
        parent, profile = self.profile_attempt()
        for n in range(3):
            attempts.search_round(self.data, [f"fixture angle {n}"])
        child = attempts.begin(self.data, channel="aptoide", method="app-get-aab", profile=profile,
                               parent_id=parent["id"], reason="Observed selected emulator ABI is x86_64")
        self.assertEqual(child["parent_attempt_id"], parent["id"])
        self.assertEqual(child["profile"], profile)
        self.assertEqual(parent["status"], "verified")
        self.assertEqual(attempts.summary(self.data)["search_rounds_remaining"], 0)
        self.assertFalse(attempts.candidate(self.data, "https://aptoide.com/app")["eligible"])

    def test_profile_change_cannot_be_faked_by_renaming_method_or_source(self):
        parent, profile = self.profile_attempt()
        for channel, method in [("apkpure", "app-get-aab"), ("aptoide", "new-method")]:
            with self.subTest(channel=channel, method=method), self.assertRaisesRegex(ValueError, "source and method"):
                attempts.begin(self.data, channel=channel, method=method, profile=profile,
                               parent_id=parent["id"], reason="different ABI")

    def test_profile_change_requires_real_difference_and_reason(self):
        parent, profile = self.profile_attempt()
        for change in ({"profile": parent["profile"], "reason": "changed"},
                       {"profile": None, "reason": "changed"}, {"profile": profile, "reason": "  "}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                attempts.begin(self.data, channel="aptoide", method="app-get-aab", parent_id=parent["id"], **change)
        with self.assertRaisesRegex(ValueError, "already attempted"):
            attempts.begin(self.data, channel="aptoide", method="app-get-aab", profile=profile)

    def test_same_changed_profile_cannot_be_retried_through_another_link(self):
        parent, profile = self.profile_attempt()
        child = attempts.begin(self.data, channel="aptoide", method="app-get-aab", profile=profile,
                               parent_id=parent["id"], reason="different ABI")
        attempts.finish(self.data, child["id"], "failed", "no package for profile")
        with self.assertRaisesRegex(ValueError, "already attempted"):
            attempts.begin(self.data, channel="aptoide", method="app-get-aab", profile=profile,
                           parent_id=parent["id"], reason="repeat")

    def test_profile_change_from_search_round_does_not_reopen_it(self):
        attempts.search_round(self.data, ["first angle"])
        parent = attempts.begin(self.data, channel="fixture", method="web", url="https://one.test/app", search_round=1,
                                profile={"abi": "arm64-v8a", "sdk_level": 35, "density": 480})
        attempts.finish(self.data, parent["id"], "failed", "wrong ABI")
        attempts.search_round(self.data, ["second angle"])
        child = attempts.begin(self.data, channel="fixture", method="web", url="https://one.test/app",
                               parent_id=parent["id"], profile={"abi": "x86_64", "sdk_level": 35, "density": 480},
                               reason="actual target ABI changed")
        self.assertEqual(child["search_round"], 1)
        self.assertEqual(len(self.data["search_rounds"]), 2)
        with self.assertRaisesRegex(ValueError, "already attempted"):
            attempts.begin(self.data, channel="fixture", method="web", url="https://one.test/app", search_round=2)

    def test_cli_profile_change_is_recorded_as_a_linked_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            parent, profile = self.profile_attempt()
            (path / "attempts.json").write_text(json.dumps(self.data))
            (path / "profile.json").write_text(json.dumps(profile))
            argv = ["attempts.py", "begin", "--ledger", str(path / "attempts.json"), "--channel", "aptoide",
                    "--method", "app-get-aab", "--profile", str(path / "profile.json"), "--parent-id", str(parent["id"]),
                    "--reason", "observed ABI changed"]
            with mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(attempts.main(), 0)
            saved = json.loads((path / "attempts.json").read_text())
            self.assertEqual(saved["attempts"][1]["parent_attempt_id"], 1)
            self.assertEqual(saved["search_rounds"], [])

    def test_cli_reinit_preserves_budget_and_refuses_different_target(self):
        def cli(argv):
            with mock.patch("sys.argv", ["attempts.py", *argv]), contextlib.redirect_stdout(io.StringIO()):
                return attempts.main()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attempts.json"
            args = ["--ledger", str(path)]
            init = ["init", *args, "--package", "com.example.app", "--version-policy", "latest-available"]
            self.assertEqual(cli(init), 0)
            self.assertEqual(cli(["search-round", *args, "--query", "com.example.app APK mirror"]), 0)
            self.assertEqual(cli(init), 0)
            self.assertEqual(len(json.loads(path.read_text())["search_rounds"]), 1)
            self.assertEqual(cli(["init", *args, "--package", "com.other.app", "--version-policy", "latest-available"]), 1)
            self.assertEqual(json.loads(path.read_text())["package"], "com.example.app")


if __name__ == "__main__":
    unittest.main()
