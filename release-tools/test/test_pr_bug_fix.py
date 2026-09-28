#!/usr/bin/python3
"""Unit tests for pr-bug-fix.py.

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


def load_module():
    """Load the hyphenated pr-bug-fix.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-bug-fix.py",
    )
    spec = importlib.util.spec_from_file_location("pr_bug_fix", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bf = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"
LAUNCHPAD = "https://code.launchpad.net/~user/snapd/branch"
SALESFORCE = "https://canonical.lightning.force.com/lightning/r/Case/500"
JIRA = "https://warthogs.atlassian.net/browse/SNAP-1"
GITHUB_ISSUE = "https://github.com/canonical/snapd/issues/1"
GITHUB_PULL = "https://github.com/canonical/snapd/pull/1"
_FORUM_TOPIC = "making-parallel-instances-a-default-on-feature-in-snapd/53360"
FORUM = "https://forum.snapcraft.io/t/" + _FORUM_TOPIC
_ADVISORY_ID = "GHSA-hhm4-4hmr-93v9"
ADVISORY = "https://github.com/canonical/snapd/security/advisories/" + _ADVISORY_ID


def fence(fields):
    """Return a References section. fields maps a link key to its value."""
    lines = ["## References", ""]
    for key in bf.LINK_KEYS:
        if key in fields:
            lines.append(f"**{key}:** {fields[key]}")
    return "\n".join(lines)


def all_na():
    return {key: "N/A" for key in bf.LINK_KEYS}


def with_report(url):
    fields = all_na()
    fields["report link"] = url
    return fence(fields)


def run_main(argv):
    out = StringIO()
    err = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = out
        sys.stderr = err
        rc = bf.main(argv)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return rc, out.getvalue(), err.getvalue()


class _Response:
    def __init__(self, text):
        self._text = text.encode()

    def read(self):
        return self._text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class StubGh:
    """Replace gh. issues maps an issue number to its type name."""

    def __init__(self, body, issues=None, failure=None):
        self.body = body
        self.issues = {} if issues is None else issues
        self.failure = failure
        self.commands = []
        self.original = None

    def __enter__(self):
        self.original = bf.subprocess.run

        def fake_run(command, **_kwargs):
            if command[0] != "gh":
                raise AssertionError(command)
            self.commands.append(command)
            if self.failure is not None:
                raise self.failure
            url = command[-1]
            if "/issues/" in url:
                number = url.rstrip("/").rsplit("/", 1)[-1]
                name = self.issues.get(number)
                if name is None:
                    return bf.subprocess.CompletedProcess(
                        command, 1, stdout="", stderr="missing issue"
                    )
                payload = json.dumps({"type": {"name": name}})
                return bf.subprocess.CompletedProcess(
                    command, 0, stdout=payload, stderr=""
                )
            payload = json.dumps({"body": self.body})
            return bf.subprocess.CompletedProcess(command, 0, stdout=payload, stderr="")

        bf.subprocess.run = fake_run
        return self

    def __exit__(self, exc_type, exc, tb):
        bf.subprocess.run = self.original


class StubJira:
    """Replace the Jira HTTP request. type_name None fails if Jira is called."""

    def __init__(self, type_name):
        self.type_name = type_name
        self.requests = []
        self.original = None

    def __enter__(self):
        self.original = bf.urllib.request.urlopen

        def fake_urlopen(request, **_kwargs):
            self.requests.append(request)
            if self.type_name is None:
                raise AssertionError("requested Jira")
            payload = json.dumps({"fields": {"issuetype": {"name": self.type_name}}})
            return _Response(payload)

        bf.urllib.request.urlopen = fake_urlopen
        return self

    def __exit__(self, exc_type, exc, tb):
        bf.urllib.request.urlopen = self.original


def run_body(body, issues=None, jira_type=None, jira_env=None):
    env = {"JIRA_EMAIL": "", "JIRA_API_TOKEN": ""}
    if jira_env:
        env.update(jira_env)
    with patch.dict(bf.os.environ, env, clear=False):
        with StubGh(body, issues=issues) as gh, StubJira(jira_type) as jira:
            rc, out, err = run_main([PR])
    return rc, out, err, gh.commands, jira.requests


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("bug-fix reference", out)
        self.assertIn("Launchpad", out)
        self.assertIn("<pull-request>", out)
        self.assertIn("exits 0", out)

    def test_markdown_launchpad_link_qualifies(self):
        markdown = "[branch](" + LAUNCHPAD + ")"
        rc, out, err, _commands, requests = run_body(with_report(markdown))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Bug-fix: yes\n"))
        self.assertIn("Report link: launchpad " + LAUNCHPAD, out)

    def test_launchpad_host_qualifies(self):
        rc, out, err, _commands, requests = run_body(with_report(LAUNCHPAD))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Bug-fix: yes\n"))
        self.assertLess(out.index("Bug-fix:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertIn(f"Report link: launchpad {LAUNCHPAD}", out)

    def test_salesforce_host_qualifies(self):
        rc, out, err, _commands, _requests = run_body(with_report(SALESFORCE))
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Bug-fix: yes\n"))
        self.assertIn(f"Report link: salesforce {SALESFORCE}", out)

    def test_jira_bug_qualifies(self):
        rc, out, err, _commands, requests = run_body(
            with_report(JIRA),
            jira_type="Bug",
            jira_env={"JIRA_EMAIL": "a@b.c", "JIRA_API_TOKEN": "token"},
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Bug-fix: yes\n"))
        self.assertIn(f"Report link: jira bug {JIRA}", out)
        self.assertEqual(len(requests), 1)
        self.assertIn("/rest/api/3/issue/SNAP-1", requests[0].full_url)
        self.assertIn("fields=issuetype", requests[0].full_url)

    def test_jira_other_type_does_not_qualify(self):
        rc, out, err, _commands, _requests = run_body(
            with_report(JIRA),
            jira_type="Task",
            jira_env={"JIRA_EMAIL": "a@b.c", "JIRA_API_TOKEN": "token"},
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Bug-fix: no\n"))
        self.assertIn(f"Report link: jira Task {JIRA}", out)

    def test_jira_without_credentials_is_unseen(self):
        rc, out, err, _commands, requests = run_body(with_report(JIRA))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Bug-fix: no\n"))
        self.assertIn(f"Report link: unseen {JIRA}", out)

    def test_github_issue_type_bug_qualifies(self):
        rc, out, err, commands, _requests = run_body(
            with_report(GITHUB_ISSUE), issues={"1": "bug"}
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Bug-fix: yes\n"))
        self.assertIn(f"Report link: github bug {GITHUB_ISSUE}", out)
        issue_calls = [cmd for cmd in commands if "/issues/" in cmd[-1]]
        self.assertEqual(issue_calls, [["gh", "api", "repos/canonical/snapd/issues/1"]])

    def test_github_issue_type_feature_does_not_qualify(self):
        rc, out, err, _commands, _requests = run_body(
            with_report(GITHUB_ISSUE), issues={"1": "Feature"}
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Bug-fix: no\n"))
        self.assertIn(f"Report link: github Feature {GITHUB_ISSUE}", out)

    def test_github_pull_request_is_not_an_issue(self):
        rc, out, err, commands, _requests = run_body(with_report(GITHUB_PULL))
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Bug-fix: no\n"))
        self.assertIn(f"Report link: not a bug-fix link {GITHUB_PULL}", out)
        self.assertFalse(any("/issues/" in cmd[-1] for cmd in commands))

    def test_forum_and_advisory_qualify(self):
        fields = all_na()
        fields["report link"] = FORUM
        fields["spec link"] = ADVISORY
        rc, out, err, commands, _requests = run_body(fence(fields))
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Bug-fix: yes\n"))
        self.assertIn(f"Report link: forum {FORUM}", out)
        self.assertIn("Issue link: N/A", out)
        self.assertIn(f"Spec link: advisory {ADVISORY}", out)
        self.assertFalse(any("/issues/" in cmd[-1] for cmd in commands))

    def test_all_na(self):
        rc, out, err, commands, requests = run_body(fence(all_na()))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertFalse(any("/issues/" in cmd[-1] for cmd in commands))
        self.assertTrue(out.startswith("Bug-fix: no\n"))
        self.assertIn("Report link: N/A", out)
        self.assertIn("Issue link: N/A", out)
        self.assertIn("Spec link: N/A", out)

    def test_missing_link_argument_prints_help(self):
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
        with StubGh("", failure=RuntimeError("cannot run gh: missing")):
            rc, _out, err = run_main([PR])
        self.assertEqual(rc, 1)
        self.assertIn("cannot run gh: missing", err)


if __name__ == "__main__":
    unittest.main()
