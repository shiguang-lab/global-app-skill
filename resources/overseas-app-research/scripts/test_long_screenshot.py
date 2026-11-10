"""Pixel preservation, fixed chrome, alignment failures and provenance verification."""
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from PIL import Image

import long_screenshot as longshot


class LongScreenshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.width = 48
        self.top, self.bottom = 12, 112
        rng = random.Random(1234)
        self.page = Image.frombytes("RGB", (self.width, 260), rng.randbytes(self.width * 260 * 3))
        self.config = {"top": self.top, "bottom": self.bottom, "match_left": 0,
                       "match_right": self.width, "min_overlap": 30}

    def frame(self, offset, name):
        frame = Image.new("RGB", (self.width, 120), "red")
        frame.paste(self.page.crop((0, offset, self.width, offset + 100)), (0, self.top))
        frame.paste(Image.new("RGB", (self.width, 8), "blue"), (0, self.bottom))
        path = self.root / name
        frame.save(path)
        return path

    def test_three_frames_reproduce_full_page_with_fixed_bars_once(self):
        frames = [self.frame(offset, f"frame-{i}.png") for i, offset in enumerate([0, 60, 110])]
        before = [p.read_bytes() for p in frames]
        manifest = longshot.stitch(frames, self.root / "joined", self.config)
        with Image.open(manifest.parent / "long.png") as result:
            self.assertEqual(result.size, (self.width, 230))
            self.assertEqual(result.crop((0, 12, self.width, 222)).tobytes(),
                             self.page.crop((0, 0, self.width, 210)).tobytes())
            self.assertEqual(result.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(result.getpixel((0, 229)), (0, 0, 255))
        record = json.loads(manifest.read_text())
        self.assertEqual([t["shift"] for t in record["transitions"]], [60, 50])
        self.assertEqual(longshot.verify(manifest)["status"], "passed")
        self.assertEqual([p.read_bytes() for p in frames], before)

    def test_scrollbar_exclusion_does_not_remove_output_columns(self):
        first, second = self.frame(0, "first.png"), self.frame(60, "second.png")
        with Image.open(second) as source:
            image = source.copy()
        image.paste(Image.new("RGB", (2, 100), "green"), (self.width - 2, self.top))
        image.save(second)
        config = {**self.config, "match_right": self.width - 2}
        manifest = longshot.stitch([first, second], self.root / "joined", config)
        with Image.open(manifest.parent / "long.png") as result:
            self.assertEqual(result.width, self.width)
            self.assertEqual(result.getpixel((self.width - 1, 160)), (0, 128, 0))
        self.assertTrue(longshot.verify(manifest)["source_pixels_unchanged"])

    def test_gap_fails_with_reason_and_preserves_all_frames(self):
        frames = [self.frame(0, "first.png"), self.frame(130, "second.png")]
        before = [p.read_bytes() for p in frames]
        with self.assertRaisesRegex(longshot.StitchError, "NO_EXACT_OVERLAP"):
            longshot.stitch(frames, self.root / "failed", self.config)
        record = json.loads((self.root / "failed/stitch.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertIn("NO_EXACT_OVERLAP", record["error"])
        self.assertEqual([p.read_bytes() for p in frames], before)
        self.assertFalse((self.root / "failed/long.png").exists())

    def test_duplicate_bottom_probe_is_not_silently_counted_as_scroll(self):
        image = self.frame(0, "first.png")
        with self.assertRaisesRegex(longshot.StitchError, "NO_SCROLL_MOVEMENT"):
            longshot.stitch([image, image], self.root / "failed", self.config)

    def test_repeated_background_with_multiple_shifts_is_rejected(self):
        first = Image.new("RGB", (48, 120), "white")
        second = first.copy()
        first.paste(Image.new("RGB", (48, 2), "black"), (0, 12))
        with self.assertRaisesRegex(longshot.StitchError, "AMBIGUOUS_OVERLAP"):
            longshot.plan([first, second], self.config)

    def test_changed_frame_size_is_rejected(self):
        with self.assertRaisesRegex(longshot.StitchError, "SIZE_CHANGED"):
            longshot.plan([Image.new("RGB", (48, 120)), Image.new("RGB", (48, 121))], self.config)

    def test_minimum_overlap_cannot_be_lowered_below_thirty_percent(self):
        frames = longshot.load_images([self.frame(0, "first.png"), self.frame(60, "second.png")])
        for minimum in (1, 29):
            with self.subTest(minimum=minimum), self.assertRaisesRegex(
                    longshot.StitchError, "INSUFFICIENT_OVERLAP_REQUIREMENT"):
                longshot.plan(frames, {**self.config, "min_overlap": minimum})

    def test_less_than_thirty_percent_actual_overlap_is_rejected(self):
        frames = [self.frame(0, "first.png"), self.frame(80, "second.png")]
        with self.assertRaisesRegex(longshot.StitchError, "NO_EXACT_OVERLAP"):
            longshot.stitch(frames, self.root / "failed", self.config)

    def test_modified_source_and_output_are_rejected(self):
        for changed in ("source", "output"):
            with self.subTest(changed=changed):
                frames = [self.frame(0, f"{changed}-first.png"), self.frame(60, f"{changed}-second.png")]
                manifest = longshot.stitch(frames, self.root / changed, self.config)
                target = frames[0] if changed == "source" else manifest.parent / "long.png"
                with target.open("ab") as stream:
                    stream.write(b"changed")
                with self.assertRaisesRegex(longshot.StitchError, "HASH_CHANGED"):
                    longshot.verify(manifest)

    def test_pixel_tamper_is_rejected_even_if_output_hash_is_updated(self):
        frames = [self.frame(0, "first.png"), self.frame(60, "second.png")]
        manifest = longshot.stitch(frames, self.root / "joined", self.config)
        output = manifest.parent / "long.png"
        with Image.open(output) as source:
            image = source.copy()
        image.putpixel((1, 50), (0, 0, 0))
        image.save(output)
        record = json.loads(manifest.read_text())
        record["output"]["sha256"] = longshot.sha256(output)
        longshot.write_json(manifest, record)
        with self.assertRaisesRegex(longshot.StitchError, "PIXELS_CHANGED"):
            longshot.verify(manifest)

    def test_cli_success_reverification_and_failure_exit_codes(self):
        frames = [self.frame(0, "first.png"), self.frame(60, "second.png")]
        args = [sys.executable, longshot.__file__, "stitch", "--frames", *map(str, frames),
                "--top", "12", "--bottom", "112", "--match-left", "0", "--match-right", "48",
                "--min-overlap", "30", "--out", str(self.root / "cli")]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        check = subprocess.run([sys.executable, longshot.__file__, "verify", "--manifest",
                                str(self.root / "cli/stitch.json")], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        # Reusing an output directory must not overwrite prior results.
        repeat = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(repeat.returncode, 0)
        self.assertEqual(json.loads(repeat.stderr)["status"], "failed")

    def test_failed_reverification_replaces_latest_report_and_retains_history(self):
        frames = [self.frame(0, "first.png"), self.frame(60, "second.png")]
        manifest = longshot.stitch(frames, self.root / "joined", self.config)
        initial = json.loads((manifest.parent / "verification.json").read_text())
        output = manifest.parent / "long.png"
        with output.open("ab") as stream:
            stream.write(b"changed after successful validation")
        check = subprocess.run([sys.executable, longshot.__file__, "verify", "--manifest", str(manifest)],
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 1)
        latest = json.loads((manifest.parent / "verification.json").read_text())
        self.assertEqual(latest["status"], "failed")
        self.assertIn("OUTPUT_HASH_CHANGED", latest["error"])
        self.assertEqual(latest["observed_output_sha256"], longshot.sha256(output))
        self.assertEqual(latest["manifest_sha256"], longshot.sha256(manifest))
        self.assertGreaterEqual(latest["checked_at"], initial["checked_at"])
        history = [json.loads(p.read_text()) for p in (manifest.parent / "verification-history").glob("*.json")]
        self.assertCountEqual([item["status"] for item in history], ["passed", "failed"])
        self.assertIn(initial, history)

    def test_source_change_and_unreadable_manifest_do_not_leave_success_record(self):
        for failure in ("source", "manifest"):
            with self.subTest(failure=failure):
                frames = [self.frame(0, f"{failure}-first.png"), self.frame(60, f"{failure}-second.png")]
                manifest = longshot.stitch(frames, self.root / failure, self.config)
                if failure == "source":
                    frames[0].write_bytes(b"different source")
                else:
                    manifest.write_text("not JSON")
                with self.assertRaises(ValueError):
                    longshot.verify(manifest)
                report = json.loads((manifest.parent / "verification.json").read_text())
                self.assertEqual(report["status"], "failed")
                self.assertEqual(len(list((manifest.parent / "verification-history").glob("*.json"))), 2)

    def test_successful_reverification_writes_current_input_fingerprints(self):
        frames = [self.frame(0, "first.png"), self.frame(60, "second.png")]
        manifest = longshot.stitch(frames, self.root / "joined", self.config)
        result = longshot.verify(manifest)
        saved = json.loads((manifest.parent / "verification.json").read_text())
        self.assertEqual(saved, result)
        self.assertEqual([item["sha256"] for item in saved["observed_sources"]], [longshot.sha256(p) for p in frames])


if __name__ == "__main__":
    unittest.main()
