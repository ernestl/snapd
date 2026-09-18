# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

"""Thin git subprocess helpers."""

from __future__ import annotations

import subprocess
from typing import Sequence


class GitError(RuntimeError):
    def __init__(self, args: Sequence[str], result: subprocess.CompletedProcess[str]):
        self.args = list(args)
        self.result = result
        super().__init__(
            f"git {' '.join(args)} exited {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )


def git(
    *args: str,
    cwd: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitError(args, result)
    return result


def first_parent_shas(ref: str, cwd: str | None = None) -> list[str]:
    """Newest-first first-parent history of ref."""
    out = git("log", "--first-parent", "--format=%H", ref, cwd=cwd).stdout
    return [line for line in out.splitlines() if line]


def is_ancestor(maybe_ancestor: str, descendant: str, cwd: str | None = None) -> bool:
    result = git("merge-base", "--is-ancestor", maybe_ancestor, descendant, cwd=cwd, check=False)
    return result.returncode == 0


def commit_parents(sha: str, cwd: str | None = None) -> list[str]:
    out = git("log", "-1", "--format=%P", sha, cwd=cwd).stdout.strip()
    if not out:
        return []
    return out.split()


def commit_subject(sha: str, cwd: str | None = None) -> str:
    return git("log", "-1", "--format=%s", sha, cwd=cwd).stdout.strip()


def commit_body(sha: str, cwd: str | None = None) -> str:
    return git("log", "-1", "--format=%b", sha, cwd=cwd).stdout


def commit_files(sha: str, cwd: str | None = None) -> list[str]:
    out = git("diff-tree", "--no-commit-id", "--name-only", "-r", sha, cwd=cwd).stdout
    return [line for line in out.splitlines() if line]


def short_sha(sha: str, cwd: str | None = None) -> str:
    return git("rev-parse", "--short", sha, cwd=cwd).stdout.strip()
