# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

"""Select tests-only master commits to cherry-pick onto a release branch."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import gitutil
from .branch_point import find_branch_point
from .paths import is_tests_only
from .pr_resolve import GitHubClient, ResolvedPR, pr_number_from_subject

_RELEASE_REF = re.compile(r"^release/[0-9]+\.[0-9]+(\.[0-9]+)?$")


@dataclass
class Candidate:
    sha: str
    subject: str
    pr: ResolvedPR | None


def version_key(branch: str) -> tuple[int, ...]:
    version = branch.split("/", 1)[1]
    return tuple(int(part) for part in version.split("."))


def list_release_branches(cwd: str | None = None, prefix: str = "origin/") -> list[str]:
    """Return origin release/X.Y names without the remote prefix, version-sorted."""
    out = gitutil.git(
        "for-each-ref",
        "--format=%(refname:short)",
        f"refs/remotes/{prefix.rstrip('/')}/release",
        cwd=cwd,
        check=False,
    ).stdout
    names: list[str] = []
    remote = prefix.rstrip("/")
    for line in out.splitlines():
        name = line.strip()
        if name.startswith(f"{remote}/"):
            name = name[len(remote) + 1 :]
        if _RELEASE_REF.match(name):
            names.append(name)
    names.sort(key=version_key)
    return names


def newest_release_branches(count: int, cwd: str | None = None, prefix: str = "origin/") -> list[str]:
    names = list_release_branches(cwd=cwd, prefix=prefix)
    if count <= 0:
        raise ValueError(f"release-branch-count must be a positive integer, got: {count}")
    return names[-count:]


def commits_after_fork(fork: str, head: str, cwd: str | None = None) -> list[str]:
    """First-parent commits of head after fork, oldest first. Excludes merge commits."""
    out = gitutil.git(
        "log",
        "--first-parent",
        "--reverse",
        "--format=%H",
        f"{fork}..{head}",
        cwd=cwd,
    ).stdout
    shas = []
    for sha in out.splitlines():
        if not sha:
            continue
        if len(gitutil.commit_parents(sha, cwd=cwd)) > 1:
            continue
        shas.append(sha)
    return shas


def equivalent_on_upstream(upstream: str, head: str, limit: str, cwd: str | None = None) -> set[str]:
    """SHAs on head whose patch is already on upstream (git cherry '-')."""
    result = gitutil.git("cherry", "-v", upstream, head, limit, cwd=cwd, check=False)
    found: set[str] = set()
    for line in result.stdout.splitlines():
        if not line.startswith("- "):
            continue
        parts = line.split()
        if len(parts) >= 2:
            found.add(parts[1])
    return found


def prs_already_on_branch(
    fork: str,
    release_ref: str,
    cwd: str | None = None,
) -> set[int]:
    """PR numbers already present on the release branch after the original cut."""
    numbers: set[int] = set()
    for sha in commits_after_fork(fork, release_ref, cwd=cwd):
        subject = gitutil.commit_subject(sha, cwd=cwd)
        number = pr_number_from_subject(subject)
        if number is not None:
            numbers.add(number)
    return numbers


def select_candidates(
    master_ref: str,
    release_ref: str,
    github: GitHubClient,
    cwd: str | None = None,
) -> tuple[str, list[Candidate]]:
    """Return (fork_point, unique tests-only PRs not yet on the release branch)."""
    fork = find_branch_point(master_ref, release_ref, cwd=cwd)
    already_eq = equivalent_on_upstream(release_ref, master_ref, fork, cwd=cwd)
    already_prs = prs_already_on_branch(fork, release_ref, cwd=cwd)
    raw: list[Candidate] = []
    for sha in commits_after_fork(fork, master_ref, cwd=cwd):
        if gitutil.is_ancestor(sha, release_ref, cwd=cwd):
            continue
        if sha in already_eq:
            continue
        files = gitutil.commit_files(sha, cwd=cwd)
        if not is_tests_only(files):
            continue
        subject = gitutil.commit_subject(sha, cwd=cwd)
        pr = github.resolve_commit(sha, subject=subject, cwd=cwd)
        if pr is not None and pr.number in already_prs:
            continue
        raw.append(Candidate(sha=sha, subject=subject, pr=pr))
    return fork, dedupe_candidates(raw)


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Keep first-seen PR number; unresolved commits stay unique by SHA."""
    seen_prs: set[int] = set()
    seen_shas: set[str] = set()
    unique: list[Candidate] = []
    for cand in candidates:
        if cand.sha in seen_shas:
            continue
        if cand.pr is not None:
            if cand.pr.number in seen_prs:
                continue
            seen_prs.add(cand.pr.number)
        seen_shas.add(cand.sha)
        unique.append(cand)
    return unique
