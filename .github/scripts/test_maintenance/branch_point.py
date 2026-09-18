# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

"""Original fork point of a release branch vs master.

Port of ernestl/relnote relnote/equivalence.py find_branch_point:

Walk the release branch's first-parent chain newest-to-oldest and return
the first SHA that also appears on master's first-parent chain.

git merge-base is the latest merge-back, not the original cut. Release
history stays on the second parent of a release→master merge, so this
walk still finds the original cut after multiple merge-backs.
"""

from __future__ import annotations

from . import gitutil


def find_branch_point(master_ref: str, release_ref: str, cwd: str | None = None) -> str:
    master_first_parent = set(gitutil.first_parent_shas(master_ref, cwd=cwd))
    if not master_first_parent:
        raise RuntimeError(f"no first-parent history for {master_ref}")
    release_first_parent = gitutil.first_parent_shas(release_ref, cwd=cwd)
    if not release_first_parent:
        raise RuntimeError(f"no first-parent history for {release_ref}")
    for sha in release_first_parent:
        if sha in master_first_parent:
            return sha
    raise RuntimeError(
        f"cannot find original fork point of {release_ref} on {master_ref}"
    )
