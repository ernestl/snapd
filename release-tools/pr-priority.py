#!/usr/bin/env python3
"""Report the priority a pull request should have.

The input is a GitHub pull request link. gh reads the pull request body.
The References section supplies report link, issue link, and spec link.
Each Launchpad bug, Jira issue, and GitHub issue is a priority
source. A bug link found on a referenced Jira ticket counts as if
the pull request had listed it. Those links are read from the Bug
Link field, the description, and remote links. Salesforce severity
is not read yet.

The decision is the highest level: critical, then high, then medium,
then low. A source that was read and has no level contributes nothing.
A source that cannot be read makes the decision unknown, so a failed
lookup cannot hide a higher level. When no source contributes a level
the decision is unknown. This command prints the decision and exits 0.
It does not fail a CI job, and it does not change a label.
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

PROG_NAME = "pr-priority.py"
JIRA_URL = "https://warthogs.atlassian.net"
SALESFORCE_SEVERITY_FIELD = "Severity__c"
BUG_LINK_FIELD_NAME = "Bug Link"

PR_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"pull/(?P<number>[0-9]+)"
    r"(?:/(?:files|commits|checks))?"
    r"/?(?:\?[^#]*)?(?:#.*)?$"
)
_LP_BUG_RE = re.compile(r"/(?:\+bug|bugs)/(\d+)(?:/|$)")
_CASE_RE = re.compile(r"/Case/([A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?)(?:/|$)")
_JIRA_KEY_RE = re.compile(r"^/browse/([A-Za-z][A-Za-z0-9]+-\d+)/?$")
_GITHUB_ISSUE_RE = re.compile(
    r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([0-9]+)/?$"
)
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"']+")

# Report order. Rank is the position from the low end, so critical wins.
_KINDS = ("launchpad", "salesforce", "jira", "github")
_TITLES = {
    "launchpad": "Launchpad",
    "salesforce": "Salesforce",
    "jira": "Jira",
    "github": "GitHub issue",
}
_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_WORDS = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}
_LP_LEVEL = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "wishlist": "low",
}
_SF_NUMBER = {"1": "critical", "2": "high", "3": "medium", "4": "low"}
_JIRA_LEVEL = {
    "highest": "critical",
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "lowest": "low",
}

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


class Source:  # pylint: disable=too-few-public-methods
    """One priority source, before or after its level is known.

    level is a rank name, "" when the source was read and has no level,
    or None when it could not be read. origin is the Jira key that
    mentioned this source, or "" when the pull request listed it.
    """

    def __init__(self, kind, identity, url, origin):
        self.kind = kind
        self.identity = identity
        self.url = url
        self.origin = origin
        self.level = ""


def _load_bug_fix():
    """Load pr-bug-fix.py. The hyphenated name is not an import path."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pr-bug-fix.py")
    spec = importlib.util.spec_from_file_location("pr_bug_fix_for_priority", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_bug_fix = _load_bug_fix()


def _host_is(host, name):
    """True when host is name or a subdomain of name."""
    return host == name or host.endswith("." + name)


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


def _bug_source(host, path, url, origin):
    """Return a Launchpad or Salesforce source, or None."""
    if _host_is(host, "launchpad.net"):
        match = _LP_BUG_RE.search(path)
        if not match:
            return None
        return Source("launchpad", match.group(1), url, origin)
    if _host_is(host, "salesforce.com") or _host_is(host, "force.com"):
        match = _CASE_RE.search(path)
        identity = match.group(1) if match else url
        return Source("salesforce", identity, url, origin)
    return None


def _tracker_source(host, path, url, origin):
    """Return a Jira or GitHub issue source, or None.

    A Jira URL found on another Jira ticket is not followed.
    """
    key = _jira_key(host, path)
    if key:
        if origin:
            return None
        return Source("jira", key.upper(), url, "")
    issue = _github_issue(host, path)
    if not issue:
        return None
    owner, repo, number = issue
    identity = owner.lower() + "/" + repo.lower() + "#" + number
    return Source("github", identity, url, origin)


def _source_from_url(url, origin):
    """Return a priority source for url, or None when it is not one."""
    parts = urllib.parse.urlparse(url)
    host = (parts.hostname or "").lower()
    path = parts.path or ""
    source = _bug_source(host, path, url, origin)
    if source is not None:
        return source
    return _tracker_source(host, path, url, origin)


def _add(found, source):
    """Record source. A pull-request listing wins over a Jira mention."""
    if source is None:
        return
    key = (source.kind, source.identity)
    current = found.get(key)
    if current is None:
        found[key] = source
        return
    if current.origin and not source.origin:
        current.origin = ""
        current.url = source.url


def _from_body(body):
    """Return the sources listed under References."""
    found = {}
    refs = _bug_fix.parse_references(body or "")
    for key in _bug_fix.LINK_KEYS:
        value = refs.get(key)
        if value is None:
            continue
        kind, detail = _bug_fix.classify_value(value)
        if kind != "url":
            continue
        _add(found, _source_from_url(detail, ""))
    return found


def _trim_url(url):
    """Drop punctuation that a sentence leaves on the end of a URL."""
    return url.rstrip(".,;:)>]")


def _collect_urls(node, found):
    """Append http and https URLs from a Jira field value.

    A field may be a plain string, an Atlassian document, or a URL
    object. Every nested string is scanned, including link marks and
    smart-card urls.
    """
    if isinstance(node, str):
        for match in _URL_IN_TEXT.findall(node):
            found.append(_trim_url(match))
        return
    if isinstance(node, dict):
        for value in node.values():
            _collect_urls(value, found)
        return
    if isinstance(node, list):
        for value in node:
            _collect_urls(value, found)


def _remote_urls(payload):
    """Return object.url values from a Jira remote-link payload."""
    if not isinstance(payload, list):
        return []
    urls = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        obj = item.get("object")
        if not isinstance(obj, dict):
            continue
        url = obj.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            urls.append(url.strip())
    return urls


def _urls_in_issue(payload, links, bug_link_field):
    """Return bug URLs from Bug Link, the description, and remote links."""
    found = []
    if isinstance(payload, dict):
        fields = payload.get("fields")
        if isinstance(fields, dict):
            _collect_urls(fields.get(bug_link_field), found)
            _collect_urls(fields.get("description"), found)
    found.extend(_remote_urls(links))
    return found


def _bug_link_field_id():
    """Return the Bug Link custom field id, or None when it cannot be read.

    JIRA_BUG_LINK_FIELD overrides the lookup. The field list is matched
    on the name Bug Link, ignoring case.
    """
    override = os.environ.get("JIRA_BUG_LINK_FIELD", "").strip()
    if override:
        return override
    payload = _jira_get("/rest/api/3/field")
    if not isinstance(payload, list):
        return None
    target = BUG_LINK_FIELD_NAME.lower()
    for field in payload:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        ident = field.get("id")
        if not isinstance(name, str) or not isinstance(ident, str):
            continue
        if name.strip().lower() == target and ident:
            return ident
    return None


def _get_json(url, headers):
    """Return a JSON body, or None when the request fails."""
    request = urllib.request.Request(url, method="GET")
    for key, value in headers.items():
        request.add_header(key, value)
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
    return payload


def _jira_headers():
    """Return Jira auth headers, or None when credentials are missing."""
    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")
    if not email or not token:
        return None
    raw = f"{email}:{token}".encode()
    encoded = base64.b64encode(raw).decode("ascii")
    return {
        "Accept": "application/json",
        "Authorization": f"Basic {encoded}",
        "User-Agent": "pr-priority",
    }


def _jira_get(path):
    """GET one Jira REST path, or None when it cannot be read."""
    headers = _jira_headers()
    if headers is None:
        return None
    return _get_json(JIRA_URL + path, headers)


def _jira_level(payload):
    """Return the level for priority.name, or "" when it does not map."""
    if not isinstance(payload, dict):
        return ""
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return ""
    priority = fields.get("priority")
    if not isinstance(priority, dict):
        return ""
    name = priority.get("name")
    if not isinstance(name, str):
        return ""
    return _JIRA_LEVEL.get(name.strip().lower(), "")


def _expand_jira(found):
    """Read each Jira issue and bring in the bug links it contains."""
    jira_items = [item for item in found.values() if item.kind == "jira"]
    if not jira_items:
        return
    field_id = _bug_link_field_id()
    for item in jira_items:
        if field_id is None:
            item.level = None
            continue
        quoted = urllib.parse.quote(item.identity)
        field = urllib.parse.quote(field_id)
        path = f"/rest/api/3/issue/{quoted}?fields=priority,description,{field}"
        payload = _jira_get(path)
        links = None
        if payload is not None:
            links = _jira_get(f"/rest/api/3/issue/{quoted}/remotelink")
        if payload is None or links is None:
            item.level = None
            continue
        item.level = _jira_level(payload)
        for url in _urls_in_issue(payload, links, field_id):
            _add(found, _source_from_url(url, item.identity))


def _launchpad_level(bug_id):
    """Return the level for a Launchpad bug, "" or None."""
    url = f"https://api.launchpad.net/devel/bugs/{bug_id}"
    headers = {"Accept": "application/json", "User-Agent": "pr-priority"}
    payload = _get_json(url, headers)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return ""
    importance = payload.get("importance")
    if not isinstance(importance, str):
        return ""
    return _LP_LEVEL.get(importance.strip().lower(), "")


def _salesforce_field():
    """Return the Case field that holds the severity."""
    override = os.environ.get("SALESFORCE_SEVERITY_FIELD", "")
    if override:
        return override
    return SALESFORCE_SEVERITY_FIELD


def _salesforce_text(value):
    """Map a severity string to a level, or "" when it has none."""
    text = value.strip().lower()
    if not text:
        return ""
    match = re.match(r"^(?:sev(?:erity)?\s*)?([1-4])\b", text)
    if match:
        return _SF_NUMBER[match.group(1)]
    for word in ("critical", "high", "medium", "low"):
        if re.search(r"\b" + word + r"\b", text):
            return word
    return ""


def _salesforce_value(value):
    """Map a Salesforce severity to a level, or "" when it has none."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        return _SF_NUMBER.get(str(value), "")
    if not isinstance(value, str):
        return ""
    return _salesforce_text(value)


def _salesforce_level(_item):
    """Return no Salesforce level until the API is available.

    TODO: restore the Case severity request once an admin has approved
    the Salesforce CLI connected app. Until then a Salesforce link does
    not change the priority, and a missing token is not a failure.

    match = _CASE_RE.search(urllib.parse.urlparse(item.url).path or "")
    if not match:
        return None
    token = os.environ.get("SALESFORCE_ACCESS_TOKEN", "")
    instance = os.environ.get("SALESFORCE_INSTANCE_URL", "").rstrip("/")
    if not token or not instance:
        return None
    field = _salesforce_field()
    quoted = urllib.parse.quote(field)
    url = f"{instance}/services/data/v59.0/sobjects/Case/{match.group(1)}"
    url = url + f"?fields={quoted}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "pr-priority",
    }
    payload = _get_json(url, headers)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return ""
    return _salesforce_value(payload.get(field))
    """
    return ""


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


def _labels_level(payload):
    """Return the highest priority label, or "" when there is none."""
    if not isinstance(payload, dict):
        return ""
    labels = payload.get("labels")
    if not isinstance(labels, list):
        return ""
    best = ""
    rank = 0
    for label in labels:
        if not isinstance(label, dict):
            continue
        name = label.get("name")
        if not isinstance(name, str):
            continue
        level = _WORDS.get(name.strip().lower(), "")
        score = _RANK.get(level, 0)
        if score > rank:
            rank = score
            best = level
    return best


def _github_level(url):
    """Return the level for a GitHub issue, "" or None."""
    parts = urllib.parse.urlparse(url)
    issue = _github_issue((parts.hostname or "").lower(), parts.path or "")
    if issue is None:
        return None
    owner, repo, number = issue
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
    return _labels_level(payload)


def _read_level(item):
    """Return the level for a non-Jira source."""
    if item.kind == "launchpad":
        return _launchpad_level(item.identity)
    if item.kind == "salesforce":
        return _salesforce_level(item)
    if item.kind == "github":
        return _github_level(item.url)
    return ""


def _read_other_levels(found):
    """Fill levels for sources other than Jira, which was read while expanding."""
    for item in found.values():
        if item.kind == "jira":
            continue
        item.level = _read_level(item)


def assess(body):
    """Return the sources for a pull request body, with levels filled in."""
    found = _from_body(body)
    _expand_jira(found)
    _read_other_levels(found)
    return found


def _grouped(found):
    """Return sources in report order, one list per kind."""
    groups = {kind: [] for kind in _KINDS}
    for item in found.values():
        groups[item.kind].append(item)
    return groups


def _source_status(items):
    """Return the highest level, none, or unknown for one kind."""
    if not items:
        return "none"
    poisoned = False
    best = ""
    rank = 0
    for item in items:
        if item.level is None:
            poisoned = True
            continue
        score = _RANK.get(item.level, 0)
        if score > rank:
            rank = score
            best = item.level
    if poisoned:
        return "unknown"
    if not best:
        return "none"
    return best


def decide(groups):
    """Return the highest level, or unknown when none can be used."""
    poisoned = False
    best = ""
    rank = 0
    for kind in _KINDS:
        status = _source_status(groups[kind])
        if status == "unknown":
            poisoned = True
            continue
        if status == "none":
            continue
        score = _RANK[status]
        if score > rank:
            rank = score
            best = status
    if poisoned or not best:
        return "unknown"
    return best


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
    """Return the priority decision and the label when the level is known."""
    level = decide(_grouped(assess(pull_request_body(pr))))
    labels = ()
    if level in ("critical", "high", "medium", "low"):
        labels = (level,)
    fact = f"Priority: {level}"
    return _contract().AreaReview("priority", (fact,), labels, ())


def print_result(link, found, out=None):
    """Print the priority decision, then one line per source.

    The first line is always "Priority: <level>" so a caller can read
    the headline without parsing the rest of the report. A bug link
    brought in from a Jira ticket is indented under its source.
    """
    if out is None:
        out = sys.stdout
    groups = _grouped(found)
    print(f"Priority: {decide(groups)}", file=out)
    print(file=out)
    print("Details:", file=out)
    print(f"Pull request: {link}", file=out)
    for kind in _KINDS:
        items = groups[kind]
        print(f"{_TITLES[kind]}: {_source_status(items)}", file=out)
        for item in items:
            if item.origin:
                print(f"  from {item.origin}: {item.url}", file=out)


def print_help(out=None):
    """Print usage and the priority rule."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (("  -h, --help", "Help for pr-priority"),)
    width = max(len(name) for name, _desc in flags)
    print("Report the priority a pull request should have.", file=out)
    print(file=out)
    print("The priority is the highest of Launchpad importance,", file=out)
    print("Jira priority, and GitHub issue labels. A bug link on", file=out)
    print("a referenced Jira ticket counts as if it were listed.", file=out)
    print("Salesforce severity is not read yet. The command prints", file=out)
    print("the decision and exits 0. It does not fail a build.", file=out)
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


def _fail_usage(err):
    print(f"Error: {err}", file=sys.stderr)
    print(f"Run '{PROG_NAME} --help' for usage.", file=sys.stderr)
    return 2


def main(argv=None):
    """CLI entry: print the priority for the pull request."""
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
        body = pull_request_body(pr)
        found = assess(body)
    except UsageError as err:
        return _fail_usage(err)
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1

    print_result(args.link, found)
    return 0


def cli(argv=None):
    """Run main() and turn a usage or read failure into an exit status."""
    return main(argv)


if __name__ == "__main__":
    sys.exit(cli())
