#!/usr/bin/env python3
"""Report whether a pull request changes classic snapd systemd units.

The input is a GitHub pull request link. gh reads the changed files.
A checkout is not required, because the decision is the path. The units
are the ones classic packaging uses to start snapd. Ubuntu Core units
are not included. A file under the spread tree, a testdata or test
directory, or a Go unit test is not a systemd service. This command
prints the decision and exits 0. It does not fail a CI job, and it
does not tick a template box.

Systemd services is yes when at least one changed file is one of those
units.
"""

# Hyphenated filename; this is a script, not a library. The CLI shape is
# shared with the other release-tools scripts on purpose.
# pylint: disable=invalid-name,duplicate-code

import argparse
import json
import re
import subprocess
import sys
from typing import NamedTuple

PROG_NAME = "pr-systemd-services.py"

PR_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"pull/(?P<number>[0-9]+)"
    r"(?:/(?:files|commits|checks))?"
    r"/?(?:\?[^#]*)?(?:#.*)?$"
)

SYSTEMD = "systemd"
OTHER = "other"

# Classic packaging units from packaging/README.md. The .in template of
# a generated unit is the same unit.
_CLASSIC_UNITS = frozenset(
    {
        "snapd.service",
        "snapd.socket",
        "snapd.apparmor.service",
        "snapd.mounts.target",
        "snapd.mounts-pre.target",
        "snapd.seeded.service",
        "snapd.session-agent.service",
        "snapd.session-agent.socket",
    }
)


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


def _parts(path):
    return [part for part in path.split("/") if part and part != "."]


def _excluded(path):
    """True when the path is a test, not a systemd unit."""
    parts = _parts(path)
    if not parts:
        return False
    if parts[0] == "tests" or "testdata" in parts or "test" in parts:
        return True
    return parts[-1].endswith("_test.go")


def _unit_name(path):
    """Return the unit basename, without a single .in suffix."""
    name = _parts(path)[-1]
    if name.endswith(".in"):
        return name[: -len(".in")]
    return name


def is_systemd_service(path):
    """True for a classic snapd bootstrap unit, including its .in template."""
    parts = _parts(path)
    if _excluded(path) or not parts:
        return False
    return _unit_name(path) in _CLASSIC_UNITS


def file_kinds(changed):
    """Return the kinds touched by one changed file, including a rename.

    A rename contributes every distinct kind of its two paths. other is
    included when one side is not a classic unit, so that side is still
    listed.
    """
    found = set()
    found.add(_kind(changed.path))
    if changed.previous:
        found.add(_kind(changed.previous))
    return found


def _kind(path):
    if is_systemd_service(path):
        return SYSTEMD
    return OTHER


def systemd_decision(changed):
    """Return yes when any changed file is a classic systemd unit."""
    for item in changed:
        if SYSTEMD in file_kinds(item):
            return "yes"
    return "no"


def _paths_for(changed, kind):
    """Return paths of this kind, one side of a rename at a time."""
    shown = set()
    for item in changed:
        if _kind(item.path) == kind:
            shown.add(item.path)
        if item.previous and _kind(item.previous) == kind:
            shown.add(item.previous)
    return sorted(shown)


def print_result(link, changed, out=None):
    """Print the systemd decision, then the details.

    The first line is always "Systemd services: <yes or no>" so a caller
    can read the headline without parsing the rest of the report.
    """
    if out is None:
        out = sys.stdout
    counts = {SYSTEMD: 0, OTHER: 0}
    for item in changed:
        for kind in file_kinds(item):
            counts[kind] += 1
    print(f"Systemd services: {systemd_decision(changed)}", file=out)
    print(file=out)
    print("Details:", file=out)
    print(f"Pull request: {link}", file=out)
    print(f"Changed files: {len(changed)}", file=out)
    print(f"Systemd services: {counts[SYSTEMD]}", file=out)
    print(f"Other files: {counts[OTHER]}", file=out)
    _print_paths("Systemd services:", _paths_for(changed, SYSTEMD), out)
    _print_paths("Other files:", _paths_for(changed, OTHER), out)


def _print_paths(heading, paths, out):
    if not paths:
        return
    print(heading, file=out)
    for path in paths:
        print(path, file=out)


def print_help(out=None):
    """Print usage and the systemd rule."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (("  -h, --help", "Help for pr-systemd-services"),)
    width = max(len(name) for name, _desc in flags)
    print("Report whether a pull request changes classic systemd units.", file=out)
    print(file=out)
    print("The units are the ones classic packaging uses to start snapd.", file=out)
    print("Ubuntu Core units and test files are not included. The command", file=out)
    print("prints the decision and exits 0. It does not fail a build.", file=out)
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

    gh api --paginate prints one JSON array per page. A rename includes
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
    """CLI entry: print whether the pull request changes classic units."""
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
