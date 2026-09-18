# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

from __future__ import annotations

import os
import tempfile
import unittest

from test_maintenance.branch_point import find_branch_point
from test_maintenance.gitutil import git


class BranchPointTest(unittest.TestCase):
    def _commit(self, cwd: str, path: str, msg: str) -> str:
        full = os.path.join(cwd, path)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
        git("add", path, cwd=cwd)
        git("commit", "-m", msg, cwd=cwd)
        return git("rev-parse", "HEAD", cwd=cwd).stdout.strip()

    def test_original_cut_survives_merge_back(self):
        with tempfile.TemporaryDirectory() as cwd:
            git("init", "-b", "master", cwd=cwd)
            git("config", "user.email", "t@t.test", cwd=cwd)
            git("config", "user.name", "t", cwd=cwd)
            cut = self._commit(cwd, "README", "release: 2.77")
            git("branch", "release/2.77", cwd=cwd)
            self._commit(cwd, "product.go", "feat: product")
            git("checkout", "release/2.77", cwd=cwd)
            self._commit(cwd, "tests/task.yaml", "tests: fix on release")
            git("checkout", "master", cwd=cwd)
            git("merge", "--no-ff", "-m", "Merge release/2.77", "release/2.77", cwd=cwd)
            self._commit(cwd, "tests/other.yaml", "tests: later on master")

            fork = find_branch_point("master", "release/2.77", cwd=cwd)
            self.assertEqual(fork, cut)
            merge_base = git("merge-base", "master", "release/2.77", cwd=cwd).stdout.strip()
            self.assertNotEqual(merge_base, cut)

    def test_missing_history(self):
        with tempfile.TemporaryDirectory() as cwd:
            git("init", "-b", "master", cwd=cwd)
            with self.assertRaises(RuntimeError):
                find_branch_point("master", "release/2.77", cwd=cwd)


if __name__ == "__main__":
    unittest.main()
