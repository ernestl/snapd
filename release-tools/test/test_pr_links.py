#!/usr/bin/python3
"""Unit tests for pr-links.py.

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
    """Load the hyphenated pr-links.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-links.py",
    )
    spec = importlib.util.spec_from_file_location("pr_links", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pl = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"
LP = "https://bugs.launchpad.net/snapd/+bug/1"
GH = "https://github.com/canonical/snapd/pull/1"


def fence(fields):
    """Return a references fence. fields maps a link key to its value."""
    lines = ["```references", "contributor: snapd team"]
    for key in pl.LINK_KEYS:
        if key in fields:
            lines.append(f"{key}: {fields[key]}")
    lines.append("```")
    return "\n".join(lines)


def all_na():
    return {key: "N/A" for key in pl.LINK_KEYS}


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


class _Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class StubGh:
    """Replace gh for one test. token is returned by gh auth token."""

    def __init__(self, body, token="", failure=None):
        self.body = body
        self.token = token
        self.failure = failure
        self.original = None

    def __enter__(self):
        self.original = pl.subprocess.run

        def fake_run(command, **_kwargs):
            if command[0] != "gh":
                raise AssertionError(command)
            if self.failure is not None:
                raise self.failure
            if command[1] == "auth":
                if not self.token:
                    return pl.subprocess.CompletedProcess(
                        command, 1, stdout="", stderr="no token"
                    )
                return pl.subprocess.CompletedProcess(
                    command, 0, stdout=self.token + "\n", stderr=""
                )
            payload = json.dumps({"body": self.body})
            return pl.subprocess.CompletedProcess(command, 0, stdout=payload, stderr="")

        pl.subprocess.run = fake_run
        return self

    def __exit__(self, exc_type, exc, tb):
        pl.subprocess.run = self.original


class StubHTTP:
    """Replace urlopen. status None fails the test if a link is requested."""

    def __init__(self, status):
        self.status = status
        self.requests = []
        self.original = None

    def __enter__(self):
        self.original = pl.urllib.request.urlopen

        def fake_urlopen(request, **_kwargs):
            self.requests.append(request)
            if self.status is None:
                raise AssertionError("requested a link")
            if self.status >= 400:
                raise pl.urllib.error.HTTPError(
                    request.full_url, self.status, "error", None, None
                )
            return _Response(self.status)

        pl.urllib.request.urlopen = fake_urlopen
        return self

    def __exit__(self, exc_type, exc, tb):
        pl.urllib.request.urlopen = self.original


def run_body(body, status=None, token=""):
    with StubGh(body, token=token), StubHTTP(status) as http:
        rc, out, err = run_main([PR])
    return rc, out, err, http.requests


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("reference links", out)
        self.assertIn("N/A", out)
        self.assertIn("<pull-request>", out)
        self.assertIn("exits 0", out)

    def test_all_na(self):
        rc, out, err, requests = run_body(fence(all_na()))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Links: yes\n"))
        self.assertLess(out.index("Links:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertIn("Report link: N/A", out)
        self.assertIn("Issue link: N/A", out)
        self.assertIn("Spec link: N/A", out)

    def test_existing_link(self):
        fields = all_na()
        fields["report link"] = LP
        rc, out, err, requests = run_body(fence(fields), status=200)
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Links: yes\n"))
        self.assertIn(f"Report link: exists {LP}", out)
        self.assertEqual(len(requests), 1)
        self.assertIsNone(requests[0].get_header("Authorization"))

    def test_missing_link(self):
        fields = all_na()
        fields["report link"] = LP
        rc, out, err, _requests = run_body(fence(fields), status=404)
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Links: no\n"))
        self.assertIn(f"Report link: missing {LP}", out)

    def test_blank_value(self):
        fields = all_na()
        fields["report link"] = ""
        rc, out, err, requests = run_body(fence(fields))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Links: no\n"))
        self.assertIn("Report link: blank", out)

    def test_absent_key(self):
        fields = all_na()
        del fields["issue link"]
        rc, out, err, _requests = run_body(fence(fields))
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Links: no\n"))
        self.assertIn("Issue link: absent", out)
        self.assertIn("Report link: N/A", out)

    def test_missing_fence(self):
        rc, out, err, requests = run_body("no references fence")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Links: no\n"))
        self.assertIn("Report link: absent", out)
        self.assertIn("Issue link: absent", out)
        self.assertIn("Spec link: absent", out)

    def test_value_is_not_a_link(self):
        fields = all_na()
        fields["report link"] = "bug 1"
        rc, out, err, requests = run_body(fence(fields))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(requests, [])
        self.assertTrue(out.startswith("Links: no\n"))
        self.assertIn("Report link: not a link bug 1", out)

    def test_forbidden_is_unseen(self):
        fields = all_na()
        fields["issue link"] = "https://warthogs.atlassian.net/browse/SNAP-1"
        rc, out, err, _requests = run_body(fence(fields), status=403)
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Links: no\n"))
        self.assertIn(
            "Issue link: unseen https://warthogs.atlassian.net/browse/SNAP-1", out
        )

    def test_github_request_sends_the_token(self):
        fields = all_na()
        fields["report link"] = GH
        rc, out, err, requests = run_body(
            fence(fields), status=200, token="secret-token"
        )
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Links: yes\n"))
        self.assertIn(f"Report link: exists {GH}", out)
        self.assertEqual(len(requests), 1)
        header = requests[0].get_header("Authorization")
        self.assertEqual(header, "Bearer secret-token")

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
