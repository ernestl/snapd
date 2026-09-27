#!/usr/bin/env python3
"""Score the review effort of a GitHub pull request.

The report is metadata for reviewers. A large change is sometimes
necessary, so this command prints the score and exits 0. It must not
fail a CI job.

Effort is churn + dispersion + cognitive complexity, and never below
zero:

    churn = added growth + DELETION_WEIGHT × removed growth
    file dispersion = MEDIUM_MAX ^ ((files - 1) / (FILE_AT_MAX - 1))
    directory dispersion = MEDIUM_MAX ^ ((contexts - 1) / (DIR_AT_MAX - 1))
    dispersion = file dispersion + directory dispersion
    cognitive complexity = COGNITIVE_WEIGHT × gocognit
    effort = churn + dispersion + cognitive complexity

added is the unit, so it has no weight. The band names the size of
that effort: trivial at or below TRIVIAL_MAX, small at or below
SMALL_MAX, medium at or below MEDIUM_MAX, and large above that. This
script stops at the score. It does not decide pull request template
fields.

Churn is how much source the pull request writes or deletes. A line
counts as source when it contains code, following David A. Wheeler's
physical source line. Comments, blank lines, and every other changed
line are non-source. Changed source lines plus non-source lines equal
the pull request's additions and deletions. Non-source lines do not
move the score. Go, C, Python, and shell can contribute source lines.
Generated and vendored paths (go.sum, go.mod, vendor, mocks, *.pb.go,
*_generated.go) do not: their changed lines are non-source. Source
growth is linear through ADDED_KNEE added lines and REMOVED_KNEE
removed lines, then slightly exponential, so a change past about 500
added lines or 800 removed lines climbs faster than the line count.
A removed line costs DELETION_WEIGHT, half of an added line.

Dispersion is how spread out the change is. files is the number of
changed files. contexts is the number of review contexts, the first two
path components, so overlord/snapstate and overlord/ifacestate are
different contexts, and two files in overlord/snapstate are one context.
One file and one context contribute nothing. The cost grows
exponentially: FILE_AT_MAX files, or DIR_AT_MAX contexts, each reach
MEDIUM_MAX. Two files or two contexts stay small.

gocognit is the sum of cognitive complexities for Go functions the pull
request touches. The link identifies the pull request. gh reads its
diff. golangci-lint runs in a temporary worktree of the pull request
head. The script supplies a gocognit config with min-complexity 0, and
--new-from-rev is the merge base of that head and the base branch. A
function counts when its cognitive complexity is greater than 0, which
means it has control flow. Straight-line functions add nothing.
golangci-lint does not subtract the complexity on the base revision,
so a function that was already complex and is touched still counts in
full.

Change the default weights by editing DELETION_WEIGHT, ADDED_KNEE,
REMOVED_KNEE, FILE_AT_MAX, DIR_AT_MAX, and COGNITIVE_WEIGHT below. One
run can override them with --deletion-weight, --added-knee,
--removed-knee, --files-at-max, --directories-at-max, and
--cognitive-weight.
Change the band ceilings by editing TRIVIAL_MAX, SMALL_MAX, and
MEDIUM_MAX below. The gocognit config this script supplies keeps
min-complexity at 0. Leave gocognit disabled in .golangci.yml: the
static checks use that file, and enabling gocognit there would fail
that job.
"""

# Hyphenated filename; this is a script, not a library. The CLI shape is
# shared with the other release-tools scripts on purpose.
# pylint: disable=invalid-name,duplicate-code

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import NamedTuple

PROG_NAME = "pr-complexity.py"

PR_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"pull/(?P<number>[0-9]+)"
    r"(?:/(?:files|commits|checks))?"
    r"/?(?:\?[^#]*)?(?:#.*)?$"
)

# Size labels for the effort score. Not a pull request template decision.
# MEDIUM_MAX is just above the largest careful-read change in the
# September 2026 calibration sample. The 143-file migration stayed large.
TRIVIAL_MAX = 20
SMALL_MAX = 100
MEDIUM_MAX = 700

