#!/usr/bin/env python3
"""Report whether a pull request changes packaging, and which kind.

The input is a GitHub pull request link. gh reads the changed files.
A checkout is not required, because the decision is the path. The kinds
are snap, Ubuntu deb, cross-distro, and vendoring. A file under the
spread tree, a testdata or test directory, or a Go unit test is not
packaging. This command prints the decision and exits 0. It does not
fail a CI job, and it does not tick a template box.

Packaging is yes when at least one changed file is one of those kinds.
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

PROG_NAME = "pr-packaging.py"

PR_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"pull/(?P<number>[0-9]+)"
    r"(?:/(?:files|commits|checks))?"
    r"/?(?:\?[^#]*)?(?:#.*)?$"
)

SNAP = "snap"
UBUNTU = "ubuntu deb"
CROSS = "cross-distro"
VENDOR = "vendoring"
OTHER = "other"

# Printed under Details, in this order. The heading is the label plus a colon.
_KIND_LABELS = (
    (SNAP, "Snap"),
    (UBUNTU, "Ubuntu deb"),
    (CROSS, "Cross-distro"),
    (VENDOR, "Vendoring"),
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
    """True when the path is a test, not packaging."""
    parts = _parts(path)
    if not parts:
        return False
    if parts[0] == "tests" or "testdata" in parts or "test" in parts:
        return True
    return parts[-1].endswith("_test.go")


def path_kind(path):
    """Return snap, ubuntu deb, cross-distro, vendoring, or other."""
    parts = _parts(path)
    if _excluded(path) or not parts:
        return OTHER
    kind = _packaging_kind(parts)
    if kind:
        return kind
    return OTHER


def _packaging_kind(parts):
    """Return the first packaging kind that matches, or an empty string."""
    if _is_vendoring(parts):
        return VENDOR
    if _is_snap(parts):
        return SNAP
    if _is_ubuntu_deb(parts):
        return UBUNTU
    if parts[0] == "packaging":
        return CROSS
    return ""


def _is_vendoring(parts):
    """True for a vendored tree or the root module files."""
    if "vendor" in parts:
        return True
    return parts in (["go.mod"], ["go.sum"])


def _is_snap(parts):
    """True for the snap build under build-aux/snap."""
    return len(parts) >= 2 and parts[0] == "build-aux" and parts[1] == "snap"


def _is_ubuntu_deb(parts):
    """True for Ubuntu package packaging and core-initrd debian packaging."""
    if parts[0] == "packaging" and len(parts) > 1 and parts[1].startswith("ubuntu-"):
        return True
    return parts[0] == "core-initrd" and "debian" in parts[1:]


def file_kinds(changed):
    """Return the kinds touched by one changed file, including a rename.

    A rename contributes every distinct kind of its two paths. other is
    included when one side is not packaging, so that side is still listed.
    """
    found = {path_kind(changed.path)}
    if changed.previous:
        found.add(path_kind(changed.previous))
    return found


def packaging_decision(changed):
    """Return yes when any changed file is packaging."""
    for item in changed:
        if any(kind != OTHER for kind in file_kinds(item)):
            return "yes"
    return "no"


def _shown_path(kind, path):
    """Collapse a vendored file to its vendor directory."""
    if kind != VENDOR:
        return path
    parts = _parts(path)
    if "vendor" not in parts:
        return path
    index = parts.index("vendor")
    return "/".join(parts[: index + 1]) + "/"


def _paths_for(changed, kind):
    """Return display paths of this kind, one side of a rename at a time."""
    shown = set()
    for item in changed:
        if path_kind(item.path) == kind:
            shown.add(_shown_path(kind, item.path))
        if item.previous and path_kind(item.previous) == kind:
            shown.add(_shown_path(kind, item.previous))
    return sorted(shown)


def print_result(link, changed, out=None):
    """Print the packaging decision, then the details.

    The first line is always "Packaging: <yes or no>" so a caller can
    read the headline without parsing the rest of the report.
    """
    if out is None:
        out = sys.stdout
    counts = {SNAP: 0, UBUNTU: 0, CROSS: 0, VENDOR: 0, OTHER: 0}
    for item in changed:
        for kind in file_kinds(item):
            counts[kind] += 1
    print(f"Packaging: {packaging_decision(changed)}", file=out)
    print(file=out)
    print("Details:", file=out)
    print(f"Pull request: {link}", file=out)
    print(f"Changed files: {len(changed)}", file=out)
    print(f"Snap: {counts[SNAP]}", file=out)
    print(f"Ubuntu deb: {counts[UBUNTU]}", file=out)
    print(f"Cross-distro: {counts[CROSS]}", file=out)
    print(f"Vendoring: {counts[VENDOR]}", file=out)
    print(f"Other files: {counts[OTHER]}", file=out)
    for kind, label in _KIND_LABELS:
        _print_paths(f"{label}:", _paths_for(changed, kind), out)
    _print_paths("Other files:", _paths_for(changed, OTHER), out)


def _print_paths(heading, paths, out):
    if not paths:
        return
    print(heading, file=out)
    for path in paths:
        print(path, file=out)


def print_help(out=None):
    """Print usage and the packaging rule."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (("  -h, --help", "Help for pr-packaging"),)
    width = max(len(name) for name, _desc in flags)
    print("Report whether a pull request changes packaging.", file=out)
    print(file=out)
    print("The kinds are snap, Ubuntu deb, cross-distro, and vendoring.", file=out)
    print("Test files are not packaging. The command prints the decision", file=out)
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
    """CLI entry: print whether the pull request changes packaging."""
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
