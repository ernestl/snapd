# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

"""Cherry-pick selected tests-only commits onto a release branch."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import gitutil
from .gitutil import GitError
from .select import Candidate


@dataclass
class Conflict:
    sha: str
    subject: str
    pr_number: int | None
    pr_title: str
    pr_url: str
    files: list[str]
    conflicted: list[str]
    status: str
    stderr: str


@dataclass
class BranchResult:
    branch: str
    fork: str
    planned: list[Candidate]
    applied: list[Candidate] = field(default_factory=list)
    skipped_empty: list[Candidate] = field(default_factory=list)
    conflict: Conflict | None = None
    pushed: bool = False
    dry_run: bool = False
    error: str = ""

    @property
    def failed(self) -> bool:
        return self.conflict is not None or bool(self.error)


def _is_empty_cherry_pick(result) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return "empty" in text or "nothing to commit" in text


def _in_cherry_pick(cwd: str | None) -> bool:
    git_dir = gitutil.git("rev-parse", "--git-dir", cwd=cwd).stdout.strip()
    root = cwd or "."
    return os.path.exists(os.path.join(root, git_dir, "CHERRY_PICK_HEAD"))


def _conflicted_paths(cwd: str | None) -> list[str]:
    out = gitutil.git("diff", "--name-only", "--diff-filter=U", cwd=cwd, check=False).stdout
    return [line for line in out.splitlines() if line]


def cherry_pick_one(sha: str, cwd: str | None = None) -> None:
    result = gitutil.git("cherry-pick", "-x", sha, cwd=cwd, check=False)
    if result.returncode == 0:
        return
    if _is_empty_cherry_pick(result):
        if _in_cherry_pick(cwd):
            gitutil.git("cherry-pick", "--skip", cwd=cwd, check=False)
        raise EmptyCherryPick(sha)
    if _in_cherry_pick(cwd):
        conflicted = _conflicted_paths(cwd)
        status = gitutil.git("status", cwd=cwd, check=False).stdout
        gitutil.git("cherry-pick", "--abort", cwd=cwd, check=False)
        raise CherryPickConflict(sha, conflicted, status, result.stderr)
    raise GitError(("cherry-pick", "-x", sha), result)


class EmptyCherryPick(RuntimeError):
    def __init__(self, sha: str):
        self.sha = sha
        super().__init__(f"cherry-pick of {sha} is empty")


class CherryPickConflict(RuntimeError):
    def __init__(self, sha: str, conflicted: list[str], status: str, stderr: str):
        self.sha = sha
        self.conflicted = conflicted
        self.status = status
        self.stderr = stderr
        super().__init__(f"cherry-pick of {sha} conflicted")


def checkout_release(branch: str, cwd: str | None = None, remote: str = "origin") -> None:
    gitutil.git("checkout", "-B", branch, f"{remote}/{branch}", cwd=cwd)


def push_release(branch: str, cwd: str | None = None, remote: str = "origin") -> None:
    gitutil.git("push", remote, f"HEAD:refs/heads/{branch}", cwd=cwd)


def apply_candidates(
    branch: str,
    fork: str,
    planned: list[Candidate],
    cwd: str | None = None,
    dry_run: bool = False,
    remote: str = "origin",
) -> BranchResult:
    result = BranchResult(branch=branch, fork=fork, planned=planned, dry_run=dry_run)
    if dry_run:
        return result
    checkout_release(branch, cwd=cwd, remote=remote)
    for cand in planned:
        try:
            cherry_pick_one(cand.sha, cwd=cwd)
        except EmptyCherryPick:
            result.skipped_empty.append(cand)
            continue
        except CherryPickConflict as err:
            files = gitutil.commit_files(cand.sha, cwd=cwd)
            result.conflict = Conflict(
                sha=cand.sha,
                subject=cand.subject,
                pr_number=None if cand.pr is None else cand.pr.number,
                pr_title="" if cand.pr is None else cand.pr.title,
                pr_url="" if cand.pr is None else cand.pr.url,
                files=files,
                conflicted=err.conflicted,
                status=err.status,
                stderr=err.stderr,
            )
            break
        except GitError as err:
            result.error = str(err)
            break
        result.applied.append(cand)

    # Push the successful prefix (full list or up to the conflict).
    if result.applied:
        try:
            push_release(branch, cwd=cwd, remote=remote)
            result.pushed = True
        except GitError as err:
            result.error = result.error or f"push failed: {err}"
            result.pushed = False
    return result
