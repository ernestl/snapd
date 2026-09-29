#!/usr/bin/python3
"""Unit tests for pr-labels.py.

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
    """Load the hyphenated pr-labels.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-labels.py",
    )
    spec = importlib.util.spec_from_file_location("pr_labels", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pl = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"
FEATURES = """features:
  - name: confdb
    description: Configuration based on a confdb and views.
"""


def event(name, label, actor):
    """Return one timeline label event."""
    return {"event": name, "actor": {"login": actor}, "label": {"name": label}}


def run_main(argv):
    out = StringIO()
    err = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = out
        sys.stderr = err
        rc = pl.main(argv)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return rc, out.getvalue(), err.getvalue()


class StubGh:
    """Replace gh. labels are the names already on the pull request."""

    def __init__(
        self, labels=None, events=None, login="bot", failure=None, features=None
    ):
        self.labels = [] if labels is None else labels
        self.events = [] if events is None else events
        self.login = login
        self.failure = failure
        self.features = FEATURES if features is None else features
        self.calls = []
        self.original = None

    def __enter__(self):
        feature_mod = pl._features()
        self.original = (pl.subprocess.run, feature_mod.subprocess.run)

        def fake_run(command, **kwargs):
            self.calls.append((list(command), kwargs.get("input")))
            if self.failure is not None:
                raise self.failure
            url = command[-1]
            if url == "user":
                payload = json.dumps({"login": self.login})
            elif url.endswith("/timeline"):
                payload = json.dumps(self.events)
            elif "/labels" in url:
                payload = ""
            elif "/issues/" in url:
                payload = json.dumps(
                    {"labels": [{"name": name} for name in self.labels]}
                )
            elif "/pulls/" in url:
                payload = json.dumps({"base": {"sha": "base"}, "head": {"sha": "head"}})
            elif "features.yaml" in url:
                payload = self.features
            else:
                raise AssertionError(command)
            return pl.subprocess.CompletedProcess(command, 0, stdout=payload, stderr="")

        pl.subprocess.run = fake_run
        feature_mod.subprocess.run = fake_run
        return self

    def __exit__(self, exc_type, exc, tb):
        labels_run, feature_run = self.original
        pl.subprocess.run = labels_run
        pl._features().subprocess.run = feature_run


def run_labels(label_text, **kwargs):
    with StubGh(**kwargs) as gh:
        rc, out, err = run_main([PR, *label_text.split()])
    return rc, out, err, gh.calls


def added(calls):
    """Return label lists posted to the labels endpoint."""
    found = []
    for command, stdin in calls:
        if "--method" in command and "POST" in command and stdin:
            found.append(json.loads(stdin)["labels"])
    return found


def removed(calls):
    """Return label names deleted from the pull request."""
    found = []
    for command, _stdin in calls:
        if "DELETE" not in command:
            continue
        found.append(command[-1].rstrip("/").rsplit("/", 1)[-1])
    return found


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("Allowlist:", out)
        self.assertIn("Priority: critical, high, medium, low", out)
        self.assertIn("Roadmap: roadmap", out)
        self.assertIn("Category: bug-fix, test-fix, interface, packaging,", out)
        self.assertIn("Only one priority label may be set.", out)
        self.assertIn("Roadmap is yes or no.", out)
        self.assertNotIn("workaround", out)
        self.assertIn("Only one feature label", out)
        self.assertIn("features.yaml", out)
        self.assertIn("overwritten by", out)
        self.assertIn("<pull-request>", out)
        self.assertIn("exits 0", out)

    def test_missing_arguments_print_help(self):
        rc, out, err = run_main([])
        self.assertEqual(rc, 2)
        self.assertEqual(err, "")
        self.assertIn("Usage:", out)
        rc, out, err = run_main([PR])
        self.assertEqual(rc, 2)
        self.assertIn("Usage:", out)

    def test_invalid_link(self):
        rc, _out, err = run_main(["not-a-pull-request", "critical"])
        self.assertEqual(rc, 2)
        self.assertIn("invalid pull request link: not-a-pull-request", err)

    def test_unknown_flag(self):
        rc, _out, err = run_main(["--nope"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown flag: --nope", err)

    def test_label_not_allowed(self):
        rc, _out, err, _calls = run_labels("critical Nope")
        self.assertEqual(rc, 2)
        self.assertIn("label is not allowed: Nope", err)

    def test_comma_does_not_separate_labels(self):
        rc, _out, err, _calls = run_labels("critical,roadmap")
        self.assertEqual(rc, 2)
        self.assertIn("label is not allowed: critical,roadmap", err)

    def test_gh_failure(self):
        with StubGh(failure=RuntimeError("cannot run gh: missing")):
            rc, _out, err = run_main([PR, "critical"])
        self.assertEqual(rc, 1)
        self.assertIn("cannot run gh: missing", err)

    def test_applies_a_priority(self):
        rc, out, err, calls = run_labels("critical")
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: applied\n"))
        self.assertLess(out.index("Labels:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertIn("Priority: critical (automatic)", out)
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [["critical"]])

    def test_only_one_priority(self):
        rc, _out, err = run_main([PR, "critical", "high"])
        self.assertEqual(rc, 2)
        self.assertIn("only one priority label is allowed", err)

    def test_replaces_other_priorities(self):
        rc, out, err, calls = run_labels(
            "critical",
            labels=["low", "documentation"],
            events=[event("labeled", "low", "bot")],
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: applied\n"))
        self.assertEqual(removed(calls), ["low"])
        self.assertEqual(added(calls), [["critical"]])
        self.assertNotIn("documentation", out)

    def test_already_applied_does_not_change_labels(self):
        rc, out, err, calls = run_labels("critical", labels=["critical"])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: applied\n"))
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [])

    def test_skips_a_type_modified_by_someone_else(self):
        rc, out, err, calls = run_labels(
            "critical",
            labels=["high"],
            events=[
                event("labeled", "high", "alice"),
                event("unlabeled", "low", "bob"),
            ],
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: override\n"))
        self.assertIn("Priority: high (overwritten by bob)", out)
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [])

    def test_script_user_may_still_modify(self):
        rc, out, err, calls = run_labels(
            "critical",
            labels=["low"],
            events=[event("labeled", "low", "bot")],
            login="bot",
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: applied\n"))
        self.assertEqual(removed(calls), ["low"])
        self.assertEqual(added(calls), [["critical"]])

    def test_unset_roadmap_is_automatic(self):
        rc, out, err, calls = run_labels("critical")
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: applied\n"))
        self.assertIn("Roadmap: no (automatic)", out)
        self.assertIn("  bug-fix: no (automatic)", out)
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [["critical"]])

    def test_applies_roadmap(self):
        rc, out, err, calls = run_labels("critical roadmap")
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: applied\n"))
        self.assertIn("Roadmap: yes (automatic)", out)
        self.assertEqual(added(calls), [["roadmap"], ["critical"]])

    def test_roadmap_set_by_someone_else(self):
        rc, out, err, calls = run_labels(
            "critical roadmap",
            labels=["roadmap"],
            events=[event("labeled", "roadmap", "alice")],
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: partial\n"))
        self.assertIn("Roadmap: yes (overwritten by alice)", out)
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [["critical"]])

    def test_roadmap_removed_by_someone_else(self):
        rc, out, err, calls = run_labels(
            "roadmap",
            events=[event("unlabeled", "roadmap", "alice")],
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: override\n"))
        self.assertIn("Roadmap: no (overwritten by alice)", out)
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [])

    def test_roadmap_already_set_is_automatic(self):
        rc, out, err, calls = run_labels(
            "critical",
            labels=["roadmap"],
            events=[event("labeled", "roadmap", "bot")],
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("Roadmap: yes (automatic)", out)
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [["critical"]])

    def test_priority_removed_by_someone_else(self):
        rc, out, err, calls = run_labels(
            "critical",
            events=[event("unlabeled", "high", "alice")],
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: override\n"))
        self.assertIn("Priority: not set (overwritten by alice)", out)
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [])

    def test_categories_are_yes_or_no(self):
        rc, out, err, calls = run_labels(
            "bug-fix packaging internal",
            labels=["interface", "documentation"],
            events=[event("labeled", "interface", "bot")],
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: applied\n"))
        self.assertIn("Roadmap: no (automatic)", out)
        self.assertIn("Priority: not set (automatic)", out)
        expected = (
            ("bug-fix", "yes"),
            ("test-fix", "no"),
            ("interface", "no"),
            ("packaging", "yes"),
            ("systemd-services", "no"),
            ("internal", "yes"),
        )
        for label, value in expected:
            self.assertIn(f"  {label}: {value} (automatic)", out)
        self.assertNotIn("documentation", out)
        self.assertEqual(removed(calls), ["interface"])
        self.assertEqual(added(calls), [["bug-fix", "packaging", "internal"]])

        rc, out, err, calls = run_labels(
            "bug-fix",
            labels=["interface"],
            events=[
                event("labeled", "interface", "alice"),
                event("unlabeled", "packaging", "bob"),
            ],
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: override\n"))
        self.assertIn("  interface: yes (overwritten by bob)", out)
        self.assertIn("  bug-fix: no (overwritten by bob)", out)
        self.assertIn("  packaging: no (overwritten by bob)", out)
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [])


class TestFeature(unittest.TestCase):
    def test_applies_one_feature_or_reports_not_set(self):
        rc, out, err, calls = run_labels("confdb")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("Feature: confdb (automatic)", out)
        self.assertEqual(added(calls), [["confdb"]])

        rc, out, err, calls = run_labels("critical")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("Feature: not set (automatic)", out)
        self.assertEqual(added(calls), [["critical"]])

    def test_name_added_on_the_head(self):
        text = "features:\n  - name: added-feature\n    description: New.\n"
        rc, out, err, calls = run_labels("added-feature", features=text)
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("Feature: added-feature (automatic)", out)
        self.assertEqual(added(calls), [["added-feature"]])

    def test_only_one_feature_and_a_foreign_change(self):
        text = (
            "features:\n"
            "  - name: confdb\n"
            "    description: A.\n"
            "  - name: clustering\n"
            "    description: B.\n"
        )
        rc, _out, err, _calls = run_labels("confdb clustering", features=text)
        self.assertEqual(rc, 2)
        self.assertIn("only one feature label is allowed", err)

        rc, out, err, calls = run_labels(
            "clustering",
            labels=["confdb"],
            events=[event("labeled", "confdb", "alice")],
            features=text,
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Labels: override\n"))
        self.assertIn("Feature: confdb (overwritten by alice)", out)
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [])

        rc, out, err, calls = run_labels(
            "confdb",
            events=[event("unlabeled", "confdb", "alice")],
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("Feature: not set (overwritten by alice)", out)
        self.assertEqual(removed(calls), [])
        self.assertEqual(added(calls), [])


if __name__ == "__main__":
    unittest.main()
