# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

from __future__ import annotations

import unittest

from test_maintenance.pr_resolve import GitHubClient, ResolvedPR, cherry_picked_from, pr_number_from_subject
from test_maintenance.select import Candidate, dedupe_candidates
from test_maintenance.summary import format_branch_summary
from test_maintenance.apply import BranchResult, Conflict


class PRResolveTest(unittest.TestCase):
    def test_subject_last_number(self):
        self.assertEqual(pr_number_from_subject("tests: foo (#17564)"), 17564)
        self.assertEqual(pr_number_from_subject("Revert \"tests: foo (#1)\" (#2)"), 2)
        self.assertIsNone(pr_number_from_subject("tests: no number"))
        self.assertEqual(
            cherry_picked_from("\n(cherry picked from commit abcdef1234567890)\n"),
            "abcdef1234567890",
        )

    def test_subject_then_associated(self):
        pulls = {
            "/repos/canonical/snapd/pulls/17564": {
                "number": 17564,
                "title": "tests: stop testing setup-staging-store",
                "html_url": "https://github.com/canonical/snapd/pull/17564",
            }
        }

        def api_get(path: str):
            if path in pulls:
                return pulls[path]
            self.fail(f"unexpected API {path}")

        client = GitHubClient("canonical/snapd", token="x", api_get=api_get)
        pr = client.resolve_commit("abc123", subject="tests: stop testing setup-staging-store (#17564)")
        self.assertIsNotNone(pr)
        self.assertEqual(pr.number, 17564)
        self.assertEqual(pr.sha, "abc123")

    def test_associated_pulls_fallback(self):
        def api_get(path: str):
            if path == "/repos/canonical/snapd/commits/deadbeef/pulls":
                return [
                    {
                        "number": 17472,
                        "title": "tests: fix json",
                        "html_url": "https://github.com/canonical/snapd/pull/17472",
                        "merged_at": "2026-08-11T00:00:00Z",
                        "base": {"ref": "master"},
                    }
                ]
            self.fail(f"unexpected API {path}")

        client = GitHubClient("canonical/snapd", token="x", api_get=api_get)
        pr = client.resolve_commit("deadbeef", subject="tests: fix json")
        self.assertEqual(pr.number, 17472)

    def test_unresolved(self):
        def api_get(path: str):
            if path.endswith("/pulls"):
                return []
            if path.startswith("/search/issues"):
                return {"items": []}
            self.fail(f"unexpected API {path}")

        client = GitHubClient("canonical/snapd", token="x", api_get=api_get)
        self.assertIsNone(client.resolve_commit("fff", subject="tests: mystery"))

    def test_cache_per_sha(self):
        calls = {"n": 0}

        def api_get(path: str):
            calls["n"] += 1
            return {
                "number": 1,
                "title": "t",
                "html_url": "https://github.com/canonical/snapd/pull/1",
            }

        client = GitHubClient("canonical/snapd", token="x", api_get=api_get)
        client.resolve_commit("aaa", subject="x (#1)")
        client.resolve_commit("aaa", subject="x (#1)")
        self.assertEqual(calls["n"], 1)


class DedupeTest(unittest.TestCase):
    def _cand(self, sha: str, number: int | None, subject: str = "s") -> Candidate:
        pr = None
        if number is not None:
            pr = ResolvedPR(number, "title", f"https://github.com/canonical/snapd/pull/{number}", sha)
        return Candidate(sha=sha, subject=subject, pr=pr)

    def test_keeps_first_pr(self):
        out = dedupe_candidates(
            [
                self._cand("a" * 40, 10),
                self._cand("b" * 40, 10),
                self._cand("c" * 40, 11),
            ]
        )
        self.assertEqual([c.sha[0] for c in out], ["a", "c"])

    def test_unresolved_unique_by_sha(self):
        out = dedupe_candidates(
            [
                self._cand("a" * 40, None, "one"),
                self._cand("a" * 40, None, "one"),
                self._cand("b" * 40, None, "two"),
            ]
        )
        self.assertEqual([c.sha[0] for c in out], ["a", "b"])


class SummaryTest(unittest.TestCase):
    def test_conflict_includes_prefix(self):
        applied = Candidate(
            sha="1" * 40,
            subject="tests: a (#1)",
            pr=ResolvedPR(1, "tests: a", "https://github.com/canonical/snapd/pull/1", "1" * 40),
        )
        blocked = Candidate(
            sha="2" * 40,
            subject="tests: b (#2)",
            pr=ResolvedPR(2, "tests: b", "https://github.com/canonical/snapd/pull/2", "2" * 40),
        )
        remaining = Candidate(
            sha="3" * 40,
            subject="tests: c (#3)",
            pr=ResolvedPR(3, "tests: c", "https://github.com/canonical/snapd/pull/3", "3" * 40),
        )
        result = BranchResult(
            branch="release/2.77",
            fork="f" * 40,
            planned=[applied, blocked, remaining],
            applied=[applied],
            conflict=Conflict(
                sha="2" * 40,
                subject="tests: b (#2)",
                pr_number=2,
                pr_title="tests: b",
                pr_url="https://github.com/canonical/snapd/pull/2",
                files=["tests/foo"],
                conflicted=["tests/foo"],
                status="UU tests/foo",
                stderr="conflict",
            ),
        )
        text = format_branch_summary(result)
        self.assertIn("Cherry-picked (1)", text)
        self.assertIn("#1", text)
        self.assertIn("Blocked on:** #2", text)
        self.assertIn("#3", text)


if __name__ == "__main__":
    unittest.main()
