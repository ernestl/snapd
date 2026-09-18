# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

"""Label a pull request tests-only when every changed path is on the allowlist."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from .paths import is_tests_only

LABEL = "tests-only"


def _gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ,
    )
    return result.stdout


def pull_request_files(repo: str, number: int) -> list[str]:
    out = _gh(
        "api",
        "--paginate",
        f"repos/{repo}/pulls/{number}/files",
        "--jq",
        ".[].filename",
    )
    files = [line.strip() for line in out.splitlines() if line.strip()]
    # Include previous names of renames so a rename out of tests/ is mixed.
    prev = _gh(
        "api",
        "--paginate",
        f"repos/{repo}/pulls/{number}/files",
        "--jq",
        ".[] | select(.previous_filename != null) | .previous_filename",
    )
    files.extend(line.strip() for line in prev.splitlines() if line.strip())
    return files


def ensure_label(repo: str) -> None:
    subprocess.run(
        [
            "gh",
            "label",
            "create",
            LABEL,
            "--repo",
            repo,
            "--description",
            "All changed files are tests or test infrastructure",
            "--color",
            "0E8A16",
            "--force",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ,
    )


def pr_labels(repo: str, number: int) -> set[str]:
    out = _gh("pr", "view", str(number), "--repo", repo, "--json", "labels")
    data = json.loads(out)
    labels = data.get("labels") or []
    names = set()
    for item in labels:
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
    return names


def set_tests_only_label(repo: str, number: int, add: bool) -> None:
    ensure_label(repo)
    present = LABEL in pr_labels(repo, number)
    if add and not present:
        _gh("pr", "edit", str(number), "--repo", repo, "--add-label", LABEL)
        print(f"added label {LABEL} to {repo}#{number}", file=sys.stderr)
    elif not add and present:
        _gh("pr", "edit", str(number), "--repo", repo, "--remove-label", LABEL)
        print(f"removed label {LABEL} from {repo}#{number}", file=sys.stderr)
    else:
        print(
            f"label {LABEL} already {'present' if present else 'absent'} on {repo}#{number}",
            file=sys.stderr,
        )


def classify_pull_request(repo: str, number: int, apply_label: bool = True) -> bool:
    files = pull_request_files(repo, number)
    only = is_tests_only(files)
    print(f"files ({len(files)}): {', '.join(files[:40])}" + (" ..." if len(files) > 40 else ""))
    print(f"tests-only: {only}")
    if apply_label:
        set_tests_only_label(repo, number, only)
    return only
