#!/usr/bin/python3
"""Unit tests for pr-summary.py.

The script filename contains a hyphen, so tests load it with importlib.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring,duplicate-code

import importlib.util
import os
import sys
import unittest
from io import StringIO
from unittest.mock import Mock, patch


def load_module():
    """Load the hyphenated pr-summary.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-summary.py",
    )
    spec = importlib.util.spec_from_file_location("pr_summary", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ps = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"


def run_main(argv):
    out = StringIO()
    err = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = out
        sys.stderr = err
        rc = ps.main(argv)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return rc, out.getvalue(), err.getvalue()


class TestDecide(unittest.TestCase):
    def test_at_the_limit_may_be_omitted(self):
        self.assertEqual(ps.decide(ps.TRIVIAL_MAX), "optional")

    def test_above_the_limit_is_required(self):
        self.assertEqual(ps.decide(ps.TRIVIAL_MAX + 1), "required")


class TestEffortReport(unittest.TestCase):
    def test_reads_the_first_line(self):
        report = "Effort: 15.5\nBand: trivial\n"
        self.assertEqual(ps.parse_effort_report(report), 15.5)

    def test_rejects_a_report_without_effort(self):
        with self.assertRaises(RuntimeError):
            ps.parse_effort_report("Band: trivial\n")

    def test_reads_effort_from_the_complexity_script(self):
        mod = Mock()
        mod.UsageError = type("UsageError", (Exception,), {})

        def fake_main(_argv):
            print("Effort: 15.5")
            print("Band: trivial")
            return 0

        mod.main.side_effect = fake_main
        with patch.object(ps, "_load_complexity", return_value=mod):
            self.assertEqual(ps.effort_for_link(PR), 15.5)
        mod.parse_pull_request.assert_called_once_with(PR)


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("may be omitted", out)
        self.assertIn("TRIVIAL_MAX", out)
        self.assertIn("pr-complexity.py", out)
        self.assertIn("<pull-request>", out)

    def test_optional(self):
        with patch.object(ps, "effort_for_link", return_value=12):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Change summary: optional\n"))
        self.assertLess(out.index("Change summary:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertLess(out.index(f"Pull request: {PR}"), out.index("Effort: 12.0"))
        self.assertLess(out.index("Effort: 12.0"), out.index("Limit: 20"))

    def test_required(self):
        with patch.object(ps, "effort_for_link", return_value=40):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Change summary: required\n"))
        self.assertLess(out.index("Change summary:"), out.index("Details:"))

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

    def test_complexity_failure(self):
        with patch.object(
            ps, "effort_for_link", side_effect=RuntimeError("cannot run gh: missing")
        ):
            rc, _out, err = run_main([PR])
        self.assertEqual(rc, 1)
        self.assertIn("cannot run gh: missing", err)


if __name__ == "__main__":
    unittest.main()
