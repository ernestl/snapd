#!/usr/bin/env python3
"""Report whether a pull request changes only test implementation.

The input is a GitHub pull request link. gh reads the changed files.
A checkout is not required, because the decision is the path. Suite
configuration, such as spread.yaml, is counted apart from the tests.
Unit tests are tests. This command prints the decision and exits 0.
It does not fail a CI job, and it does not tick a template box.

Test only is yes when every changed file is test implementation.
A pull request that changes no files, or that changes suite
configuration or any other path, is not test-only.
"""

# Hyphenated filename; this is a script, not a library. The CLI shape is
# shared with the other release-tools scripts on purpose.
# pylint: disable=invalid-name,duplicate-code

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from typing import NamedTuple

PROG_NAME = "pr-test-only.py"

PR_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"pull/(?P<number>[0-9]+)"
    r"(?:/(?:files|commits|checks))?"
    r"/?(?:\?[^#]*)?(?:#.*)?$"
)

# Path components that hold test implementation, unless the file itself
# is suite configuration.
_TEST_COMPONENTS = {"test", "tests", "testdata"}

# Confine unit-test runner. These are tests, not suite configuration.
_C_HARNESS = {
    "test-utils.c",
    "test-utils.h",
    "unit-tests.c",
    "unit-tests.h",
    "unit-tests-main.c",
}

# Autopkgtest metadata. Only when the parent directory is tests, so a
# package control file is not test configuration.
_APT_CONFIG = {"control", "testconfig.json"}


class UsageError(Exception):
    """Invalid CLI usage; main() prints this and exits 2."""


class PullRequest(NamedTuple):
    """A GitHub pull request identified by its link."""

    owner: str
    repo: str
    number: str

    @property
    def slug(self):
        """owner/repo, as gh --repo expects it."""
        return f"{self.owner}/{self.repo}"


class ChangedFile(NamedTuple):
    """One changed path, and the previous path when the file was renamed."""

    path: str
    previous: str


class Classified(NamedTuple):
    """A changed file labeled test, configuration, or other."""

    kind: str
    shown: str


def path_kind(path):
    """Return test, configuration, or other for one repository path."""
    parts = [part for part in path.split("/") if part and part != "."]
    if not parts:
        return "other"
    name = parts[-1]
    parent = parts[-2] if len(parts) > 1 else ""
    if _is_configuration(name, parent):
        return "configuration"
    if _is_test_name(name) or any(part in _TEST_COMPONENTS for part in parts):
        return "test"
    return "other"


def _is_configuration(name, parent):
    """True for suite config that sits beside the tests."""
    if name == "spread.yaml":
        return True
    return parent == "tests" and name in _APT_CONFIG


def _is_test_name(name):
    """True for a unit test or the confine unit-test harness."""
    if name.endswith("_test.go"):
        return True
    if name.endswith(("-test.c", "-test.h")):
        return True
    return name in _C_HARNESS


def classify_file(changed):
    """Label one changed file, using the stricter side of a rename.

    If either path is other, the file is other. Otherwise if either path
    is test configuration, the file is configuration. Otherwise it is a
    test. shown is the path that explains a configuration or other label.
    """
    current = path_kind(changed.path)
    if not changed.previous:
        return Classified(current, changed.path)
    previous = path_kind(changed.previous)
    if "other" in (current, previous):
        shown = changed.path if current == "other" else changed.previous
        return Classified("other", shown)
    if "configuration" in (current, previous):
        shown = changed.path if current == "configuration" else changed.previous
        return Classified("configuration", shown)
    return Classified("test", changed.path)


def test_only(classified):
    """Return yes when every file is test implementation."""
    if not classified:
        return "no"
    if all(item.kind == "test" for item in classified):
        return "yes"
    return "no"


def _contract():
    """Load review.py. The hyphenated scripts cannot import it by name."""
    name = "snapd_release_review"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def review(pr):
    """Return the test-only decision. No label and no findings."""
    changed = pull_request_files(pr)
    classified = [classify_file(item) for item in changed]
    fact = f"Test only: {test_only(classified)}"
    return _contract().AreaReview("test-only", (fact,), (), ())


def print_result(link, changed, out=None):
    """Print the test-only decision, then the details.

    The first line is always "Test only: <yes or no>" so a caller can
    read the headline without parsing the rest of the report.
    """
    if out is None:
        out = sys.stdout
    classified = [classify_file(item) for item in changed]
    configuration = [item.shown for item in classified if item.kind == "configuration"]
    others = [item.shown for item in classified if item.kind == "other"]
    tests = sum(1 for item in classified if item.kind == "test")
    print(f"Test only: {test_only(classified)}", file=out)
    print(file=out)
    print("Details:", file=out)
    print(f"Pull request: {link}", file=out)
    print(f"Changed files: {len(changed)}", file=out)
    print(f"Tests: {tests}", file=out)
    print(f"Test configuration: {len(configuration)}", file=out)
    print(f"Other files: {len(others)}", file=out)
    _print_paths("Test configuration:", configuration, out)
    _print_paths("Other files:", others, out)


