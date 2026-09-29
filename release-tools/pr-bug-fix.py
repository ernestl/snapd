#!/usr/bin/env python3
"""Report whether a pull request has a bug-fix reference.

The input is a GitHub pull request link. gh reads the pull request body.
The References section supplies report link, issue link, and spec link.
A link qualifies when it is Launchpad, Salesforce, a Jira issue of type
bug, a GitHub issue of type bug, a Snapcraft forum topic, or a GitHub
security advisory. This command prints the decision and exits 0. It
does not fail a CI job, and it does not tick a template box.

Bug-fix is yes when at least one of those links qualifies.
"""

# Hyphenated filename; this is a script, not a library. The CLI shape is
# shared with the other release-tools scripts on purpose.
# pylint: disable=invalid-name,duplicate-code

import argparse
import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple

PROG_NAME = "pr-bug-fix.py"
JIRA_URL = "https://warthogs.atlassian.net"

PR_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"pull/(?P<number>[0-9]+)"
    r"(?:/(?:files|commits|checks))?"
    r"/?(?:\?[^#]*)?(?:#.*)?$"
)

_URL_RE = re.compile(r"^https?://\S+$")
_MARKDOWN_LINK_RE = re.compile(r"^\[([^\[\]]*)\]\((https?://[^)\s]+)\)$")
# **label:** value, **label**: value, or label: value.
_FIELD_RE = re.compile(
    r"^(?:\*\*)?(?P<key>[^*:\n]+?)(?:\*\*)?\s*:\s*(?:\*\*\s*)?(?P<value>.*)$"
)
_JIRA_KEY_RE = re.compile(r"^/browse/([A-Za-z][A-Za-z0-9]+-\d+)/?$")
_GITHUB_ISSUE_RE = re.compile(
    r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([0-9]+)/?$"
)

# Checked keys, in report order.
LINK_KEYS = ("report link", "issue link", "spec link")

_LABELS = {
    "report link": "Report link",
    "issue link": "Issue link",
    "spec link": "Spec link",
}

_QUALIFYING = frozenset(
    {
        "launchpad",
        "salesforce",
        "jira bug",
        "github bug",
        "forum",
        "advisory",
    }
)

_TIMEOUT = 20


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


class Reference(NamedTuple):
    """One checked key, its kind, and the value when there is one."""

    key: str
    kind: str
    detail: str


def _section(body, heading):
    """Return the lines under a markdown heading, until the next heading.

    The match is the heading text, ignoring the leading # marks and case.
    A missing heading returns None.
    """
    inside = False
    collected = []
    target = heading.strip().lower()
    for line in (body or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            name = stripped.lstrip("#").strip().lower()
            if inside:
                break
            inside = name == target
            continue
        if inside:
            collected.append(line)
    if not inside:
        return None
    return "\n".join(collected)


def parse_references(body):
    """Return the link keys present under the References heading.

    A key maps to its stripped value. A key that is not in that section
    is absent from the result.
    """
    text = _section(body, "References")
    if text is None:
        return {}
    found = {}
    for line in text.splitlines():
        match = _FIELD_RE.match(line.strip())
        if not match:
            continue
        key = match.group("key").strip()
        if key in LINK_KEYS:
            found[key] = match.group("value").strip()
    return found


def _one_url(value):
    """Return the URL when value is one plain or markdown link."""
    if _URL_RE.match(value):
        return value
    match = _MARKDOWN_LINK_RE.match(value)
    if not match:
        return ""
    return match.group(2)


def classify_value(value):
    """Return (kind, detail) before a URL is classified.

    kind is blank, na, url, or not a link. detail is the URL, or the
    original value when it is not a link, and empty otherwise. A
    markdown link [label](url) is the same as the plain URL.
    """
    if value == "":
        return "blank", ""
    if value.lower() == "n/a":
        return "na", ""
    url = _one_url(value)
    if url:
        return "url", url
    return "not a link", value


def _host_is(host, name):
    """True when host is name or a subdomain of name."""
    return host == name or host.endswith("." + name)


def _static_kind(host, path):
    """Return a kind that can be decided from the URL alone, or empty."""
    if _host_is(host, "launchpad.net"):
        return "launchpad"
    if _host_is(host, "salesforce.com") or _host_is(host, "force.com"):
        return "salesforce"
    if host == "forum.snapcraft.io":
        return "forum"
    if host == "github.com" and "/security/advisories/GHSA-" in path:
        return "advisory"
    return ""


def _jira_key(host, path):
    """Return the Jira issue key, or empty when the URL is not a browse URL."""
    if host != "warthogs.atlassian.net":
        return ""
    match = _JIRA_KEY_RE.match(path)
    if not match:
        return ""
    return match.group(1)


def _github_issue(host, path):
    """Return (owner, repo, number), or None when the URL is not an issue."""
    if host != "github.com":
        return None
    match = _GITHUB_ISSUE_RE.match(path)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


def _type_kind(prefix, type_name):
    """Return the displayed kind for an issue type lookup.

    None means the type could not be read. An empty string means the
    issue has no type. bug matches without regard to case.
    """
    if type_name is None:
        return "unseen"
    if not type_name:
        return f"{prefix} unknown"
    if type_name.lower() == "bug":
        return f"{prefix} bug"
    return f"{prefix} {type_name}"


def link_kind(url, jira_type_of, github_type_of):
    """Return the bug-fix kind of one URL.

    jira_type_of takes an issue key. github_type_of takes owner, repo,
    and number. Either returns the type name, an empty string when the
    issue has no type, or None when the type could not be read.
    """
    parts = urllib.parse.urlparse(url)
    host = (parts.hostname or "").lower()
    path = parts.path or ""
    kind = _static_kind(host, path)
    if kind:
        return kind
    key = _jira_key(host, path)
    if key:
        return _type_kind("jira", jira_type_of(key))
    issue = _github_issue(host, path)
    if issue:
        return _type_kind("github", github_type_of(*issue))
    return "not a bug-fix link"


def jira_issue_type(key):
    """Return the Jira issue type name, "" when it has none, or None.

    None means the credentials are missing or the request failed.
    """
    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")
    if not email or not token:
        return None
    url = f"{JIRA_URL}/rest/api/3/issue/{key}?fields=issuetype"
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", "pr-bug-fix")
    raw = f"{email}:{token}".encode()
    encoded = base64.b64encode(raw).decode("ascii")
    request.add_header("Authorization", f"Basic {encoded}")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            payload = json.loads(response.read().decode())
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        UnicodeError,
    ):
        return None
    return _issue_type_name(payload)