# An added source line costs 1 through ADDED_KNEE, then the cost climbs.
# A removed line costs DELETION_WEIGHT, and starts climbing at REMOVED_KNEE.
DELETION_WEIGHT = 0.5
ADDED_KNEE = 500
REMOVED_KNEE = 800
# File count, and review-context count, at which dispersion reaches
# MEDIUM_MAX. One of either contributes nothing. Two stay small.
FILE_AT_MAX = 20
DIR_AT_MAX = 8
# Multiplier for the gocognit total inside the effort score.
COGNITIVE_WEIGHT = 3

COGNITIVE_RE = re.compile(r"cognitive complexity (\d+) of func ")
# Supplied at runtime, not written into .golangci.yml.
GOCOGNIT_CONFIG = """\
version: "2"
linters:
  default: none
  enable:
    - gocognit
  settings:
    gocognit:
      min-complexity: 0
output:
  formats:
    json:
      path: stdout
"""


class PullRequest(NamedTuple):
    """A GitHub pull request identified by its link."""

    owner: str
    repo: str
    number: str

    @property
    def slug(self):
        """owner/repo, as gh --repo expects it."""
        return f"{self.owner}/{self.repo}"

    @property
    def git_url(self):
        """Git URL used to fetch the head and the base branch."""
        return f"https://github.com/{self.owner}/{self.repo}.git"

    @property
    def url(self):
        """Canonical pull request link."""
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.number}"


class Weights(NamedTuple):
    """Costs used to turn a diff into an effort score."""

    deletion: float
    added_knee: float
    removed_knee: float
    files_at_max: float
    directories_at_max: float
    cognitive: float


DEFAULT_WEIGHTS = Weights(
    DELETION_WEIGHT,
    ADDED_KNEE,
    REMOVED_KNEE,
    FILE_AT_MAX,
    DIR_AT_MAX,
    COGNITIVE_WEIGHT,
)

GO_EXT = ".go"
C_LIKE_EXTS = {".c", ".h", ".cc", ".hh", ".cpp", ".hpp", ".cxx", ".hxx"}
PYTHON_EXT = ".py"
SHELL_EXTS = {".sh", ".bash"}


class UsageError(Exception):
    """Invalid CLI usage; main() prints this and exits 2."""


class ChangeSize(NamedTuple):
    """Inputs of the three-layer effort score."""

    added: int
    removed: int
    non_source: int
    ignored: int
    files: int
    directories: int
    gocognit: int
    measured: bool
    weights: Weights

    @property
    def changed(self):
        """Added source lines plus removed source lines, before weighting."""
        return self.added + self.removed

    @property
    def churn(self):
        """Source growth, linear through each knee, then slightly exponential."""
        added = _source_growth(self.added, self.weights.added_knee)
        removed = _source_growth(self.removed, self.weights.removed_knee)
        return added + self.weights.deletion * removed

    @property
    def dispersion(self):
        """Exponential file span plus exponential directory span."""
        files = _exponential_span(self.files, self.weights.files_at_max)
        directories = _exponential_span(
            self.directories, self.weights.directories_at_max
        )
        return files + directories

    @property
    def cognitive_complexity(self):
        """COGNITIVE_WEIGHT × gocognit."""
        return self.gocognit * self.weights.cognitive

    @property
    def effort(self):
        """Churn, dispersion, and cognitive complexity, never below zero."""
        score = self.churn + self.dispersion + self.cognitive_complexity
        if score < 0:
            return 0
        return score

    @property
    def band(self):
        """Size label: trivial, small, medium, or large."""
        if self.effort <= TRIVIAL_MAX:
            return "trivial"
        if self.effort <= SMALL_MAX:
            return "small"
        if self.effort <= MEDIUM_MAX:
            return "medium"
        return "large"


def _source_growth(lines, knee):
    """Linear through knee, then slightly exponential.

    The slope is 1 at the knee and increases after it. extra is how far
    past the knee the line count has gone.
    """
    if lines <= knee:
        return float(lines)
    extra = lines - knee
    return knee + extra * math.exp(extra / knee)