def _print_paths(heading, paths, out):
    if not paths:
        return
    print(heading, file=out)
    for path in sorted(paths):
        print(path, file=out)


def print_help(out=None):
    """Print usage and the test-only rule."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (("  -h, --help", "Help for pr-test-only"),)
    width = max(len(name) for name, _desc in flags)
    print("Report whether a pull request changes only tests.", file=out)
    print(file=out)
    print("Unit tests and spread tests count as tests. Suite configuration,", file=out)
    print("such as spread.yaml, does not. The command prints the decision", file=out)
    print("and exits 0. It does not fail a build.", file=out)
    print(file=out)
    print("Usage:", file=out)
    print(f"  {prog} <pull-request>", file=out)
    print(file=out)
    print("Examples:", file=out)
    print(f"  {prog} https://github.com/canonical/snapd/pull/17718", file=out)
    print(file=out)
    print("Flags:", file=out)
    for name, desc in flags:
        print(f"{name.ljust(width)}  {desc}", file=out)


def parse_arguments(argv=None):
    """Parse argv. Unknown flags raise UsageError."""
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("link", nargs="?")
    parser.add_argument("-h", "--help", action="store_true")
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        token = unknown[0]
        if token.startswith("-"):
            raise UsageError(f"unknown flag: {token}")
        raise UsageError(f'unknown command "{token}" for "{PROG_NAME}"')
    return args


def parse_pull_request(link):
    """Return a PullRequest for a GitHub pull request link."""
    match = PR_RE.match((link or "").strip())
    if not match:
        raise UsageError(f"invalid pull request link: {link}")
    return PullRequest(match.group("owner"), match.group("repo"), match.group("number"))


def parse_changed_files(text):
    """Return changed files from one or more gh JSON documents.

    gh api --paginate prints one JSON array per page. gh pr view --json
    files prints an object with a files list. A rename includes
    previous_filename or previousFilename.
    """
    raw = text.strip()
    if not raw:
        return []
    decoder = json.JSONDecoder()
    files = []
    idx = 0
    length = len(raw)
    while idx < length:
        while idx < length and raw[idx].isspace():
            idx += 1
        if idx >= length:
            break
        try:
            data, end = decoder.raw_decode(raw, idx)
        except json.JSONDecodeError as err:
            raise RuntimeError(f"cannot read pull request files: {err}") from err
        idx = end
        files.extend(_files_from_payload(data))
    return files


def _files_from_payload(data):
    if isinstance(data, dict):
        data = data.get("files")
    if not isinstance(data, list):
        raise RuntimeError("cannot read pull request files")
    files = []
    for item in data:
        if not isinstance(item, dict):
            raise RuntimeError("cannot read pull request files")
        path = item.get("path") or item.get("filename") or ""
        if not path:
            raise RuntimeError("cannot read pull request files")
        previous = item.get("previousFilename") or item.get("previous_filename") or ""
        files.append(ChangedFile(path, previous))
    return files


def _capture(command, cwd=None):
    """Run command and return stdout. Raise RuntimeError on failure."""
    try:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except OSError as err:
        raise RuntimeError(f"cannot run {command[0]}: {err}") from err
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"{command[0]} failed"
        raise RuntimeError(f"cannot run {command[0]}: {detail}")
    return proc.stdout


def pull_request_files(pr):
    """Return the changed files of the pull request from gh.

    The files API includes previous_filename when a file was renamed.
    """
    raw = _capture(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{pr.slug}/pulls/{pr.number}/files",
        ]
    )
    return parse_changed_files(raw)


def _fail_usage(err):
    print(f"Error: {err}", file=sys.stderr)
    print(f"Run '{PROG_NAME} --help' for usage.", file=sys.stderr)
    return 2


def main(argv=None):
    """CLI entry: print whether the pull request changes only tests."""
    if argv is None:
        argv = sys.argv[1:]
    try:
        args = parse_arguments(argv)
    except UsageError as err:
        return _fail_usage(err)

    if args.help:
        print_help()
        return 0

    if not args.link:
        print_help()
        return 2

    try:
        pr = parse_pull_request(args.link)
        changed = pull_request_files(pr)
    except UsageError as err:
        return _fail_usage(err)
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1

    print_result(args.link, changed)
    return 0


def cli(argv=None):
    """Run main() and turn a usage or read failure into an exit status."""
    return main(argv)


if __name__ == "__main__":
    sys.exit(cli())
