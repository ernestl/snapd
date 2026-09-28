#!/usr/bin/env python3
"""Report whether the reference links in a pull request exist.

The input is a GitHub pull request link. gh reads the pull request body.
The references fence supplies report link, issue link, and spec link.
N/A is accepted. Any other value is one http or https URL, and the
stdlib requests it. This command does not check contributor, and it
does not suggest a category or a priority. It prints the decision and
exits 0. It does not fail a CI job, and it does not tick a template box.

Links is yes when every checked key is present and each value is N/A
or a link that exists.
"""

# Hyphenated filename; this is a script, not a library. The CLI shape is
# shared with the other release-tools scripts on purpose.
# pylint: disable=invalid-name,duplicate-code

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple

PROG_NAME = "pr-links.py"

PR_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"pull/(?P<number>[0-9]+)"
    r"(?:/(?:files|commits|checks))?"
    r"/?(?:\?[^#]*)?(?:#.*)?$"
)

_URL_RE = re.compile(r"^https?://\S+$")

# Checked keys, in report order. contributor is not one of them.
LINK_KEYS = ("report link", "issue link", "spec link")

_LABELS = {
    "report link": "Report link",
    "issue link": "Issue link",
    "spec link": "Spec link",
}

_TIMEOUT = 20
_EXISTS = range(200, 400)
_MISSING = (404, 410)


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
    """One checked key, its status, and the value when there is one."""

    key: str
    kind: str
    detail: str


def _references_fence(body):
    """Return the body of the first references fence, or None."""
    inside = False
    collected = []
    for line in body.splitlines():
        stripped = line.strip()
        if not inside:
            opener = stripped[3:].strip() if stripped.startswith("```") else ""
            inside = opener == "references"
            continue
        if stripped.startswith("```"):
            return "\n".join(collected)
        collected.append(line)
    return None


def parse_references(body):
    """Return the link keys present in the first references fence.

    A key maps to its stripped value. A key that is not in the fence is
    absent from the result. contributor is ignored.
    """
    text = _references_fence(body or "")
    if text is None:
        return {}
    found = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in LINK_KEYS:
            found[key] = value.strip()
    return found


def classify_value(value):
    """Return (kind, detail) for one reference value.

    kind is blank, na, url, or not a link. detail is the URL, or the
    original value when it is not a link, and empty otherwise.
    """
    if value == "":
        return "blank", ""
    if value == "N/A":
        return "na", ""
    if _URL_RE.match(value):
        return "url", value
    return "not a link", value


def _github_host(url):
    """True for a URL whose host is github.com."""
    return (urllib.parse.urlparse(url).hostname or "") == "github.com"


def _needs_token(found):
    """True when a github.com URL will be requested."""
    for value in found.values():
        kind, detail = classify_value(value)
        if kind == "url" and _github_host(detail):
            return True
    return False


def _status_for_code(code):
    """Map an HTTP status to exists, missing, or unseen."""
    if code in _EXISTS:
        return "exists"
    if code in _MISSING:
        return "missing"
    return "unseen"


def fetch_status(url, token):
    """Request url and return exists, missing, or unseen.

    urllib follows redirects, so the status is the final response.
    200 through 399 exists. 404 and 410 are missing. 401, 403, a 5xx
    response, any other status, and a connection error are unseen.
    A github.com URL sends the gh token when one was supplied.
    """
    request = urllib.request.Request(url, method="GET")
    # GitHub rejects the default urllib user agent.
    request.add_header("User-Agent", "pr-links")
    if token and _github_host(url):
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            code = response.status
    except urllib.error.HTTPError as err:
        code = err.code
        if err.fp is not None:
            err.close()
    except (urllib.error.URLError, TimeoutError, OSError):
        return "unseen"
    return _status_for_code(code)


def assess_references(body, status_of):
    """Return one Reference per checked key, in report order.

    status_of is called with a URL and returns exists, missing, or unseen.
    """
    found = parse_references(body)
    rows = []
    for key in LINK_KEYS:
        if key not in found:
            rows.append(Reference(key, "absent", ""))
            continue
        kind, detail = classify_value(found[key])
        if kind == "url":
            kind = status_of(detail)
        rows.append(Reference(key, kind, detail))
    return tuple(rows)


def links_decision(rows):
    """Return yes when every key is N/A or a link that exists."""
    for row in rows:
        if row.kind not in ("na", "exists"):
            return "no"
    return "yes"


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
    """Print the links decision, then one line per key.

    The first line is always "Links: <yes or no>" so a caller can read
    the headline without parsing the rest of the report.
    """
    if out is None:
        out = sys.stdout
    print(f"Links: {links_decision(rows)}", file=out)
    print(file=out)
    print("Details:", file=out)
    print(f"Pull request: {link}", file=out)
    for row in rows:
        print(_detail_line(row), file=out)


def print_help(out=None):
    """Print usage and the link rule."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (("  -h, --help", "Help for pr-links"),)
    width = max(len(name) for name, _desc in flags)
    print("Report whether the reference links in a pull request exist.", file=out)
    print(file=out)
    print("report link, issue link, and spec link are N/A or one URL.", file=out)
    print("The command requests each URL. It prints the decision and", file=out)
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


def github_token():
    """Return the gh auth token, or an empty string when it is not available."""
    command = ["gh", "auth", "token"]
    try:
        proc = _capture(command)
    except RuntimeError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def reference_rows(pr):
    """Read the body and assess each reference link."""
    body = pull_request_body(pr)
    token = ""
    if _needs_token(parse_references(body)):
        token = github_token()

    def status_of(url):
        return fetch_status(url, token)

    return assess_references(body, status_of)


def _fail_usage(err):
    print(f"Error: {err}", file=sys.stderr)
    print(f"Run '{PROG_NAME} --help' for usage.", file=sys.stderr)
    return 2


def main(argv=None):
    """CLI entry: print whether the reference links exist."""
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