def _exponential_span(count, at_max):
    """Grow from 0 at one item to MEDIUM_MAX at at_max items.

    A count of one returns 0. MEDIUM_MAX to the power of zero would be 1,
    which would charge for a change that has not spread at all.
    """
    extra = max(0, count - 1)
    if extra == 0:
        return 0
    return MEDIUM_MAX ** (extra / (at_max - 1))


class CLikeScanner:  # pylint: disable=too-few-public-methods
    """Physical-SLOC scan for // and /* */ languages.

    Block-comment and raw-string state carry across lines. Call one scanner
    for the old side of a file and another for the new side.
    """

    def __init__(self, raw_strings=False):
        self._raw_strings = raw_strings
        self._block = False
        self._raw = False

    def feed(self, line):
        """Return whether line contains code. Update comment state."""
        i = 0
        n = len(line)
        saw = False
        while i < n:
            if self._raw:
                end = line.find("`", i)
                if end < 0:
                    return True
                saw = True
                self._raw = False
                i = end + 1
                continue
            if self._block:
                end = line.find("*/", i)
                if end < 0:
                    return saw
                self._block = False
                i = end + 2
                continue
            char = line[i]
            if char in " \t\r":
                i += 1
                continue
            if line.startswith("//", i):
                return saw
            if line.startswith("/*", i):
                self._block = True
                i += 2
                continue
            if char == "`" and self._raw_strings:
                self._raw = True
                saw = True
                i += 1
                continue
            if char == '"':
                i = _skip_escaped(line, i, '"')
                saw = True
                continue
            if char == "'":
                i = _skip_escaped(line, i, "'")
                saw = True
                continue
            saw = True
            i += 1
        return saw


class HashScanner:  # pylint: disable=too-few-public-methods
    """Physical-SLOC scan for languages whose line comment starts with #.

    Python triple quotes can span lines. Shell uses the same quote rules
    without triple quotes.
    """

    def __init__(self, triple=False):
        self._triple = triple
        self._quote = None

    def feed(self, line):
        """Return whether line contains code. Update string state."""
        i = 0
        n = len(line)
        saw = False
        while i < n:
            if self._quote:
                end = line.find(self._quote, i)
                if end < 0:
                    return True
                saw = True
                i = end + len(self._quote)
                self._quote = None
                continue
            char = line[i]
            if char in " \t\r":
                i += 1
                continue
            if char == "#":
                return saw
            if char in "'\"":
                delim = char
                if self._triple and line.startswith(char * 3, i):
                    delim = char * 3
                self._quote = delim
                saw = True
                i += len(delim)
                continue
            saw = True
            i += 1
        return saw


def _skip_escaped(line, start, quote):
    """Return the index after a quoted span that honors backslash escapes."""
    i = start + 1
    n = len(line)
    while i < n:
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == quote:
            return i + 1
        i += 1
    return n


def _extension(path):
    return os.path.splitext(path)[1].lower()


def _ignored(path):
    """True for generated or vendored paths that must not move the score."""
    name = os.path.basename(path)
    if name in {"go.mod", "go.sum"}:
        return True
    parts = path.split("/")
    if "vendor" in parts or "mock" in parts or "mocks" in parts:
        return True
    if name.endswith((".pb.go", "_generated.go", "_mock.go")):
        return True
    return False


def _scanners_for(path):
    """Return (old scanner, new scanner, is_source) for path."""
    ext = _extension(path)
    if ext == GO_EXT:
        return CLikeScanner(raw_strings=True), CLikeScanner(raw_strings=True), True
    if ext in C_LIKE_EXTS:
        return CLikeScanner(raw_strings=False), CLikeScanner(raw_strings=False), True
    if ext == PYTHON_EXT:
        return HashScanner(triple=True), HashScanner(triple=True), True
    if ext in SHELL_EXTS:
        return HashScanner(triple=False), HashScanner(triple=False), True
    return None, None, False


