# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

from __future__ import annotations

import os
import tempfile
import unittest

from test_maintenance.apply import apply_candidates, cherry_pick_one, EmptyCherryPick
from test_maintenance.gitutil import git
from test_maintenance.pr_resolve import GitHubClient, ResolvedPR
from test_maintenance.select import Candidate, newest_release_branches, select_candidates


def _init(cwd: str) -> None:
    git("init", "-b", "master", cwd=cwd)
    git("config", "user.email", "t@t.test", cwd=cwd)
    git("config", "user.name", "t", cwd=cwd)


def _commit(cwd: str, path: str, msg: str, contents: str | None = None) -> str:
    full = os.path.join(cwd, path)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    with open(full, "a", encoding="utf-8") as fh:
        fh.write((contents if contents is not None else msg) + "\n")
    git("add", path, cwd=cwd)
    git("commit", "-m", msg, cwd=cwd)
    return git("rev-parse", "HEAD", cwd=cwd).stdout.strip()


class _FakeGitHub(GitHubClient):
    def __init__(self, mapping: dict[str, ResolvedPR | None]):
        super().__init__("canonical/snapd", token="x", api_get=lambda path: (_ for _ in ()).throw(AssertionError(path)))
        self._mapping = mapping

    def resolve_commit(self, sha: str, subject: str = "", cwd: str | None = None) -> ResolvedPR | None:
        if sha in self._mapping:
            return self._mapping[sha]
        number = None
        if "(#" in subject:
            number = int(subject.rsplit("#", 1)[-1].rstrip(")"))
        if number is None:
            return None
        return ResolvedPR(number, subject, f"https://github.com/canonical/snapd/pull/{number}", sha)


class SelectApplyTest(unittest.TestCase):
    def test_newest_release_branches(self):
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as bare:
            _init(cwd)
            git("init", "--bare", cwd=bare)
            _commit(cwd, "README", "base")
            git("branch", "release/2.76", cwd=cwd)
            git("branch", "release/2.77", cwd=cwd)
            git("branch", "release/2.78", cwd=cwd)
            git("branch", "release/not-a-version", cwd=cwd)
            git("remote", "add", "origin", bare, cwd=cwd)
            git("push", "origin", "--all", cwd=cwd)
            git("fetch", "origin", cwd=cwd)
            names = newest_release_branches(2, cwd=cwd, prefix="origin/")
            self.assertEqual(names, ["release/2.77", "release/2.78"])

    def test_select_tests_only_skips_product(self):
        with tempfile.TemporaryDirectory() as cwd:
            _init(cwd)
            cut = _commit(cwd, "README", "cut")
            git("branch", "release/2.77", cwd=cwd)
            product = _commit(cwd, "daemon/daemon.go", "daemon: product")
            testfix = _commit(cwd, "tests/foo/task.yaml", "tests: fix (#10)")
            github = _FakeGitHub(
                {
                    testfix: ResolvedPR(10, "tests: fix", "https://github.com/canonical/snapd/pull/10", testfix),
                }
            )
            fork, cands = select_candidates("master", "release/2.77", github, cwd=cwd)
            self.assertEqual(fork, cut)
            self.assertEqual([c.sha for c in cands], [testfix])
            self.assertNotIn(product, [c.sha for c in cands])

    def test_cherry_pick_conflict_keeps_prefix(self):
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as bare:
            _init(cwd)
            git("init", "--bare", cwd=bare)
            _commit(cwd, "tests/foo.yaml", "base", "line1\n")
            git("branch", "release/2.77", cwd=cwd)
            a = _commit(cwd, "tests/a.yaml", "tests: a (#1)", "a\n")
            git("checkout", "release/2.77", cwd=cwd)
            _commit(cwd, "tests/foo.yaml", "tests: diverge", "line1\nrelease-side\n")
            git("checkout", "master", cwd=cwd)
            b = _commit(cwd, "tests/foo.yaml", "tests: b (#2)", "line1\nmaster-side\n")
            git("remote", "add", "origin", bare, cwd=cwd)
            git("push", "origin", "master:master", "release/2.77:release/2.77", cwd=cwd)
            git("fetch", "origin", cwd=cwd)
            planned = [
                Candidate(a, "tests: a (#1)", ResolvedPR(1, "tests: a", "u", a)),
                Candidate(b, "tests: b (#2)", ResolvedPR(2, "tests: b", "u", b)),
            ]
            result = apply_candidates("release/2.77", "unused", planned, cwd=cwd, dry_run=False, remote="origin")
            self.assertEqual([c.sha for c in result.applied], [a])
            self.assertIsNotNone(result.conflict)
            self.assertEqual(result.conflict.sha, b)
            self.assertTrue(result.pushed)
            self.assertTrue(git("log", "-1", "--format=%s", cwd=cwd).stdout.startswith("tests: a"))

    def test_empty_cherry_pick(self):
        with tempfile.TemporaryDirectory() as cwd:
            _init(cwd)
            _commit(cwd, "tests/foo.yaml", "base", "same\n")
            git("branch", "release/2.77", cwd=cwd)
            sha = _commit(cwd, "tests/foo.yaml", "tests: already", "same\nmore\n")
            git("checkout", "release/2.77", cwd=cwd)
            git("cherry-pick", sha, cwd=cwd)
            git("checkout", "master", cwd=cwd)
            with self.assertRaises(EmptyCherryPick):
                cherry_pick_one(sha, cwd=cwd)


if __name__ == "__main__":
    unittest.main()
