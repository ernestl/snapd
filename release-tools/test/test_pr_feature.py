#!/usr/bin/python3
"""Unit tests for pr-feature.py.

The script filename contains a hyphen, so tests load it with importlib.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring,duplicate-code

import importlib.util
import json
import os
import sys
import unittest
from io import StringIO


def load_module():
    """Load the hyphenated pr-feature.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-feature.py",
    )
    spec = importlib.util.spec_from_file_location("pr_feature", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pf = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"
BASE = "base-sha"
HEAD = "head-sha"

CONFDB = "Configuration based on a confdb and views."


def features_text(*entries):
    """Return a features.yaml document. An entry is (name, description)."""
    lines = ["features:"]
    for name, description in entries:
        lines.append(f"  - name: {name}")
        if description is not None:
            lines.append(f"    description: {description}")
    return "\n".join(lines) + "\n"


def pull_json():
    return json.dumps({"base": {"sha": BASE}, "head": {"sha": HEAD}})


def run_main(argv):
    out = StringIO()
    err = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = out
        sys.stderr = err
        rc = pf.main(argv)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return rc, out.getvalue(), err.getvalue()


class StubGh:
    """Replace gh for one test.

    files maps a commit sha to file text. None means the file is missing.
    failure, when set, is raised from the first gh call.
    """

    def __init__(self, files, failure=None):
        self.files = files
        self.failure = failure
        self.original = None

    def __enter__(self):
        self.original = pf.subprocess.run

        def fake_run(command, **_kwargs):
            if command[0] != "gh":
                raise AssertionError(command)
            if self.failure is not None:
                raise self.failure
            url = command[-1]
            if "/contents/" not in url:
                return pf.subprocess.CompletedProcess(
                    command, 0, stdout=pull_json(), stderr=""
                )
            sha = url.split("ref=", 1)[1]
            body = self.files[sha]
            if body is None:
                return pf.subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="",
                    stderr="gh: Not Found (HTTP 404)",
                )
            return pf.subprocess.CompletedProcess(command, 0, stdout=body, stderr="")

        pf.subprocess.run = fake_run
        return self

    def __exit__(self, exc_type, exc, tb):
        pf.subprocess.run = self.original


def run_files(base, head):
    with StubGh({BASE: base, HEAD: head}):
        return run_main([PR])


class TestCompare(unittest.TestCase):
    def test_new_name_with_description_is_added(self):
        base = features_text(("confdb", CONFDB))
        head = features_text(
            ("confdb", CONFDB),
            ("clustering", "Cluster snapd devices."),
        )
        change = pf.compare_features(base, head)
        self.assertEqual(change.added, (("clustering", "Cluster snapd devices."),))
        self.assertEqual(change.incomplete, ())
        self.assertEqual(pf.feature_decision(change), "yes")

    def test_name_without_description_is_incomplete(self):
        base = features_text(("confdb", CONFDB))
        head = features_text(("confdb", CONFDB), ("clustering", None))
        change = pf.compare_features(base, head)
        self.assertEqual(change.added, ())
        self.assertEqual(change.incomplete, ("clustering",))
        self.assertEqual(pf.feature_decision(change), "no")

    def test_description_edit_is_not_an_addition(self):
        base = features_text(("confdb", CONFDB))
        head = features_text(("confdb", "A rewritten description."))
        change = pf.compare_features(base, head)
        self.assertEqual(change.added, ())
        self.assertEqual(change.incomplete, ())

    def test_removal_is_not_an_addition(self):
        base = features_text(("confdb", CONFDB))
        head = features_text()
        change = pf.compare_features(base, head)
        self.assertEqual(change.added, ())
        self.assertEqual(change.incomplete, ())

    def test_unchanged_file_adds_nothing(self):
        text = features_text(("confdb", CONFDB))
        change = pf.compare_features(text, text)
        self.assertEqual(pf.feature_decision(change), "no")

    def test_identical_empty_documents_add_nothing(self):
        change = pf.compare_features("", "")
        self.assertEqual(change.added, ())
        self.assertEqual(change.incomplete, ())


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("feature name", out)
        self.assertIn("release-tools/features.yaml", out)
        self.assertIn("<pull-request>", out)
        self.assertIn("exits 0", out)

    def test_added_name_prints_the_decision_first(self):
        base = features_text()
        head = features_text(("confdb", CONFDB))
        rc, out, err = run_files(base, head)
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Feature: yes\n"))
        self.assertLess(out.index("Feature:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertIn("Added: 1", out)
        self.assertIn(f"confdb: {CONFDB}", out)
        self.assertNotIn("Incomplete:", out)

    def test_name_without_description(self):
        base = features_text(("confdb", CONFDB))
        head = features_text(("confdb", CONFDB), ("clustering", None))
        rc, out, err = run_files(base, head)
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Feature: no\n"))
        self.assertIn("Added: 0", out)
        self.assertIn("Incomplete: 1", out)
        self.assertIn("clustering", out)
        self.assertNotIn("Added:\n", out)

    def test_description_edit(self):
        base = features_text(("confdb", CONFDB))
        head = features_text(("confdb", "A rewritten description."))
        rc, out, err = run_files(base, head)
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Feature: no\n"))
        self.assertIn("Added: 0", out)
        self.assertNotIn("Incomplete:", out)
        self.assertNotIn("rewritten", out)

    def test_removal(self):
        rc, out, err = run_files(features_text(("confdb", CONFDB)), features_text())
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Feature: no\n"))
        self.assertIn("Added: 0", out)

    def test_unchanged_file(self):
        text = features_text(("confdb", CONFDB))
        rc, out, err = run_files(text, text)
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Feature: no\n"))
        self.assertIn("Added: 0", out)

    def test_file_absent_on_the_base(self):
        head = features_text(("confdb", CONFDB))
        rc, out, err = run_files(None, head)
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Feature: yes\n"))
        self.assertIn(f"confdb: {CONFDB}", out)

    def test_identical_empty_contents(self):
        rc, out, err = run_files("", "")
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Feature: no\n"))
        self.assertIn("Added: 0", out)
        self.assertNotIn("Incomplete:", out)

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

    def test_gh_failure(self):
        with StubGh({}, failure=RuntimeError("cannot run gh: missing")):
            rc, _out, err = run_main([PR])
        self.assertEqual(rc, 1)
        self.assertIn("cannot run gh: missing", err)


if __name__ == "__main__":
    unittest.main()