def _review_context(path):
    """Directory a reviewer has to load. Two levels down, not the repo root."""
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    if parts:
        return parts[0]
    return "(root)"


def _split_diff_git(line):
    """Return (old path, new path) from a `diff --git` header.

    A path that itself contains `` b/`` is ambiguous. Git diffs of ordinary
    snapd paths do not.
    """
    marker = "diff --git "
    start = len(marker)
    rest = line[start:]
    if not rest.startswith("a/") or " b/" not in rest:
        return None, None
    old, new = rest[2:].split(" b/", 1)
    return old, new


def _header_path(line):
    """Return the path from a `---` or `+++` header, without a/ or b/."""
    path = line[4:].split("\t", 1)[0].strip()
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


class _Tally:  # pylint: disable=too-few-public-methods
    """Source lines, files, and contexts accumulated from one diff."""

    def __init__(self):
        self.added = 0
        self.removed = 0
        self.non_source = 0
        self.files = set()
        self.contexts = set()
        self.ignored = set()


class _FileCursor:  # pylint: disable=too-few-public-methods
    """Which file a diff line belongs to, and that file's scanners."""

    def __init__(self):
        self.pending = None
        self.path = None
        self.old_scan = None
        self.new_scan = None
        self.kind = "other"
        self.in_hunk = False

    def read(self, line, tally):
        """Update tally from one unified-diff line."""
        if line.startswith("diff --git "):
            self._begin_file(line)
        elif line.startswith("@@"):
            self._begin_hunk(tally)
        elif not self.in_hunk and line.startswith("+++ "):
            self._note_path(line)
        elif self.in_hunk and line and not line.startswith("\\"):
            self._count(line, tally)

    def _begin_file(self, line):
        old_path, new_path = _split_diff_git(line)
        if new_path and new_path != "/dev/null":
            self.pending = new_path
        else:
            self.pending = old_path
        self.path = None
        self.in_hunk = False
        self.kind = "other"

    def _begin_hunk(self, tally):
        self.in_hunk = True
        if not self.path:
            return
        if self.kind == "ignored":
            tally.ignored.add(self.path)
            return
        tally.files.add(self.path)
        tally.contexts.add(_review_context(self.path))

    def _note_path(self, line):
        path = _header_path(line)
        if path == "/dev/null":
            path = self.pending
        self.path = path
        if not path:
            return
        if _ignored(path):
            self.kind = "ignored"
            self.old_scan = None
            self.new_scan = None
            return
        self.old_scan, self.new_scan, source = _scanners_for(path)
        self.kind = "source" if source else "other"

    def _count(self, line, tally):
        added, removed, non_source = _count_body(
            self.kind, line[0], line[1:], self.old_scan, self.new_scan
        )
        tally.added += added
        tally.removed += removed
        tally.non_source += non_source


def _count_body(kind, marker, body, old_scan, new_scan):
    """Return added, removed, and non-source increments for one hunk line."""
    if marker == " ":
        if kind == "source":
            old_scan.feed(body)
            new_scan.feed(body)
        return 0, 0, 0
    if marker == "+":
        return _changed_line(kind, body, new_scan, added=True)
    if marker == "-":
        return _changed_line(kind, body, old_scan, added=False)
    return 0, 0, 0


def _changed_line(kind, body, scan, added):
    """Return increments for one added or removed line.

    A physical source line counts as source. Every other changed line
    counts as non-source, so the two totals add up to the pull request.
    """
    if kind == "source" and scan.feed(body):
        if added:
            return 1, 0, 0
        return 0, 1, 0
    return 0, 0, 1


