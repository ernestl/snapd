#!/usr/bin/env python3
"""Decide whether a pull request change summary may be omitted.

The input is a GitHub pull request link. pr-complexity.py scores that
pull request. This script does not score anything. It applies one rule:
the change summary may be omitted only when that effort is at most
TRIVIAL_MAX. A larger effort requires a change summary.

Change the limit by editing TRIVIAL_MAX below. The trivial band in
pr-complexity.py is only a size label for the score. This command
prints the decision and exits 0. It does not fail a CI job.
"""

# Hyphenated filename; this is a script, not a library. The CLI shape is
# shared with the other release-tools scripts on purpose.
# pylint: disable=invalid-name,duplicate-code

import argparse
import importlib.util
import os
import sys
from io import StringIO

PROG_NAME = "pr-summary.py"

# The change summary may be omitted only at or below this effort.
TRIVIAL_MAX = 20


class UsageError(Exception):
    """Invalid CLI usage; main() prints this and exits 2."""


def decide(effort):
    """Return optional or required for an effort score."""
    if effort <= TRIVIAL_MAX:
        return "optional"
    return "required"


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
    """Return the change-summary decision. No label and no findings."""
    link = f"https://github.com/{pr.slug}/pull/{pr.number}"
    decision = decide(effort_for_link(link))
    fact = f"Change summary: {decision}"
    return _contract().AreaReview("summary", (fact,), (), ())


def print_result(link, effort, out=None):
    """Print the change-summary decision, then the details.

    The first line is always "Change summary: <decision>" so a caller
    can read the headline without parsing the rest of the report.
    """
    if out is None:
        out = sys.stdout
    print(f"Change summary: {decide(effort)}", file=out)
    print(file=out)
    print("Details:", file=out)
    print(f"Pull request: {link}", file=out)
    print(f"Effort: {effort:.1f}", file=out)
    print(f"Limit: {TRIVIAL_MAX}", file=out)


def print_help(out=None):
    """Print usage and the change-summary rule."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (("  -h, --help", "Help for pr-summary"),)
    width = max(len(name) for name, _desc in flags)
    print("Decide whether a pull request change summary may be omitted.", file=out)
    print(file=out)
    print("The link is scored by pr-complexity.py. The change summary may", file=out)
    print(
        f"be omitted only when that effort is at most {TRIVIAL_MAX}. Change",
        file=out,
    )
    print("the limit by editing TRIVIAL_MAX in this file. This command", file=out)
    print("prints the decision and exits 0.", file=out)
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


def parse_effort_report(text):
    """Return the effort from a pr-complexity.py report.

    The score is the first line, ``Effort: <number>``.
    """
    lines = text.splitlines()
    if not lines or not lines[0].startswith("Effort:"):
        raise RuntimeError("cannot read effort from pr-complexity.py")
    raw = lines[0].split(":", 1)[1].strip()
    try:
        value = float(raw)
    except ValueError:
        raise RuntimeError("cannot read effort from pr-complexity.py") from None
    if value < 0:
        raise RuntimeError("cannot read effort from pr-complexity.py")
    return value


def _load_complexity():
    """Load pr-complexity.py. The hyphenated name is not an import path."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pr-complexity.py")
    spec = importlib.util.spec_from_file_location("pr_complexity", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def effort_for_link(link):
    """Return the effort pr-complexity.py reports for link."""
    mod = _load_complexity()
    try:
        mod.parse_pull_request(link)
    except mod.UsageError as err:
        raise UsageError(str(err)) from err
    out = StringIO()
    captured_err = StringIO()
    saved = sys.stdout, sys.stderr
    try:
        sys.stdout = out
        sys.stderr = captured_err
        code = mod.main([link])
    finally:
        sys.stdout, sys.stderr = saved
    if code != 0:
        detail = captured_err.getvalue().strip() or "pr-complexity.py failed"
        raise RuntimeError(detail)
    return parse_effort_report(out.getvalue())


def _fail_usage(err):
    print(f"Error: {err}", file=sys.stderr)
    print(f"Run '{PROG_NAME} --help' for usage.", file=sys.stderr)
    return 2


def main(argv=None):
    """CLI entry: print whether the change summary may be omitted."""
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
        effort = effort_for_link(args.link)
    except UsageError as err:
        return _fail_usage(err)
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1

    print_result(args.link, effort)
    return 0


def cli(argv=None):
    """Run main() and turn a usage or read failure into an exit status."""
    return main(argv)


if __name__ == "__main__":
    sys.exit(cli())
