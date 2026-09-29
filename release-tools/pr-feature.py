#!/usr/bin/env python3
"""Report whether a pull request adds a feature name and description.

The input is a GitHub pull request link. gh reads release-tools/features.yaml
at the base and head commits. A checkout is not required. The command
does not read the feature field in the pull request body. It prints the
decision and exits 0. It does not fail a CI job, and it does not tick a
template box.

Feature is yes when at least one name is new on the head and that entry
has a description.
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

PROG_NAME = "pr-feature.py"
FEATURES_PATH = "release-tools/features.yaml"

PR_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"pull/(?P<number>[0-9]+)"
    r"(?:/(?:files|commits|checks))?"
    r"/?(?:\?[^#]*)?(?:#.*)?$"
)

_NAME_PREFIX = "- name:"
_DESCRIPTION_PREFIX = "description:"


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


class FeatureChange(NamedTuple):
    """Names added with a description, and new names that have none."""

    added: tuple
    incomplete: tuple


def _scalar(text):
    """Return a one-line YAML scalar, without a matching quote pair."""
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1].strip()
    return value


def parse_features(text):
    """Return name to description for every feature entry.

    Entries live under experimental, previously-experimental, or
    non-experimental. Each entry is one "- name:" line and an optional
    following "description:" line. The section key is ignored, so a name
    in any list is one feature.
    A name with no description is kept with an empty string.
    """
    features = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(_NAME_PREFIX):
            name_at = len(_NAME_PREFIX)
            current = _scalar(line[name_at:])
            if current:
                features[current] = ""
            else:
                current = None
            continue
        if current and line.startswith(_DESCRIPTION_PREFIX):
            description_at = len(_DESCRIPTION_PREFIX)
            features[current] = _scalar(line[description_at:])
            current = None
    return features


def compare_features(base_text, head_text):
    """Return names added on the head, and new names that lack a description.

    A name already present on the base is not an addition, including when
    only its description changes. A removal is not an addition.
    """
    base = parse_features(base_text)
    head = parse_features(head_text)
    added = []
    incomplete = []
    for name, description in head.items():
        if name in base:
            continue
        if description:
            added.append((name, description))
        else:
            incomplete.append(name)
    return FeatureChange(tuple(added), tuple(incomplete))


def feature_decision(change):
    """Return yes when at least one name was added with a description."""
    if change.added:
        return "yes"
    return "no"


def print_result(link, change, out=None):
    """Print the feature decision, then the details.

    The first line is always "Feature: <yes or no>" so a caller can read
    the headline without parsing the rest of the report.
    """
    if out is None:
        out = sys.stdout
    print(f"Feature: {feature_decision(change)}", file=out)
    print(file=out)
    print("Details:", file=out)
    print(f"Pull request: {link}", file=out)
    print(f"Added: {len(change.added)}", file=out)
    if change.incomplete:
        print(f"Incomplete: {len(change.incomplete)}", file=out)
    _print_added(change.added, out)
    _print_incomplete(change.incomplete, out)


def _print_added(added, out):
    if not added:
        return
    print(file=out)
    print("Added:", file=out)
    for name, description in added:
        print(f"{name}: {description}", file=out)


def _print_incomplete(incomplete, out):
    if not incomplete:
        return
    print(file=out)
    print("Incomplete:", file=out)
    for name in incomplete:
        print(name, file=out)


def print_help(out=None):
    """Print usage and the feature-list rule."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (("  -h, --help", "Help for pr-feature"),)
    width = max(len(name) for name, _desc in flags)
    print("Report whether a pull request adds a feature name.", file=out)
    print(file=out)
    print("A name counts when it is new in release-tools/features.yaml", file=out)
    print("and the entry has a description. The command prints the", file=out)
    print("decision and exits 0. It does not fail a build.", file=out)
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


def _capture(command):
    """Run command and return a completed process. Raise RuntimeError on OSError."""
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as err:
        raise RuntimeError(f"cannot run {command[0]}: {err}") from err


def _command_error(command, proc):
    detail = proc.stderr.strip() or proc.stdout.strip() or f"{command[0]} failed"
    return RuntimeError(f"cannot run {command[0]}: {detail}")


def _is_missing(proc):
    """True when gh failed because the file is not in that commit."""
    detail = f"{proc.stderr}\n{proc.stdout}"
    return "404" in detail or "Not Found" in detail


def parse_pull_refs(text):
    """Return (base sha, head sha) from a pull request JSON document."""
    try:
        data = json.loads(text)
        base = data["base"]["sha"]
        head = data["head"]["sha"]
    except (json.JSONDecodeError, KeyError, TypeError) as err:
        raise RuntimeError("cannot read pull request") from err
    if not base or not head:
        raise RuntimeError("cannot read pull request")
    return base, head


def pull_request_refs(pr):
    """Return the base and head commit shas of the pull request."""
    command = ["gh", "api", f"repos/{pr.slug}/pulls/{pr.number}"]
    proc = _capture(command)
    if proc.returncode != 0:
        raise _command_error(command, proc)
    return parse_pull_refs(proc.stdout)


def read_features(pr, sha):
    """Return features.yaml at sha. A missing file is an empty string."""
    command = [
        "gh",
        "api",
        "-H",
        "Accept: application/vnd.github.raw",
        f"repos/{pr.slug}/contents/{FEATURES_PATH}?ref={sha}",
    ]
    proc = _capture(command)
    if proc.returncode == 0:
        return proc.stdout
    if _is_missing(proc):
        return ""
    raise _command_error(command, proc)


def feature_change(pr):
    """Return the feature names added between the base and the head."""
    base, head = pull_request_refs(pr)
    return compare_features(read_features(pr, base), read_features(pr, head))


def _fail_usage(err):
    print(f"Error: {err}", file=sys.stderr)
    print(f"Run '{PROG_NAME} --help' for usage.", file=sys.stderr)
    return 2


def main(argv=None):
    """CLI entry: print whether the pull request adds a feature name."""
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
        change = feature_change(pr)
    except UsageError as err:
        return _fail_usage(err)
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1

    print_result(args.link, change)
    return 0


def cli(argv=None):
    """Run main() and turn a usage or read failure into an exit status."""
    return main(argv)


if __name__ == "__main__":
    sys.exit(cli())