def classify_diff(diff_text, weights=None, gocognit=None):
    """Score a git unified diff as churn, dispersion, and cognitive complexity.

    gocognit is the summed cognitive complexity, or None when it was not run.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    measured = gocognit is not None
    if gocognit is None:
        gocognit = 0
    tally = _Tally()
    cursor = _FileCursor()
    for line in diff_text.splitlines():
        cursor.read(line, tally)
    return ChangeSize(
        tally.added,
        tally.removed,
        tally.non_source,
        len(tally.ignored),
        len(tally.files),
        len(tally.contexts),
        gocognit,
        measured,
        weights,
    )


def _score(value):
    return f"{value:.1f}"


def _num(value):
    """Format a weight, keeping 0.5 and printing 4 rather than 4.0."""
    if value == int(value):
        return str(int(value))
    return str(value)


def print_result(result, pull_request=None, out=None):
    """Print effort and its band, then the calculation and the details.

    The first line is always "Effort: <score>" so a caller can read the
    headline without parsing the rest of the report. Band is the size
    label for that score and sits on the next line.
    """
    if out is None:
        out = sys.stdout
    weights = result.weights
    print(f"Effort: {_score(result.effort)}", file=out)
    print(f"Band: {result.band}", file=out)
    print(file=out)
    print("Calculation:", file=out)
    print(f"Churn: {_score(result.churn)}", file=out)
    print(f"Dispersion: {_score(result.dispersion)}", file=out)
    print(f"Cognitive complexity: {_score(result.cognitive_complexity)}", file=out)
    print(file=out)
    print("Details:", file=out)
    if pull_request:
        print(f"Pull request: {pull_request}", file=out)
    print(
        "Weights:"
        f" deletion {_num(weights.deletion)},"
        f" added knee {_num(weights.added_knee)},"
        f" removed knee {_num(weights.removed_knee)},"
        f" files {_num(weights.files_at_max)},"
        f" directories {_num(weights.directories_at_max)},"
        f" cognitive {_num(weights.cognitive)}",
        file=out,
    )
    print(f"Added source lines: {result.added}", file=out)
    print(f"Removed source lines: {result.removed}", file=out)
    print(f"Changed source lines: {result.changed}", file=out)
    print(f"Files: {result.files}", file=out)
    print(f"Directories: {result.directories}", file=out)
    if result.measured:
        print(f"Gocognit: {result.gocognit}", file=out)
    else:
        print("Gocognit: not run", file=out)
    print(f"Non-source lines: {result.non_source}", file=out)
    print(f"Ignored files: {result.ignored}", file=out)


def print_help(out=None):
    """Print usage, the effort formula, and the weight flags."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (
        (
            "      --deletion-weight float",
            f"Cost of a deleted source line (default {DELETION_WEIGHT})",
        ),
        (
            "      --added-knee count",
            f"Added lines where churn starts to climb (default {ADDED_KNEE})",
        ),
        (
            "      --removed-knee count",
            f"Removed lines where churn starts to climb (default {REMOVED_KNEE})",
        ),
        (
            "      --files-at-max count",
            f"Files that reach the medium ceiling (default {FILE_AT_MAX})",
        ),
        (
            "      --directories-at-max count",
            f"Directories that reach the medium ceiling (default {DIR_AT_MAX})",
        ),
        (
            "      --cognitive-weight float",
            f"Multiplier for the gocognit total (default {COGNITIVE_WEIGHT})",
        ),
        ("  -h, --help", "Help for pr-complexity"),
    )
    width = max(len(name) for name, _desc in flags)
    print("Score the review effort of a GitHub pull request.", file=out)
    print(file=out)
    print("effort = churn + dispersion + cognitive complexity", file=out)
    print(file=out)
    print("churn = added growth + DELETION_WEIGHT × removed growth", file=out)
    print("Growth is linear through ADDED_KNEE and REMOVED_KNEE, then", file=out)
    print("slightly exponential.", file=out)
    print(
        "file dispersion = MEDIUM_MAX ^ ((files - 1) / (FILE_AT_MAX - 1))",
        file=out,
    )
    print(
        "directory dispersion = MEDIUM_MAX ^ ((contexts - 1) / (DIR_AT_MAX - 1))",
        file=out,
    )
    print("One file or one directory is 0. Two of either stay small.", file=out)
    print("cognitive complexity = COGNITIVE_WEIGHT × gocognit", file=out)
    print(file=out)
    print(
        "Below the knees, added is the unit. removed costs DELETION_WEIGHT,", file=out
    )
    print("so churn is not added plus removed. Past the knees the cost", file=out)
    print("climbs. The band names the size of the effort score.", file=out)
    print(file=out)
    print(
        "The command reports the score and exits 0. It does not fail a build.", file=out
    )
    print(file=out)
    print("Default weights and band ceilings are the constants at the top of", file=out)
    print("this file. The weight flags override those defaults for one run.", file=out)
    print("gocognit sums every touched Go function that has control flow.", file=out)
    print("The script supplies that config. min-complexity stays 0.", file=out)
    print(file=out)
    print("Usage:", file=out)
    print(f"  {prog} <pull-request> [flags]", file=out)
    print(file=out)
    print("Examples:", file=out)
    print(f"  {prog} https://github.com/canonical/snapd/pull/17718", file=out)
    print(
        f"  {prog} https://github.com/canonical/snapd/pull/17718 --cognitive-weight 5",
        file=out,
    )
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
    parser.add_argument("--deletion-weight", dest="deletion_weight")
    parser.add_argument("--added-knee", dest="added_knee")
    parser.add_argument("--removed-knee", dest="removed_knee")
    parser.add_argument("--files-at-max", dest="files_at_max")
    parser.add_argument("--directories-at-max", dest="directories_at_max")
    parser.add_argument("--cognitive-weight", dest="cognitive_weight")
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


