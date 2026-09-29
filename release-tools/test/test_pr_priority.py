#!/usr/bin/python3
"""Unit tests for pr-priority.py.

The script filename contains a hyphen, so tests load it with importlib.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring,duplicate-code

import importlib.util
import json
import os
import re
import sys
import unittest
import urllib.error
from io import StringIO
from unittest.mock import patch

KEYS = ("report link", "issue link", "spec link")
JIRA_ENV = {"JIRA_EMAIL": "a@b.c", "JIRA_API_TOKEN": "token"}
SF_ENV = {
    "SALESFORCE_ACCESS_TOKEN": "token",
    "SALESFORCE_INSTANCE_URL": "https://canonical.my.salesforce.com",
}
_JIRA_KEY_RE = re.compile(r"/issue/([A-Za-z][A-Za-z0-9]+-\d+)")


def load_module():
    """Load the hyphenated pr-priority.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-priority.py",
    )
    spec = importlib.util.spec_from_file_location("pr_priority", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pp = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"
LP = "https://bugs.launchpad.net/snapd/+bug/1"
LP_42 = "https://bugs.launchpad.net/snapd/+bug/42"
CASE = "5003000000AbCdE"
SALESFORCE = "https://canonical.lightning.force.com/lightning/r/Case/" + CASE
SALESFORCE_SHORT = "https://canonical.lightning.force.com/lightning/r/Case/500"
JIRA = "https://warthogs.atlassian.net/browse/SNAPDENG-1"
GITHUB_ISSUE = "https://github.com/canonical/snapd/issues/9"
GITHUB_PULL = "https://github.com/canonical/snapd/pull/1"


def fence(fields):
    """Return a References section. fields maps a link key to its value."""
    lines = ["## References", ""]
    for key in KEYS:
        if key in fields:
            lines.append(f"**{key}:** {fields[key]}")
    return "\n".join(lines)


def listed(**kwargs):
    fields = {key: "N/A" for key in KEYS}
    fields.update(kwargs)
    return fence(fields)


def jira_payload(priority, text="", href=""):
    """Return a Jira issue body with a priority and an optional description."""
    content = []
    if text or href:
        node = {"type": "text", "text": text or "bug"}
        if href:
            node["marks"] = [{"type": "link", "attrs": {"href": href}}]
        content.append({"type": "paragraph", "content": [node]})
    description = {"type": "doc", "version": 1, "content": content}
    return {"fields": {"priority": {"name": priority}, "description": description}}


def run_main(argv):
    out = StringIO()
    err = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = out
        sys.stderr = err
        rc = pp.main(argv)
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
    """Replace gh. issues maps an issue number to a list of label names."""

    def __init__(self, body, issues=None, failure=None):
        self.body = body
        self.issues = {} if issues is None else issues
        self.failure = failure
        self.commands = []
        self.original = None

    def __enter__(self):
        self.original = pp.subprocess.run

        def fake_run(command, **_kwargs):
            if command[0] != "gh":
                raise AssertionError(command)
            self.commands.append(command)
            if self.failure is not None:
                raise self.failure
            url = command[-1]
            if "/issues/" in url:
                number = url.rstrip("/").rsplit("/", 1)[-1]
                names = self.issues.get(number)
                if names is None:
                    return pp.subprocess.CompletedProcess(
                        command, 1, stdout="", stderr="missing issue"
                    )
                payload = {"labels": [{"name": name} for name in names]}
                return pp.subprocess.CompletedProcess(
                    command, 0, stdout=json.dumps(payload), stderr=""
                )
            payload = json.dumps({"body": self.body})
            return pp.subprocess.CompletedProcess(command, 0, stdout=payload, stderr="")

        pp.subprocess.run = fake_run
        return self

    def __exit__(self, exc_type, exc, tb):
        pp.subprocess.run = self.original


class StubHTTP:
    """Replace urlopen. A missing fixture raises if that host is requested."""

    def __init__(self, launchpad=None, jira=None, remote=None, salesforce=None):
        self.launchpad = launchpad
        self.jira = jira
        self.remote = {} if remote is None else remote
        self.salesforce = salesforce
        self.requests = []
        self.original = None

    def __enter__(self):
        self.original = pp.urllib.request.urlopen

        def fake_urlopen(request, **_kwargs):
            self.requests.append(request)
            return _Response(json.dumps(self._payload(request.full_url)))

        pp.urllib.request.urlopen = fake_urlopen
        return self

    def __exit__(self, exc_type, exc, tb):
        pp.urllib.request.urlopen = self.original

    def _payload(self, url):
        if "api.launchpad.net" in url:
            return {"importance": self._launchpad(url)}
        if "remotelink" in url:
            return self._remote(url)
        if "/rest/api/3/field" in url:
            if self.jira is None:
                raise AssertionError(url)
            return [{"id": "customfield_10400", "name": "Bug Link"}]
        if "atlassian.net" in url:
            return self._jira(url)
        if "sobjects/Case" in url:
            return self._case()
        raise AssertionError(url)

    def _launchpad(self, url):
        if self.launchpad is None:
            raise AssertionError(url)
        bug = url.rstrip("/").split("?")[0].rsplit("/", 1)[-1]
        importance = self.launchpad.get(bug)
        if importance is None:
            raise urllib.error.URLError("missing bug")
        return importance

    def _jira_key(self, url):
        if self.jira is None:
            raise AssertionError(url)
        match = _JIRA_KEY_RE.search(url)
        if not match:
            raise AssertionError(url)
        return match.group(1)

    def _jira(self, url):
        key = self._jira_key(url)
        issue = self.jira.get(key)
        if issue is None:
            raise urllib.error.URLError("missing issue")
        return issue

    def _remote(self, url):
        key = self._jira_key(url)
        return self.remote.get(key, [])

    def _case(self):
        if self.salesforce is None:
            raise AssertionError("requested Salesforce")
        return self.salesforce


def run_body(body, **kwargs):
    env = {
        "JIRA_EMAIL": "",
        "JIRA_API_TOKEN": "",
        "SALESFORCE_ACCESS_TOKEN": "",
        "SALESFORCE_INSTANCE_URL": "",
        "SALESFORCE_SEVERITY_FIELD": "",
        "JIRA_BUG_LINK_FIELD": "",
    }
    env.update(kwargs.pop("env", {}))
    gh_failure = kwargs.pop("gh_failure", None)
    with patch.dict(pp.os.environ, env, clear=False):
        with StubGh(body, issues=kwargs.get("issues"), failure=gh_failure) as gh:
            with StubHTTP(
                launchpad=kwargs.get("launchpad"),
                jira=kwargs.get("jira"),
                remote=kwargs.get("remote"),
                salesforce=kwargs.get("salesforce"),
            ) as http:
                rc, out, err = run_main([PR])
    return rc, out, err, gh.commands, http.requests


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("priority", out)
        self.assertIn("Launchpad", out)
        self.assertIn("<pull-request>", out)
        self.assertIn("exits 0", out)

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

    def test_all_na(self):
        rc, out, err, commands, requests = run_body(listed())
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertEqual(len(commands), 1)
        self.assertTrue(out.startswith("Priority: unknown\n"))
        self.assertLess(out.index("Priority:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertIn("Launchpad: none", out)
        self.assertIn("Salesforce: none", out)
        self.assertIn("Jira: none", out)
        self.assertIn("GitHub issue: none", out)
        with patch.dict(
            pp.os.environ,
            {
                "JIRA_EMAIL": "",
                "JIRA_API_TOKEN": "",
                "SALESFORCE_ACCESS_TOKEN": "",
                "SALESFORCE_INSTANCE_URL": "",
                "SALESFORCE_SEVERITY_FIELD": "",
                "JIRA_BUG_LINK_FIELD": "",
            },
            clear=False,
        ):
            with StubGh(listed()), StubHTTP():
                result = pp.review(pp.parse_pull_request(PR))
        self.assertEqual(result.facts, ("Priority: unknown",))
        self.assertEqual(result.labels, ())
        self.assertEqual(result.findings, ())

    def test_na_is_case_insensitive(self):
        body = listed(**{"report link": "n/a", "issue link": "N/a", "spec link": "n/A"})
        rc, out, err, _commands, requests = run_body(body)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Priority: unknown\n"))

    def test_launchpad_importance(self):
        mapping = [
            ("Critical", "critical"),
            ("High", "high"),
            ("Medium", "medium"),
            ("Low", "low"),
            ("Wishlist", "low"),
        ]
        for importance, level in mapping:
            rc, out, err, _commands, requests = run_body(
                listed(**{"report link": LP}),
                launchpad={"1": importance},
            )
            self.assertEqual((rc, err), (0, ""), importance)
            self.assertTrue(out.startswith(f"Priority: {level}\n"), out)
            self.assertIn(f"Launchpad: {level}", out)
            self.assertEqual(len(requests), 1)
            self.assertIn("/bugs/1", requests[0].full_url)
            if level == "high":
                with patch.dict(
                    pp.os.environ,
                    {
                        "JIRA_EMAIL": "",
                        "JIRA_API_TOKEN": "",
                        "SALESFORCE_ACCESS_TOKEN": "",
                        "SALESFORCE_INSTANCE_URL": "",
                        "SALESFORCE_SEVERITY_FIELD": "",
                        "JIRA_BUG_LINK_FIELD": "",
                    },
                    clear=False,
                ):
                    with StubGh(listed(**{"report link": LP})):
                        with StubHTTP(launchpad={"1": importance}):
                            result = pp.review(pp.parse_pull_request(PR))
                self.assertEqual(result.facts, ("Priority: high",))
                self.assertEqual(result.labels, ("high",))
                self.assertEqual(result.findings, ())
        rc, out, err, _commands, _requests = run_body(
            listed(**{"report link": LP}),
            launchpad={"1": "Undecided"},
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Priority: unknown\n"))
        self.assertIn("Launchpad: none", out)

    def test_salesforce_severity_is_not_read_yet(self):
        rc, out, err, _commands, requests = run_body(
            listed(**{"report link": SALESFORCE}),
            salesforce={"Severity__c": "1"},
            env=SF_ENV,
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Priority: unknown\n"))
        self.assertIn("Salesforce: none", out)

    def test_salesforce_without_case_id_is_not_a_failure(self):
        rc, out, err, _commands, requests = run_body(
            listed(**{"report link": SALESFORCE_SHORT}),
            env=SF_ENV,
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Priority: unknown\n"))
        self.assertIn("Salesforce: none", out)

    def test_jira_priorities(self):
        mapping = [
            ("Highest", "critical"),
            ("Critical", "critical"),
            ("High", "high"),
            ("Medium", "medium"),
            ("Low", "low"),
            ("Lowest", "low"),
        ]
        for name, level in mapping:
            rc, out, err, _commands, _requests = run_body(
                listed(**{"issue link": JIRA}),
                jira={"SNAPDENG-1": jira_payload(name)},
                env=JIRA_ENV,
            )
            self.assertEqual((rc, err), (0, ""), name)
            self.assertTrue(out.startswith(f"Priority: {level}\n"), out)
            self.assertIn(f"Jira: {level}", out)
        rc, out, err, _commands, _requests = run_body(
            listed(**{"issue link": JIRA}),
            jira={"SNAPDENG-1": jira_payload("Blocker")},
            env=JIRA_ENV,
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Priority: unknown\n"))
        self.assertIn("Jira: none", out)

    def test_jira_without_credentials_is_unknown(self):
        rc, out, err, _commands, requests = run_body(listed(**{"issue link": JIRA}))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Priority: unknown\n"))
        self.assertIn("Jira: unknown", out)

    def test_github_issue_labels(self):
        rc, out, err, commands, _requests = run_body(
            listed(**{"issue link": GITHUB_ISSUE}),
            issues={"9": ["low", "critical"]},
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Priority: critical\n"))
        self.assertIn("GitHub issue: critical", out)
        self.assertTrue(any(cmd[-1].endswith("/issues/9") for cmd in commands))

    def test_github_pull_request_is_not_a_source(self):
        rc, out, err, commands, requests = run_body(
            listed(**{"issue link": GITHUB_PULL})
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertFalse(any("/issues/" in cmd[-1] for cmd in commands))
        self.assertTrue(out.startswith("Priority: unknown\n"))
        self.assertIn("GitHub issue: none", out)

    def test_highest_of_mixed_sources(self):
        body = listed(**{"report link": LP, "issue link": JIRA})
        rc, out, err, _commands, _requests = run_body(
            body,
            launchpad={"1": "Medium"},
            jira={"SNAPDENG-1": jira_payload("Highest")},
            env=JIRA_ENV,
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Priority: critical\n"))
        self.assertIn("Launchpad: medium", out)
        self.assertIn("Jira: critical", out)

    def test_description_brings_in_launchpad(self):
        text = "see " + LP_42
        rc, out, err, _commands, requests = run_body(
            listed(**{"issue link": JIRA}),
            launchpad={"42": "High"},
            jira={"SNAPDENG-1": jira_payload("Medium", text=text, href=LP_42)},
            env=JIRA_ENV,
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Priority: high\n"))
        self.assertIn("Launchpad: high", out)
        self.assertIn("Jira: medium", out)
        self.assertIn("from SNAPDENG-1: " + LP_42, out)
        launchpad_calls = [req for req in requests if "launchpad" in req.full_url]
        self.assertEqual(len(launchpad_calls), 1)

    def test_remote_link_brings_in_salesforce(self):
        remote = {"SNAPDENG-1": [{"object": {"url": SALESFORCE}}]}
        rc, out, err, _commands, requests = run_body(
            listed(**{"issue link": JIRA}),
            jira={"SNAPDENG-1": jira_payload("Medium")},
            remote=remote,
            salesforce={"Severity__c": "1"},
            env={**JIRA_ENV, **SF_ENV},
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Priority: medium\n"))
        self.assertIn("Salesforce: none", out)
        self.assertIn("Jira: medium", out)
        self.assertIn("from SNAPDENG-1: " + SALESFORCE, out)
        self.assertFalse(any("sobjects/Case" in req.full_url for req in requests))

    def test_bug_link_field_brings_in_salesforce(self):
        issue = jira_payload("Medium")
        issue["fields"]["customfield_10400"] = SALESFORCE
        rc, out, err, _commands, requests = run_body(
            listed(**{"issue link": JIRA}),
            jira={"SNAPDENG-1": issue},
            salesforce={"Severity__c": "2"},
            env={**JIRA_ENV, **SF_ENV},
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Priority: medium\n"))
        self.assertIn("Salesforce: none", out)
        self.assertIn("Jira: medium", out)
        self.assertIn("from SNAPDENG-1: " + SALESFORCE, out)
        self.assertTrue(any("/rest/api/3/field" in req.full_url for req in requests))
        self.assertTrue(any("customfield_10400" in req.full_url for req in requests))
        self.assertFalse(any("sobjects/Case" in req.full_url for req in requests))
        rc, out, err, _commands, requests = run_body(
            listed(**{"issue link": JIRA}),
            jira={"SNAPDENG-1": issue},
            env=JIRA_ENV,
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Priority: medium\n"))
        self.assertIn("Salesforce: none", out)
        self.assertIn("from SNAPDENG-1: " + SALESFORCE, out)
        self.assertFalse(any("sobjects/Case" in req.full_url for req in requests))

    def test_same_bug_on_the_pull_request_is_not_repeated(self):
        body = listed(**{"report link": LP, "issue link": JIRA})
        rc, out, err, _commands, requests = run_body(
            body,
            launchpad={"1": "High"},
            jira={"SNAPDENG-1": jira_payload("Low", text="see " + LP)},
            env=JIRA_ENV,
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Priority: high\n"))
        self.assertNotIn("from SNAPDENG-1", out)
        launchpad_calls = [req for req in requests if "launchpad" in req.full_url]
        self.assertEqual(len(launchpad_calls), 1)

    def test_unreadable_source_forces_unknown(self):
        body = listed(**{"report link": LP, "issue link": JIRA})
        rc, out, err, _commands, _requests = run_body(
            body,
            launchpad={},
            jira={"SNAPDENG-1": jira_payload("Low")},
            env=JIRA_ENV,
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Priority: unknown\n"))
        self.assertIn("Launchpad: unknown", out)
        self.assertIn("Jira: low", out)


if __name__ == "__main__":
    unittest.main()
