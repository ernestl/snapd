#!/usr/bin/python3
"""Unit tests for pr-review.py.

The script filename contains a hyphen, so tests load it with importlib.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring,duplicate-code

import importlib.util
import json
import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch


def load_module(filename, name):
    """Load a hyphenated script or review.py."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rv = load_module("pr-review.py", "pr_review")
contract = load_module("review.py", "snapd_release_review_for_tests")
PR = "https://github.com/canonical/snapd/pull/17718"
LABELS = "\n".join(
    (
        "Labels: override",
        "",
        "Details:",
        f"Pull request: {PR}",
        "Roadmap: no (overwritten by alice)",
        "Priority: high (overwritten by alice)",
    )
)


def run_main(argv):
    out = StringIO()
    err = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = out
        sys.stderr = err
        rc = rv.main(argv)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return rc, out.getvalue(), err.getvalue()


def sample_reviews():
    return (
        contract.AreaReview("priority", ("Priority: high",), ("high",), ()),
        contract.AreaReview("feature", ("Feature: yes",), (), ()),
        contract.AreaReview(
            "links",
            ("Links: no",),
            (),
            (contract.Finding("error", "report link is absent"),),
        ),
        contract.AreaReview(
            "summary",
            ("Change summary: required",),
            (),
            (contract.Finding("warning", "summary is missing"),),
        ),
    )