def pull_request_diff(pr):
    """Return the unified diff of the pull request from gh."""
    return _capture(["gh", "pr", "diff", pr.number, "--repo", pr.slug])


def _pull_request_refs(pr):
    """Return (base branch name, head commit) from gh."""
    raw = _capture(
        [
            "gh",
            "pr",
            "view",
            pr.number,
            "--repo",
            pr.slug,
            "--json",
            "baseRefName,headRefOid",
        ]
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"cannot read pull request: {err}") from err
    base = data.get("baseRefName")
    head = data.get("headRefOid")
    if not base or not head:
        raise RuntimeError("cannot read pull request base and head")
    return base, head


def _issue_summary(text):
    """True when text is golangci-lint's trailing issue summary."""
    lines = text.splitlines()
    if not re.fullmatch(r"\d+ issues[.:]?", lines[0]):
        return False
    return all(line.startswith("* ") for line in lines[1:])


def cognitive_total(report):
    """Sum gocognit complexities in a golangci-lint JSON report.

    golangci-lint prints one JSON document and may follow it with a
    summary such as "0 issues." or "3 issues:" plus a per-linter count.
    """
    text = report.strip()
    if not text:
        return 0
    try:
        data, end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"cannot read gocognit report: {err}") from err
    rest = text[end:].strip()
    if rest and not _issue_summary(rest):
        raise RuntimeError(
            f"cannot read gocognit report: unexpected trailing text: {rest}"
        )
    total = 0
    for issue in data.get("Issues") or []:
        if issue.get("FromLinter") != "gocognit":
            continue
        match = COGNITIVE_RE.search(issue.get("Text") or "")
        if match:
            total += int(match.group(1))
    return total