def _issue_type_name(payload):
    """Return fields.issuetype.name, or "" when the payload has none."""
    if not isinstance(payload, dict):
        return ""
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return ""
    issue_type = fields.get("issuetype")
    if not isinstance(issue_type, dict):
        return ""
    name = issue_type.get("name")
    if not isinstance(name, str):
        return ""
    return name


def github_issue_type(owner, repo, number):
    """Return the GitHub issue type name, "" when it has none, or None.

    None means gh could not read the issue.
    """
    command = ["gh", "api", f"repos/{owner}/{repo}/issues/{number}"]
    try:
        proc = _capture(command)
    except RuntimeError:
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return _github_type_name(payload)


def _github_type_name(payload):
    """Return type.name, or "" when the payload has none."""
    if not isinstance(payload, dict):
        return ""
    issue_type = payload.get("type")
    if not isinstance(issue_type, dict):
        return ""
    name = issue_type.get("name")
    if not isinstance(name, str):
        return ""
    return name


def assess_references(body, jira_type_of, github_type_of):
    """Return one Reference per checked key, in report order."""
    found = parse_references(body)
    rows = []
    for key in LINK_KEYS:
        if key not in found:
            rows.append(Reference(key, "absent", ""))
            continue
        kind, detail = classify_value(found[key])
        if kind == "url":
            kind = link_kind(detail, jira_type_of, github_type_of)
        rows.append(Reference(key, kind, detail))
    return tuple(rows)


def bug_fix_decision(rows):
    """Return yes when any reference is a qualifying bug-fix link."""
    for row in rows:
        if row.kind in _QUALIFYING:
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
    """Return the bug-fix decision. No label and no findings."""
    rows = reference_rows(pr)
    fact = f"Bug-fix: {bug_fix_decision(rows)}"
    return _contract().AreaReview("bug-fix", (fact,), (), ())


def _detail_line(row):
    label = _LABELS[row.key]
    if row.kind in ("absent", "blank"):
        return f"{label}: {row.kind}"
    if row.kind == "na":
        return f"{label}: N/A"
    if row.kind == "not a link":
        return f"{label}: not a link {row.detail}"
    return f"{label}: {row.kind} {row.detail}"


def print_result(link, rows, out=None):
    """Print the bug-fix decision, then one line per key.

    The first line is always "Bug-fix: <yes or no>" so a caller can read
    the headline without parsing the rest of the report.
    """
    if out is None:
        out = sys.stdout
    print(f"Bug-fix: {bug_fix_decision(rows)}", file=out)
    print(file=out)
    print("Details:", file=out)
    print(f"Pull request: {link}", file=out)
    for row in rows:
        print(_detail_line(row), file=out)


def print_help(out=None):
    """Print usage and the bug-fix rule."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (("  -h, --help", "Help for pr-bug-fix"),)
    width = max(len(name) for name, _desc in flags)
    print("Report whether a pull request has a bug-fix reference.", file=out)
    print(file=out)
    print("A reference qualifies when it is Launchpad, Salesforce, a", file=out)
    print("Jira or GitHub bug, a Snapcraft forum topic, or a GitHub", file=out)
    print("security advisory. The command prints the decision and", file=out)
    print("exits 0. It does not fail a build.", file=out)
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


def pull_request_body(pr):
    """Return the pull request body. An empty body is an empty string."""
    command = ["gh", "api", f"repos/{pr.slug}/pulls/{pr.number}"]
    proc = _capture(command)
    if proc.returncode != 0:
        raise _command_error(command, proc)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as err:
        raise RuntimeError("cannot read pull request") from err
    if not isinstance(data, dict):
        raise RuntimeError("cannot read pull request")
    body = data.get("body")
    if not isinstance(body, str):
        return ""
    return body


def reference_rows(pr):
    """Read the body and classify each reference link."""
    body = pull_request_body(pr)
    return assess_references(body, jira_issue_type, github_issue_type)


def _fail_usage(err):
    print(f"Error: {err}", file=sys.stderr)
    print(f"Run '{PROG_NAME} --help' for usage.", file=sys.stderr)
    return 2


def main(argv=None):
    """CLI entry: print whether the pull request has a bug-fix reference."""
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
        rows = reference_rows(pr)
    except UsageError as err:
        return _fail_usage(err)
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1

    print_result(args.link, rows)
    return 0


def cli(argv=None):
    """Run main() and turn a usage or read failure into an exit status."""
    return main(argv)


if __name__ == "__main__":
    sys.exit(cli())