class TestComment(unittest.TestCase):
    def test_sections_copy_the_label_report(self):
        reviews = sample_reviews()
        comment = rv.render_comment("Ship the fix.", "yes", LABELS, reviews, "fail")
        self.assertTrue(comment.startswith(rv.MARKER + "\n"))
        self.assertIn("Review: fail\n", comment)
        self.assertIn("## Information\n", comment)
        self.assertIn("Release note: Ship the fix.", comment)
        self.assertIn("Omit: yes", comment)
        self.assertIn(LABELS, comment)
        self.assertIn("Feature file: yes", comment)
        self.assertIn("Links: no", comment)
        self.assertIn("Change summary: required", comment)
        self.assertNotIn("\nPriority: high\n", comment)
        self.assertLess(comment.index("## Warnings"), comment.index("## Errors"))
        self.assertIn("- summary: summary is missing", comment)
        self.assertIn("- links: report link is absent", comment)
        self.assertEqual(rv.verdict_of(reviews), "fail")

    def test_empty_findings_approve(self):
        reviews = (contract.AreaReview("links", ("Links: yes",), (), ()),)
        comment = rv.render_comment(
            "not set", "no", "Labels: applied\n", reviews, "approve"
        )
        self.assertEqual(rv.verdict_of(reviews), "approve")
        self.assertIn("## Warnings\n\nnone\n", comment)
        self.assertIn("## Errors\n\nnone\n", comment)

    def test_warning_does_not_fail(self):
        reviews = (
            contract.AreaReview(
                "summary",
                ("Change summary: required",),
                (),
                (contract.Finding("warning", "summary is missing"),),
            ),
        )
        self.assertEqual(rv.verdict_of(reviews), "comment")
        comment = rv.render_comment(
            "not set", "no", "Labels: applied\n", reviews, "comment"
        )
        self.assertIn("## Errors\n\nnone\n", comment)

    def test_release_note_and_omit(self):
        body = "\n".join(
            (
                "**release note:** `<add your note here>`",
                "- [ ] Omit",
            )
        )
        self.assertEqual(rv.release_fields(body), ("not set", "no"))
        body = "\n".join(
            (
                "**release note:** `Ship the fix.`",
                "- [x] Omit",
            )
        )
        self.assertEqual(rv.release_fields(body), ("Ship the fix.", "yes"))

    def test_priority_label_is_passed_through(self):
        reviews = sample_reviews()
        seen = {}

        def fake_report(_pr, _link, words):
            seen["words"] = words
            return LABELS

        labels = rv.labels_script()
        pr = rv.parse_pull_request(PR)
        with patch.object(rv, "pull_request_body", return_value=""):
            with patch.object(rv, "collect_reviews", return_value=reviews):
                with patch.object(labels, "label_report", fake_report):
                    comment, verdict = rv.run_review(pr, PR)
        self.assertEqual(seen["words"], ("high",))
        self.assertEqual(verdict, "fail")
        self.assertIn("overwritten by alice", comment)


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("<pull-request>", out)
        self.assertIn("exits 0", out)
        self.assertIn("exits 1", out)
        self.assertIn("real check", out)
        self.assertIn("--publish", out)

    def test_missing_link_prints_help(self):
        rc, out, err = run_main([])
        self.assertEqual(rc, 2)
        self.assertEqual(err, "")
        self.assertIn("Usage:", out)

    def test_invalid_link(self):
        rc, _out, err = run_main(["not-a-pull-request"])
        self.assertEqual(rc, 2)
        self.assertIn("invalid pull request link: not-a-pull-request", err)

    def test_unknown_flag(self):
        rc, _out, err = run_main(["--nope"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown flag: --nope", err)

    def test_prints_without_publishing(self):
        comment = rv.MARKER + "\nReview: approve\n"
        with patch.object(rv, "run_review", return_value=(comment, "approve")):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out, comment)

    def test_error_finding_exits_1(self):
        comment = rv.MARKER + "\nReview: fail\n"
        with patch.object(rv, "run_review", return_value=(comment, "fail")):
            rc, out, err = run_main([PR])
        self.assertEqual(rc, 1)
        self.assertEqual(err, "")
        self.assertEqual(out, comment)

    def test_gh_failure(self):
        with patch.object(
            rv, "run_review", side_effect=RuntimeError("cannot run gh: missing")
        ):
            rc, _out, err = run_main([PR])
        self.assertEqual(rc, 1)
        self.assertIn("cannot run gh: missing", err)


def _gh(payload):
    def fake_run(command, **kwargs):
        _gh.calls.append((list(command), kwargs.get("input")))
        return rv.subprocess.CompletedProcess(
            command, 0, stdout=payload(command), stderr=""
        )

    return fake_run


class TestPublish(unittest.TestCase):
    def setUp(self):
        _gh.calls = []

    def _run(self, verdict):
        comment = f"{rv.MARKER}\nReview: {verdict}\n"

        def payload(command):
            if "--method" not in command:
                return "[]"
            return "{}"

        with patch.object(rv, "run_review", return_value=(comment, verdict)):
            with patch.object(rv.subprocess, "run", _gh(payload)):
                return run_main([PR, "--publish"])

    def test_approval_is_not_submitted(self):
        rc, out, err = self._run("approve")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn(rv.MARKER, out)
        urls = [command[-1] for command, _stdin in _gh.calls]
        self.assertTrue(any(url.endswith("/comments") for url in urls))
        self.assertFalse(any(url.endswith("/reviews") for url in urls))

    def test_error_requests_changes(self):
        rc, _out, err = self._run("fail")
        self.assertEqual((rc, err), (1, ""))
        bodies = [stdin for _command, stdin in _gh.calls if stdin]
        self.assertTrue(any("REQUEST_CHANGES" in body for body in bodies))

    def test_warning_comments(self):
        rc, _out, err = self._run("comment")
        self.assertEqual((rc, err), (0, ""))
        bodies = [stdin for _command, stdin in _gh.calls if stdin]
        self.assertTrue(any('"COMMENT"' in body for body in bodies))

    def test_existing_comment_is_patched(self):
        comment = f"{rv.MARKER}\nReview: approve\n"
        existing = json.dumps([{"id": 9, "body": rv.MARKER + "\nold"}])

        def payload(command):
            if "--method" not in command:
                return existing
            return "{}"

        with patch.object(rv, "run_review", return_value=(comment, "approve")):
            with patch.object(rv.subprocess, "run", _gh(payload)):
                rc, _out, err = run_main([PR, "--publish"])
        self.assertEqual((rc, err), (0, ""))
        patched = [command for command, _stdin in _gh.calls if "PATCH" in command]
        self.assertEqual(len(patched), 1)
        self.assertTrue(patched[0][-1].endswith("/comments/9"))


if __name__ == "__main__":
    unittest.main()