def measure_cognitive(base, cwd):
    """Run gocognit on functions changed since base. Return the summed complexity."""
    fd, config = tempfile.mkstemp(suffix=".yml", prefix="gocognit-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(GOCOGNIT_CONFIG)
        report = _capture(
            [
                "golangci-lint",
                "run",
                "--config",
                config,
                f"--new-from-rev={base}",
                "--issues-exit-code",
                "0",
            ],
            cwd=cwd,
        )
    finally:
        os.remove(config)
    return cognitive_total(report)


def measure_pull_request(pr):
    """Run gocognit on the pull request head, against its merge base."""
    root = _git_root()
    base_name, head = _pull_request_refs(pr)
    _capture(
        ["git", "fetch", "--quiet", pr.git_url, f"+pull/{pr.number}/head"],
        cwd=root,
    )
    fetched_head = _capture(["git", "rev-parse", "FETCH_HEAD"], cwd=root).strip()
    if fetched_head != head:
        raise RuntimeError("fetched pull request head does not match GitHub")
    _capture(
        ["git", "fetch", "--quiet", pr.git_url, f"+refs/heads/{base_name}"],
        cwd=root,
    )
    base_tip = _capture(["git", "rev-parse", "FETCH_HEAD"], cwd=root).strip()
    merge_base = _capture(
        ["git", "merge-base", fetched_head, base_tip],
        cwd=root,
    ).strip()
    checkout = tempfile.mkdtemp(prefix="pr-complexity-")
    try:
        _capture(
            ["git", "worktree", "add", "--detach", "--quiet", checkout, fetched_head],
            cwd=root,
        )
        return measure_cognitive(merge_base, checkout)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", checkout],
            check=False,
            capture_output=True,
            text=True,
            cwd=root,
        )
        shutil.rmtree(checkout, ignore_errors=True)


def _git_root():
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as err:
        raise RuntimeError(f"cannot find git repository: {err}") from err
    if proc.returncode != 0:
        detail = proc.stderr.strip() or "git rev-parse failed"
        raise RuntimeError(f"cannot find git repository: {detail}")
    return proc.stdout.strip()


def weights_from_args(args):
    """Build Weights from flags. Omitted flags keep the defaults."""
    return Weights(
        deletion=_parse_weight(
            args.deletion_weight, DELETION_WEIGHT, "deletion weight"
        ),
        added_knee=_parse_knee(args.added_knee, ADDED_KNEE, "added knee"),
        removed_knee=_parse_knee(args.removed_knee, REMOVED_KNEE, "removed knee"),
        files_at_max=_parse_span(args.files_at_max, FILE_AT_MAX, "files at max"),
        directories_at_max=_parse_span(
            args.directories_at_max, DIR_AT_MAX, "directories at max"
        ),
        cognitive=_parse_weight(
            args.cognitive_weight, COGNITIVE_WEIGHT, "cognitive weight"
        ),
    )


def _parse_weight(text, default, name):
    if text is None:
        return default
    try:
        value = float(text)
    except ValueError:
        raise UsageError(f"invalid {name}: {text}") from None
    if not 0 <= value < float("inf"):
        raise UsageError(f"invalid {name}: {text}")
    return value


def _parse_knee(text, default, name):
    """Return the line count where source growth starts to climb."""
    value = _parse_weight(text, default, name)
    if value < 1:
        shown = text if text is not None else value
        raise UsageError(f"invalid {name}: {shown}")
    return value


def _parse_span(text, default, name):
    """Return how many files or directories reach the medium ceiling."""
    value = _parse_weight(text, default, name)
    if value < 2:
        raise UsageError(f"invalid {name}: {text if text is not None else value}")
    return value


def _fail_usage(err):
    print(f"Error: {err}", file=sys.stderr)
    print(f"Run '{PROG_NAME} --help' for usage.", file=sys.stderr)
    return 2


def _score_link(argv):
    """Score argv's pull request. Raise UsageError or RuntimeError."""
    args = parse_arguments(argv)
    if args.help:
        print_help()
        return 0
    weights = weights_from_args(args)
    if not args.link:
        print_help()
        return 2
    pr = parse_pull_request(args.link)
    diff_text = pull_request_diff(pr)
    gocognit = measure_pull_request(pr)
    print_result(classify_diff(diff_text, weights, gocognit), pr.url)
    return 0


def main(argv=None):
    """CLI entry: score the pull request link and print its effort."""
    if argv is None:
        argv = sys.argv[1:]
    try:
        return _score_link(argv)
    except UsageError as err:
        return _fail_usage(err)
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1


def cli(argv=None):
    """Run main() and turn a usage or read failure into an exit status."""
    return main(argv)


if __name__ == "__main__":
    sys.exit(cli())
