#!/usr/bin/env python3
"""Summarise a pull request and approve or fail from area findings.

The input is a GitHub pull request link. Each area script reviews its
own area. This command collects those results into one comment. It does
not reimplement their rules.

An error finding fails the review. A warning does not approve or fail.
No findings is an approval. Approval is not submitted until an area has
a real check, because the first areas return facts and no findings.

Without --publish the command prints the comment. With --publish it
updates the marked comment and submits the review. A successful report
exits 0. An error finding exits 1.
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

PROG_NAME = "pr-review.py"
MARKER = "<!-- snapd-pr-review -->"
_PLACEHOLDER = "<add your note here>"

# The first areas return facts and no findings, so a clean run would
# approve every pull request. Leave this false until one area emits a
# real check.
PUBLISH_APPROVAL = False

_AREAS = (
    "pr-priority.py",
    "pr-feature.py",
    "pr-links.py",
    "pr-bug-fix.py",
    "pr-interface.py",
    "pr-packaging.py",
    "pr-systemd-services.py",
    "pr-test-only.py",
    "pr-summary.py",
)

_FACT_ORDER = (
    "feature",
    "links",
    "bug-fix",
    "interface",
    "packaging",
    "systemd-services",
    "test-only",
    "summary",
)

_REVIEW_EVENT = {
    "approve": "APPROVE",
    "comment": "COMMENT",
    "fail": "REQUEST_CHANGES",
}

PR_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"pull/(?P<number>[0-9]+)"
    r"(?:/(?:files|commits|checks))?"
    r"/?(?:\?[^#]*)?(?:#.*)?$"
)

_NOTE_RE = re.compile(r"^\*\*release note:\*\*\s*(?P<value>.*)$", re.IGNORECASE)
_OMIT_RE = re.compile(r"^- \[(?P<mark>[ xX])\] Omit\s*$")


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


def _load(filename):
    """Load a hyphenated script beside this file."""
    name = "pr_review_" + filename.replace("-", "_").replace(".", "_")
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def area_modules():
    """Return the area scripts in report order."""
    return tuple(_load(name) for name in _AREAS)


def labels_script():
    """Return pr-labels.py."""
    return _load("pr-labels.py")


def verdict_of(reviews):
    """Return fail, comment, or approve from the collected findings."""
    severities = {item.severity for review in reviews for item in review.findings}
    if "error" in severities:
        return "fail"
    if "warning" in severities:
        return "comment"
    return "approve"


def release_fields(body):
    """Return the release note text and whether Omit is ticked."""
    note = ""
    omit = "no"
    for raw in (body or "").splitlines():
        line = raw.strip()
        match = _NOTE_RE.match(line)
        if match:
            note = match.group("value").strip().strip("`").strip()
        omitted = _OMIT_RE.match(line)
        if omitted and omitted.group("mark").lower() == "x":
            omit = "yes"
    if not note or note == _PLACEHOLDER:
        note = "not set"
    return note, omit


def _fact_line(review):
    """Return one information line for an area."""
    if not review.facts:
        return ""
    fact = review.facts[0]
    if review.name == "feature" and fact.startswith("Feature:"):
        return fact.replace("Feature:", "Feature file:", 1)
    return fact


def _finding_lines(reviews, severity):
    """Return finding lines for one severity, or none."""
    lines = []
    for review in reviews:
        for finding in review.findings:
            if finding.severity == severity:
                lines.append(f"- {review.name}: {finding.message}")
    if not lines:
        return ("none",)
    return tuple(lines)


def _ordered_facts(reviews):
    """Return information lines, leaving priority to the label report."""
    by_name = {review.name: review for review in reviews}
    lines = []
    shown = set()
    for name in _FACT_ORDER:
        review = by_name.get(name)
        if review is None:
            continue
        shown.add(name)
        line = _fact_line(review)
        if line:
            lines.append(line)
    for review in reviews:
        if review.name in shown or review.name == "priority":
            continue
        line = _fact_line(review)
        if line:
            lines.append(line)
    return lines


def render_comment(note, omit, label_text, reviews, verdict):
    """Return the marked comment body."""
    lines = [
        MARKER,
        f"Review: {verdict}",
        "",
        "## Information",
        "",
        f"Release note: {note}",
        f"Omit: {omit}",
        "",
        label_text.strip(),
        "",
    ]
    lines.extend(_ordered_facts(reviews))
    lines.extend(["", "## Warnings", ""])
    lines.extend(_finding_lines(reviews, "warning"))
    lines.extend(["", "## Errors", ""])
    lines.extend(_finding_lines(reviews, "error"))
    return "\n".join(lines) + "\n"


def _label_words(reviews):
    """Return label words requested by areas, in review order."""
    words = []
    for review in reviews:
        for label in review.labels:
            if label not in words:
                words.append(label)
    return tuple(words)


def collect_reviews(pr):
    """Return one AreaReview from each area script."""
    return tuple(mod.review(pr) for mod in area_modules())


def run_review(pr, link):
    """Return the comment body and the verdict."""
    note, omit = release_fields(pull_request_body(pr))
    reviews = collect_reviews(pr)
    label_text = labels_script().label_report(pr, link, _label_words(reviews))
    verdict = verdict_of(reviews)
    return render_comment(note, omit, label_text, reviews, verdict), verdict


def _capture(command, stdin=None):
    """Run command and return stdout. Raise RuntimeError on failure."""
    try:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            input=stdin,
        )
    except OSError as err:
        raise RuntimeError(f"cannot run {command[0]}: {err}") from err
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"{command[0]} failed"
        raise RuntimeError(f"cannot run {command[0]}: {detail}")
    return proc.stdout


def _json_values(text, what):
    """Return JSON documents from gh output. Pages are concatenated."""
    raw = (text or "").strip()
    if not raw:
        raise RuntimeError(f"cannot read {what}")
    decoder = json.JSONDecoder()
    values = []
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
            raise RuntimeError(f"cannot read {what}: {err}") from err
        idx = end
        values.append(data)
    if not values:
        raise RuntimeError(f"cannot read {what}")
    return values


def pull_request_body(pr):
    """Return the pull request body. A missing body is empty."""
    raw = _capture(["gh", "api", f"repos/{pr.slug}/pulls/{pr.number}"])
    values = _json_values(raw, "pull request")
    if len(values) != 1 or not isinstance(values[0], dict):
        raise RuntimeError("cannot read pull request")
    body = values[0].get("body")
    if not isinstance(body, str):
        return ""
    return body


def _comment_id(pr):
    """Return the id of the marked comment, or None."""
    raw = _capture(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{pr.slug}/issues/{pr.number}/comments",
        ]
    )
    for data in _json_values(raw, "pull request comments"):
        rows = data if isinstance(data, list) else [data]
        for item in rows:
            if not isinstance(item, dict):
                continue
            body = item.get("body")
            if isinstance(body, str) and body.startswith(MARKER):
                return item.get("id")
    return None


def _upsert_comment(pr, body):
    """Create the marked comment, or replace it."""
    payload = json.dumps({"body": body})
    comment_id = _comment_id(pr)
    if comment_id is None:
        path = f"repos/{pr.slug}/issues/{pr.number}/comments"
    else:
        path = f"repos/{pr.slug}/issues/comments/{comment_id}"
    method = "POST" if comment_id is None else "PATCH"
    _capture(["gh", "api", "--method", method, "--input", "-", path], stdin=payload)


def _submit_review(pr, body, verdict):
    """Submit the GitHub review for this verdict."""
    if verdict == "approve" and not PUBLISH_APPROVAL:
        return
    payload = json.dumps({"event": _REVIEW_EVENT[verdict], "body": body})
    path = f"repos/{pr.slug}/pulls/{pr.number}/reviews"
    _capture(["gh", "api", "--method", "POST", "--input", "-", path], stdin=payload)


def publish(pr, body, verdict):
    """Update the marked comment and submit the review."""
    _upsert_comment(pr, body)
    _submit_review(pr, body, verdict)


def print_help(out=None):
    """Print usage and the verdict rule."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (
        ("  -h, --help", "Help for pr-review"),
        ("  --publish", "Update the comment and submit the review"),
    )
    width = max(len(name) for name, _desc in flags)
    print("Summarise a pull request from the area reviews.", file=out)
    print(file=out)
    print("The comment has an information section and a warnings", file=out)
    print("and errors section. An error finding exits 1. Any other", file=out)
    print("report exits 0. Approval is not submitted until an area", file=out)
    print("has a real check.", file=out)
    print(file=out)
    print("Usage:", file=out)
    print(f"  {prog} <pull-request>", file=out)
    print(file=out)
    print("Examples:", file=out)
    example = f"  {prog} https://github.com/canonical/snapd/pull/17718"
    print(example, file=out)
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
    parser.add_argument("--publish", action="store_true")
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


def _fail_usage(err):
    print(f"Error: {err}", file=sys.stderr)
    print(f"Run '{PROG_NAME} --help' for usage.", file=sys.stderr)
    return 2


def main(argv=None):
    """CLI entry: print the review, and publish it when asked."""
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
        comment, verdict = run_review(pr, args.link)
        if args.publish:
            publish(pr, comment, verdict)
    except UsageError as err:
        return _fail_usage(err)
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1

    print(comment, end="")
    return 1 if verdict == "fail" else 0


def cli(argv=None):
    """Run main() and turn a usage or read failure into an exit status."""
    return main(argv)


if __name__ == "__main__":
    sys.exit(cli())
