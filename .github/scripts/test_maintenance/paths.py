# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

"""Classify changed paths as tests-only.

A change set is tests-only iff every path matches the allowlist. Mixed
changes (any production path) are not backported.
"""

from __future__ import annotations

import os
import re

_PKGTEST_DIR = re.compile(r"^[a-z0-9]+test$")
_ROOT_CHECK_PY = re.compile(r"^check-[^/]+\.py$")
_PACKAGING_TESTS = re.compile(r"^packaging/[^/]+/tests(/.*)?$")
_C_UNIT_TEST = re.compile(r"(.+-test\.c|unit-tests.*|test-utils.*)$")


def normalize_path(path: str) -> str:
    path = path.replace("\\", "/").strip()
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def is_tests_only_path(path: str) -> bool:
    """Return True if this single path is test or test-infrastructure."""
    path = normalize_path(path)
    if not path or path == ".":
        return False

    if path == "tests" or path.startswith("tests/"):
        return True
    if path in ("spread.yaml", "run-spread", "run-checks"):
        return True
    if path == "osutil/vfs/spread.yaml" or path.startswith("osutil/vfs/tests/"):
        return True
    if path.endswith("_test.go"):
        return True
    if path == "export_test.go" or path.endswith("/export_test.go"):
        return True
    if (
        path == "testdata"
        or path.startswith("testdata/")
        or "/testdata/" in path
        or path.endswith("/testdata")
    ):
        return True
    if path == "testutil" or path.startswith("testutil/"):
        return True
    if path == "testtime" or path.startswith("testtime/"):
        return True
    if path.startswith("cmd/") and (
        path == "cmd/test-driver" or _C_UNIT_TEST.search(os.path.basename(path))
    ):
        return True
    if _PACKAGING_TESTS.match(path):
        return True
    if path == "release-tools/test" or path.startswith("release-tools/test/"):
        return True
    if path.startswith(".github/"):
        return True
    if _ROOT_CHECK_PY.match(path):
        return True

    for part in path.split("/")[:-1]:
        if _PKGTEST_DIR.fullmatch(part):
            return True
    return False


def is_tests_only(paths: list[str]) -> bool:
    """Return True if paths is non-empty and every path is tests-only."""
    if not paths:
        return False
    return all(is_tests_only_path(p) for p in paths)
