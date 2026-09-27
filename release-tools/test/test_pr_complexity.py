#!/usr/bin/python3
"""Unit tests for pr-complexity.py.

The script filename contains a hyphen, so tests load it with importlib.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring,duplicate-code

import importlib.util
import os
import sys
import unittest
from contextlib import contextmanager
from io import StringIO


def load_module():
    """Load the hyphenated pr-complexity.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-complexity.py",
    )
    spec = importlib.util.spec_from_file_location("pr_complexity", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dc = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"


def git_diff(path, body_lines):
    """Build a one-file git unified diff whose hunk is body_lines."""
    lines = [
        f"diff --git a/{path} b/{path}",
        "index 1111111..2222222 100644",
        f"--- a/{path}",
        f"+++ b/{path}",
        "@@ -1,1 +1,1 @@",
    ]
    lines.extend(body_lines)
    return "\n".join(lines) + "\n"


def _files_in_one_directory(count):
    """Comment-only edits, so churn stays 0 and only the file span scores."""
    parts = [git_diff(f"area/pkg/f{index}.go", ["+// note"]) for index in range(count)]
    return "".join(parts)


def _sized(files, directories):
    """A score with no churn, so dispersion alone sets the band."""
    return dc.ChangeSize(0, 0, 0, 0, files, directories, 0, False, dc.DEFAULT_WEIGHTS)


def _churn(added=0, removed=0):
    """Churn for one source file with this many added and removed lines."""
    lines = ["+n()" for _ in range(added)]
    lines.extend("-n()" for _ in range(removed))
    return dc.classify_diff(git_diff("p.go", lines)).churn


def run_main(argv):
    out = StringIO()
    err = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = out
        sys.stderr = err
        rc = dc.main(argv)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return rc, out.getvalue(), err.getvalue()


@contextmanager
def patched_pull_request(diff_text, cognitive):
    """Stub gh and gocognit so a pull request link can be scored offline."""
    original_diff = dc.pull_request_diff
    original_measure = dc.measure_pull_request
    dc.pull_request_diff = lambda pr: diff_text
    dc.measure_pull_request = lambda pr: cognitive
    try:
        yield
    finally:
        dc.pull_request_diff = original_diff
        dc.measure_pull_request = original_measure


class TestScanners(unittest.TestCase):
    def test_go_line_comment_and_string(self):
        scan = dc.CLikeScanner(raw_strings=True)
        self.assertFalse(scan.feed("// only a comment"))
        self.assertFalse(scan.feed("   "))
        self.assertTrue(scan.feed('fmt.Println("https://example.com")'))

    def test_block_comment_carries_across_lines(self):
        scan = dc.CLikeScanner()
        self.assertFalse(scan.feed("/* start"))
        self.assertFalse(scan.feed(" still comment"))
        self.assertTrue(scan.feed(" end */ x := 1"))

    def test_python_hash_comment_inside_string_counts(self):
        scan = dc.HashScanner(triple=True)
        self.assertFalse(scan.feed("# note"))
        self.assertTrue(scan.feed('print("keep # this")'))
        self.assertTrue(scan.feed('"""doc'))
        self.assertTrue(scan.feed("still a string"))
        self.assertTrue(scan.feed('"""'))


class TestClassify(unittest.TestCase):
    def test_blank_and_comment_lines_do_not_count(self):
        diff = git_diff(
            "overlord/snapstate/snapstate.go",
            [
                " func before() {",
                "-// old note",
                "+",
                "+// new note",
                " }",
            ],
        )
        result = dc.classify_diff(diff)
        self.assertEqual(result.added, 0)
        self.assertEqual(result.removed, 0)
        self.assertEqual(result.changed, 0)
        self.assertEqual(result.non_source, 3)
        self.assertEqual(result.changed + result.non_source, 3)
        self.assertEqual(result.band, "trivial")

    def test_replaced_line_counts_twice(self):
        diff = git_diff(
            "cmd/snap/main.go",
            [
                "-old()",
                "+new()",
            ],
        )
        result = dc.classify_diff(diff)
        self.assertEqual((result.added, result.removed, result.changed), (1, 1, 2))

    def test_context_starts_a_block_comment(self):
        diff = git_diff(
            "widget/widget.go",
            [
                " /* start",
                "- still the comment",
                "+ still the comment too",
                "  end */",
            ],
        )
        result = dc.classify_diff(diff)
        self.assertEqual(result.changed, 0)
        self.assertEqual(result.non_source, 2)
        self.assertEqual(result.changed + result.non_source, 2)

    def test_non_source_does_not_change_the_band(self):
        diff = git_diff(
            "docs/notes.md",
            [
                "-old words here",
                "+new words here",
            ],
        )
        result = dc.classify_diff(diff)
        self.assertEqual(result.changed, 0)
        self.assertEqual(result.non_source, 2)
        self.assertEqual(result.changed + result.non_source, 2)
        self.assertEqual(result.band, "trivial")

    def test_source_plus_non_source_is_the_pull_request(self):
        diff = git_diff(
            "overlord/snapstate/snapstate.go",
            [
                " func before() {",
                "-old()",
                "-// old note",
                "+",
                "+new()",
                "+// new note",
                " }",
            ],
        )
        diff += git_diff("docs/notes.md", ["-old words", "+", "+new words"])
        diff += git_diff("api/types.pb.go", ["+generated()"])
        result = dc.classify_diff(diff)
        self.assertEqual((result.added, result.removed), (1, 1))
        self.assertEqual(result.non_source, 7)
        self.assertEqual(result.changed + result.non_source, 9)
        self.assertEqual(result.ignored, 1)
        self.assertEqual(result.churn, 1 + dc.DELETION_WEIGHT)

    def test_trivial_boundary(self):
        trivial = git_diff("p.go", ["+" + f"n{i}()" for i in range(dc.TRIVIAL_MAX)])
        required = git_diff(
            "p.go", ["+" + f"n{i}()" for i in range(dc.TRIVIAL_MAX + 1)]
        )
        self.assertEqual(dc.classify_diff(trivial).band, "trivial")
        self.assertEqual(dc.classify_diff(required).band, "small")

    def test_large_band(self):
        diff = git_diff("p.go", ["+" + f"n{i}()" for i in range(dc.MEDIUM_MAX + 1)])
        self.assertEqual(dc.classify_diff(diff).band, "large")

    def test_deleted_file_uses_the_old_path(self):
        lines = [
            "diff --git a/old.go b/old.go",
            "deleted file mode 100644",
            "index 1111111..0000000",
            "--- a/old.go",
            "+++ /dev/null",
            "@@ -1 +0,0 @@",
            "-keep()",
        ]
        diff = "\n".join(lines) + "\n"
        result = dc.classify_diff(diff)
        self.assertEqual(result.removed, 1)
        self.assertEqual(result.added, 0)

    def test_deletions_cost_half_an_added_line(self):
        at_limit = git_diff("p.go", ["-keep()" for _ in range(dc.TRIVIAL_MAX * 2)])
        above = git_diff("p.go", ["-keep()" for _ in range(dc.TRIVIAL_MAX * 2 + 1)])
        self.assertEqual(dc.classify_diff(at_limit).churn, float(dc.TRIVIAL_MAX))
        self.assertEqual(dc.classify_diff(at_limit).band, "trivial")
        self.assertEqual(dc.classify_diff(above).band, "small")

    def test_source_lines_climb_after_the_knees(self):
        added_knee = dc.ADDED_KNEE
        removed_knee = dc.REMOVED_KNEE
        self.assertEqual(_churn(added=added_knee), added_knee)
        self.assertEqual(
            _churn(removed=removed_knee), removed_knee * dc.DELETION_WEIGHT
        )
        added_past = _churn(added=added_knee + 100)
        self.assertGreater(added_past, added_knee + 100)
        self.assertLess(added_past, added_knee + 130)
        removed_past = _churn(removed=removed_knee + 200)
        removed_linear = (removed_knee + 200) * dc.DELETION_WEIGHT
        self.assertGreater(removed_past, removed_linear)
        self.assertLess(removed_past, removed_linear + 40)
        further = _churn(added=added_knee + 200)
        self.assertGreater(further - added_past, added_past - added_knee)

    def test_source_lines_leave_medium_past_the_knees(self):
        at_added = git_diff("p.go", ["+n()" for _ in range(dc.ADDED_KNEE)])
        past_added = git_diff("p.go", ["+n()" for _ in range(dc.ADDED_KNEE + 200)])
        at_removed = git_diff("p.go", ["-n()" for _ in range(dc.REMOVED_KNEE)])
        past_removed = git_diff("p.go", ["-n()" for _ in range(dc.REMOVED_KNEE + 400)])
        self.assertEqual(dc.classify_diff(at_added).band, "medium")
        self.assertEqual(dc.classify_diff(past_added).band, "large")
        self.assertEqual(dc.classify_diff(at_removed).band, "medium")
        self.assertEqual(dc.classify_diff(past_removed).band, "large")

    def test_cognitive_complexity_raises_effort(self):
        diff = git_diff("p.go", ["+n()" for _ in range(dc.TRIVIAL_MAX)])
        plain = dc.classify_diff(diff)
        self.assertFalse(plain.measured)
        self.assertEqual(plain.band, "trivial")
        scored = dc.classify_diff(diff, gocognit=11)
        self.assertTrue(scored.measured)
        self.assertEqual(scored.gocognit, 11)
        self.assertEqual(scored.cognitive_complexity, 11 * dc.COGNITIVE_WEIGHT)
        self.assertGreater(scored.effort, plain.effort)

    def test_cross_package_change_adds_dispersion(self):
        diff = git_diff("overlord/snapstate/snapstate.go", ["+ready()"])
        diff += git_diff("overlord/ifacestate/ifacestate.go", ["+ready()"])
        result = dc.classify_diff(diff)
        self.assertEqual(result.files, 2)
        self.assertEqual(result.directories, 2)
        file_span = _sized(files=2, directories=1).dispersion
        dir_span = _sized(files=1, directories=2).dispersion
        self.assertAlmostEqual(file_span, 1.4, delta=0.05)
        self.assertAlmostEqual(dir_span, 2.55, delta=0.05)
        self.assertAlmostEqual(result.dispersion, file_span + dir_span)
        self.assertEqual(result.band, "trivial")

    def test_twenty_files_reach_the_medium_ceiling(self):
        at_max = dc.classify_diff(_files_in_one_directory(dc.FILE_AT_MAX))
        self.assertEqual(at_max.files, dc.FILE_AT_MAX)
        self.assertEqual(at_max.directories, 1)
        self.assertEqual(at_max.added, 0)
        self.assertEqual(at_max.dispersion, dc.MEDIUM_MAX)
        self.assertEqual(at_max.band, "medium")
        over = dc.classify_diff(_files_in_one_directory(dc.FILE_AT_MAX + 1))
        self.assertAlmostEqual(over.dispersion, 987, delta=5)
        self.assertEqual(over.band, "large")

    def test_eight_directories_reach_the_medium_ceiling(self):
        at_max = _sized(files=1, directories=dc.DIR_AT_MAX)
        self.assertEqual(at_max.dispersion, dc.MEDIUM_MAX)
        self.assertEqual(at_max.band, "medium")
        over = _sized(files=1, directories=dc.DIR_AT_MAX + 1)
        self.assertGreater(over.dispersion, dc.MEDIUM_MAX)
        self.assertEqual(over.band, "large")

    def test_generated_files_are_ignored(self):
        lines = ["+if ready() {" for _ in range(50)]
        diff = git_diff("sandbox/cgroup/cgroup.pb.go", lines)
        diff += git_diff("go.sum", ["+example.com/mod v1.2.3"])
        result = dc.classify_diff(diff)
        self.assertEqual(result.added, 0)
        self.assertEqual(result.files, 0)
        self.assertEqual(result.ignored, 2)
        self.assertEqual(result.non_source, 51)
        self.assertEqual(result.changed + result.non_source, 51)
        self.assertEqual(result.effort, 0)
        self.assertEqual(result.band, "trivial")

    def test_weights_are_configurable(self):
        diff = git_diff("p.go", ["-keep()" for _ in range(80)])
        full = dc.Weights(
            deletion=1,
            added_knee=dc.ADDED_KNEE,
            removed_knee=dc.REMOVED_KNEE,
            files_at_max=20,
            directories_at_max=8,
            cognitive=3,
        )
        result = dc.classify_diff(diff, full)
        self.assertEqual(result.churn, 80)
        self.assertEqual(result.band, "small")


class TestCognitive(unittest.TestCase):
    def test_sums_gocognit_issues(self):
        report = """
        {"Issues":[
          {"FromLinter":"gocognit","Text":"cognitive complexity 11 of func `small` is high (> 10)"},
          {"FromLinter":"gocognit","Text":"cognitive complexity 24 of func `nested` is high (> 10)"},
          {"FromLinter":"unused","Text":"cognitive complexity 99 of func `nope` is high (> 10)"}
        ]}
        """
        self.assertEqual(dc.cognitive_total(report), 35)

    def test_empty_report_is_zero(self):
        self.assertEqual(dc.cognitive_total(""), 0)
        self.assertEqual(dc.cognitive_total('{"Issues":null}'), 0)

    def test_status_line_after_json_is_ignored(self):
        report = (
            '{"Issues":[{"FromLinter":"gocognit","Text":'
            '"cognitive complexity 12 of func `f` is high (> 10)"}]}'
            "\n0 issues.\n"
        )
        self.assertEqual(dc.cognitive_total(report), 12)

    def test_linter_summary_after_json_is_ignored(self):
        report = (
            '{"Issues":[{"FromLinter":"gocognit","Text":'
            '"cognitive complexity 8 of func `f` is high (> 0)"}]}\n'
            "3 issues:\n* gocognit: 3\n"
        )
        self.assertEqual(dc.cognitive_total(report), 8)

    def test_script_supplies_the_gocognit_config(self):
        seen = {}

        def fake_run(command, **kwargs):
            self.assertEqual(kwargs["cwd"], "/tmp")
            config = command[command.index("--config") + 1]
            with open(config, encoding="utf-8") as handle:
                seen["text"] = handle.read()
            seen["path"] = config
            return dc.subprocess.CompletedProcess(
                command, 0, stdout='{"Issues":[]}\n0 issues.\n', stderr=""
            )

        original = dc.subprocess.run
        dc.subprocess.run = fake_run
        try:
            total = dc.measure_cognitive("abc123", "/tmp")
        finally:
            dc.subprocess.run = original
        self.assertEqual(total, 0)
        self.assertIn("min-complexity: 0", seen["text"])
        self.assertIn("- gocognit", seen["text"])
        self.assertFalse(os.path.exists(seen["path"]))

    def test_pull_request_uses_the_gocognit_total(self):
        diff = git_diff("p.go", ["+n()"])
        with patched_pull_request(diff, 11):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Effort: "))
        self.assertLess(out.index("Band:"), out.index("Calculation:"))
        self.assertLess(out.index("Calculation:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertIn("Gocognit: 11", out)
        self.assertIn("Cognitive complexity: 33.0", out)
        self.assertIn("Band: small", out)


class TestPullRequestLink(unittest.TestCase):
    def test_parse_pull_request_link(self):
        pr = dc.parse_pull_request("https://github.com/canonical/snapd/pull/17718")
        self.assertEqual(
            (pr.owner, pr.repo, pr.number), ("canonical", "snapd", "17718")
        )
        self.assertEqual(pr.url, "https://github.com/canonical/snapd/pull/17718")

    def test_parse_files_suffix(self):
        pr = dc.parse_pull_request(
            "https://github.com/canonical/snapd/pull/17718/files"
        )
        self.assertEqual(pr.number, "17718")

    def test_reject_a_non_link(self):
        with self.assertRaises(dc.UsageError):
            dc.parse_pull_request("17718")


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("exits 0", out)
        self.assertIn("https://github.com/canonical/snapd/pull/17718", out)
        self.assertIn("--deletion-weight float", out)
        self.assertIn("--added-knee count", out)
        self.assertIn("--removed-knee count", out)
        self.assertIn("ADDED_KNEE", out)
        self.assertIn("REMOVED_KNEE", out)
        self.assertIn("--files-at-max count", out)
        self.assertIn("--directories-at-max count", out)
        self.assertIn("--cognitive-weight float", out)
        self.assertIn("FILE_AT_MAX", out)
        self.assertIn("DIR_AT_MAX", out)
        self.assertIn("DELETION_WEIGHT", out)
        self.assertIn("min-complexity stays 0", out)
        self.assertIn("constants at the top", out)

    def test_unknown_flag(self):
        rc, _out, err = run_main(["--nope"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown flag: --nope", err)

    def test_weight_flag_changes_the_score(self):
        diff = git_diff("p.go", ["-keep()" for _ in range(80)])
        with patched_pull_request(diff, 0):
            rc, out, err = run_main([PR, "--deletion-weight", "1"])
        self.assertEqual((rc, err), (0, ""))
        self.assertIn(
            "Weights: deletion 1, added knee 500, removed knee 800, "
            "files 20, directories 8, cognitive 3",
            out,
        )
        self.assertIn("Churn: 80.0", out)
        self.assertIn("Band: small", out)

    def test_invalid_pull_request_link(self):
        rc, _out, err = run_main(["not-a-pull-request"])
        self.assertEqual(rc, 2)
        self.assertIn("invalid pull request link: not-a-pull-request", err)

    def test_invalid_weight(self):
        rc, _out, err = run_main(["--files-at-max", "1"])
        self.assertEqual(rc, 2)
        self.assertIn("invalid files at max: 1", err)

    def test_pull_request_link_scores_the_diff(self):
        diff = git_diff("a.go", ["-old()", "+new()"])
        with patched_pull_request(diff, 0):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Effort: "))
        self.assertEqual(out.count("\nEffort:"), 0)
        self.assertIn("Changed source lines: 2", out)
        self.assertIn("Band: trivial", out)
        self.assertIn("Gocognit: 0", out)
        self.assertIn("Cognitive complexity: 0.0", out)

    def test_missing_link_prints_help(self):
        rc, out, err = run_main([])
        self.assertEqual(rc, 2)
        self.assertEqual(err, "")
        self.assertIn("Usage:", out)


if __name__ == "__main__":
    unittest.main()
