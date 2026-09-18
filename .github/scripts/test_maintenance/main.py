# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

"""Daily test-maintenance backports onto the newest release branches."""

from __future__ import annotations

import argparse
import os
import sys

from . import gitutil
from .apply import BranchResult, apply_candidates
from .pr_resolve import GitHubClient
from .select import newest_release_branches, select_candidates
from .summary import format_branch_summary, format_conflict_log


def _append_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        print(text)
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)
        if not text.endswith("\n"):
            fh.write("\n")
        fh.write("\n")


def _parse_count(raw: str) -> int:
    if not raw.isdigit() or int(raw) < 1:
        raise SystemExit(f"release-branch-count must be a positive integer, got: {raw}")
    return int(raw)


def cmd_backport(args: argparse.Namespace) -> int:
    cwd = args.cwd or os.getcwd()
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY") or "canonical/snapd"
    count = _parse_count(str(args.release_branch_count))
    github = GitHubClient(repo)
    remote = args.remote
    gitutil.git("config", "user.name", os.environ.get("GIT_COMMITTER_NAME", "snapd-test-maintenance[bot]"), cwd=cwd, check=False)
    gitutil.git("config", "user.email", os.environ.get("GIT_COMMITTER_EMAIL", "snapd-test-maintenance[bot]@users.noreply.github.com"), cwd=cwd, check=False)
    gitutil.git(
        "fetch",
        "--prune",
        remote,
        "+refs/heads/*:refs/remotes/{0}/*".format(remote),
        cwd=cwd,
    )
    master_ref = f"{remote}/master"

    try:
        branches = newest_release_branches(count, cwd=cwd, prefix=f"{remote}/")
    except ValueError as err:
        raise SystemExit(str(err)) from err
    if not branches:
        print("no release/[0-9]+.[0-9]+ branches found", file=sys.stderr)
        return 1

    header = [
        "# Test maintenance",
        "",
        f"Repo: `{repo}`",
        f"Release branches: {', '.join(f'`{b}`' for b in branches)}",
        "",
    ]
    _append_summary("\n".join(header))

    failed = False
    for branch in branches:
        release_ref = f"{remote}/{branch}"
        print(f"== {branch} ==", file=sys.stderr)
        try:
            fork, planned = select_candidates(master_ref, release_ref, github, cwd=cwd)
        except Exception as err:  # noqa: BLE001 — report and continue other branches
            result = BranchResult(branch=branch, fork="", planned=[], error=str(err))
            failed = True
            _append_summary(format_branch_summary(result))
            print(f"cannot select candidates for {branch}: {err}", file=sys.stderr)
            continue
        result = apply_candidates(
            branch,
            fork,
            planned,
            cwd=cwd,
            dry_run=args.dry_run,
            remote=remote,
        )
        _append_summary(format_branch_summary(result))
        if result.conflict is not None:
            print(format_conflict_log(result), file=sys.stderr)
            print(
                f"::error::CHERRY-PICK CONFLICT: {branch} blocked on {result.conflict.sha}",
                file=sys.stderr,
            )
        if result.failed:
            failed = True
    return 1 if failed else 0


def cmd_label(args: argparse.Namespace) -> int:
    from .label import classify_pull_request

    repo = args.repo or os.environ.get("GITHUB_REPOSITORY") or "canonical/snapd"
    only = classify_pull_request(repo, args.pr, apply_label=not args.no_label)
    return 0 if only or args.no_fail else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    backport = sub.add_parser("backport", help="cherry-pick tests-only commits onto release branches")
    backport.add_argument("--cwd", default="")
    backport.add_argument("--repo", default="")
    backport.add_argument("--remote", default="origin")
    backport.add_argument(
        "--release-branch-count",
        default=os.environ.get("RELEASE_BRANCH_COUNT", "3"),
    )
    backport.add_argument("--dry-run", action="store_true")
    backport.set_defaults(func=cmd_backport)

    label = sub.add_parser("label-pr", help="classify a pull request and set the tests-only label")
    label.add_argument("--pr", type=int, required=True)
    label.add_argument("--repo", default="")
    label.add_argument("--no-label", action="store_true", help="classify only, do not change labels")
    label.add_argument(
        "--no-fail",
        action="store_true",
        help="exit 0 even when the PR is not tests-only",
    )
    label.set_defaults(func=cmd_label)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
