#!/usr/bin/env python3
"""Apply allowlisted pull request labels.

The input is a GitHub pull request link and label names as separate
words, such as critical roadmap. Only labels named in
ALLOWLIST may be applied. Each name belongs to one type, such as
Priority. A pull request may have only one priority label.

The report always states every value. Roadmap is yes or no.
Priority is critical, high, medium, low, or not set. Feature is one
name from release-tools/features.yaml at the pull request head, or
not set. Each category is yes or no. A value is automatic unless
someone else added or removed that type. The report then says
overwritten by that person and the label is left unchanged.

The script's identity is the authenticated gh user. Otherwise the
labels of a type become the requested ones: requested labels are
added, and other allowlisted labels of that type are removed.
Labels outside the allowlist are not touched.

The first line is Labels: applied, override, or partial. The command
exits 0 after a report.
"""

# Hyphenated filename; this is a script, not a library. The CLI shape is
# shared with the other release-tools scripts on purpose.
# pylint: disable=invalid-name,duplicate-code

import argparse
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import urllib.parse
from typing import NamedTuple

PROG_NAME = "pr-labels.py"

# Labels this script may change, grouped by type. A human edit to any
# label in a type freezes that whole type.
ALLOWLIST = {
    "Roadmap": ("roadmap",),
    "Priority": ("critical", "high", "medium", "low"),
    "Category": (
        "bug-fix",
        "test-fix",
        "interface",
        "packaging",
        "systemd-services",
        "internal",
    ),
}

# Types that may have only one label on a pull request.
SINGLE_LABEL_TYPES = frozenset({"Priority"})

_FEATURES = None

PR_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"pull/(?P<number>[0-9]+)"
    r"(?:/(?:files|commits|checks))?"
    r"/?(?:\?[^#]*)?(?:#.*)?$"
)

_LABEL_EVENTS = frozenset({"labeled", "unlabeled"})


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


class TypeChange(NamedTuple):
    """What happened to one label type.

    status is applied, override, or ours. labels are the requested
    names when the type was applied. overrides are (label, login)
    pairs when someone else changed that label. value and note are
    the single-value report. lines are (label, yes or no) pairs for
    Category.
    """

    name: str
    status: str
    labels: tuple
    overrides: tuple
    remove: tuple
    add: tuple
    value: str = ""
    note: str = ""
    lines: tuple = ()


def _type_of(label):
    """Return the allowlist type that contains label, or empty."""
    for name, labels in ALLOWLIST.items():
        if label in labels:
            return name
    return ""


def parse_label_list(words):
    """Return label tokens from the words after the pull request link.

    The allowlist is checked later, once feature names are known.
    Two priority labels are rejected here.
    """
    if not words:
        raise UsageError("labels are required")
    labels = []
    for raw in words:
        label = str(raw).strip()
        if not label:
            raise UsageError("labels are required")
        if label not in labels:
            labels.append(label)
    priorities = [label for label in labels if _type_of(label) == "Priority"]
    if len(priorities) > 1:
        raise UsageError("only one priority label is allowed")
    return tuple(labels)


def resolve_labels(tokens, names):
    """Split tokens into static labels and one feature name.

    A token that is neither an allowlisted label nor a feature name
    raises UsageError. Two feature names raise UsageError.
    """
    known = set(names)
    static = []
    feature = []
    for label in tokens:
        if _type_of(label):
            static.append(label)
            continue
        if label in known:
            feature.append(label)
            continue
        raise UsageError(f"label is not allowed: {label}")
    if len(feature) > 1:
        raise UsageError("only one feature label is allowed")
    return tuple(static), tuple(feature)


def _features():
    """Load pr-feature.py. The hyphenated name is not an import path."""
    global _FEATURES  # pylint: disable=global-statement
    if _FEATURES is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pr-feature.py")
        spec = importlib.util.spec_from_file_location("pr_feature_for_labels", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _FEATURES = mod
    return _FEATURES


def feature_names(pr):
    """Return feature names in features.yaml at the pull request head."""
    mod = _features()
    _base, head = mod.pull_request_refs(pr)
    return tuple(mod.parse_features(mod.read_features(pr, head)))


def _desired(labels):
    """Return the requested labels grouped by allowlist type."""
    grouped = {name: [] for name in ALLOWLIST}
    for label in labels:
        grouped[_type_of(label)].append(label)
    return grouped


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


def github_login():
    """Return the login of the authenticated gh user."""
    values = _json_values(_capture(["gh", "api", "user"]), "github user")
    if len(values) != 1 or not isinstance(values[0], dict):
        raise RuntimeError("cannot read github user")
    login = values[0].get("login")
    if not isinstance(login, str) or not login:
        raise RuntimeError("cannot read github user")
    return login


def _label_names(payload):
    """Return label names from an issue payload."""
    if not isinstance(payload, dict):
        raise RuntimeError("cannot read pull request labels")
    labels = payload.get("labels")
    if not isinstance(labels, list):
        raise RuntimeError("cannot read pull request labels")
    names = []
    for label in labels:
        if isinstance(label, str) and label:
            names.append(label)
            continue
        if not isinstance(label, dict):
            raise RuntimeError("cannot read pull request labels")
        name = label.get("name")
        if not isinstance(name, str) or not name:
            raise RuntimeError("cannot read pull request labels")
        names.append(name)
    return names


def issue_labels(pr):
    """Return the label names currently on the pull request."""
    raw = _capture(["gh", "api", f"repos/{pr.slug}/issues/{pr.number}"])
    values = _json_values(raw, "pull request labels")
    if len(values) != 1:
        raise RuntimeError("cannot read pull request labels")
    return _label_names(values[0])


def _event_name(event):
    """Return the timeline event name, or empty."""
    if not isinstance(event, dict):
        return ""
    name = event.get("event")
    if isinstance(name, str):
        return name
    return ""


def _event_label(event):
    """Return the label name on a timeline event, or empty."""
    label = event.get("label")
    if isinstance(label, str):
        return label
    if not isinstance(label, dict):
        return ""
    name = label.get("name")
    if isinstance(name, str):
        return name
    return ""


def _event_actor(event):
    """Return the actor login, or empty when the event has none."""
    actor = event.get("actor")
    if not isinstance(actor, dict):
        return ""
    login = actor.get("login")
    if isinstance(login, str):
        return login
    return ""


def timeline(pr):
    """Return timeline events for the pull request."""
    raw = _capture(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{pr.slug}/issues/{pr.number}/timeline",
        ]
    )
    events = []
    for value in _json_values(raw, "pull request timeline"):
        if not isinstance(value, list):
            raise RuntimeError("cannot read pull request timeline")
        events.extend(value)
    return events


def _last_foreign_actor(events, type_labels, script_login):
    """Return the latest login other than the script that changed this type."""
    found = ""
    for event in events:
        if _event_name(event) not in _LABEL_EVENTS:
            continue
        if _event_label(event) not in type_labels:
            continue
        actor = _event_actor(event)
        if actor == script_login:
            continue
        found = actor or "unknown"
    return found


def _current_priority(present):
    """Return the priority label on the pull request, or No."""
    found = [label for label in ALLOWLIST["Priority"] if label in present]
    if not found:
        return "not set"
    return ", ".join(found)


def _priority_change(requested, present, events, script_login):
    """Return the priority change. Absence is not set.

    An addition or a removal by someone else leaves the current value
    unchanged and names that person. With no request the current value
    is reported and left unchanged.
    """
    labels = ALLOWLIST["Priority"]
    actor = _last_foreign_actor(events, labels, script_login)
    value = _current_priority(present)
    if actor:
        note = f"overwritten by {actor}"
        return TypeChange("Priority", "override", (), (), (), (), value, note)
    if not requested:
        return TypeChange("Priority", "ours", (), (), (), (), value, "automatic")
    wanted = set(requested)
    remove = tuple(
        label for label in labels if label in present and label not in wanted
    )
    add = tuple(label for label in requested if label not in present)
    return TypeChange(
        "Priority",
        "applied",
        requested,
        (),
        remove,
        add,
        requested[0],
        "automatic",
    )


def _current_feature(present, names):
    """Return the feature label on the pull request, or not set."""
    found = [label for label in names if label in present]
    if not found:
        return "not set"
    return ", ".join(found)


def _feature_change(requested, names, present, events, script_login):
    """Return the feature change. Absence is not set.

    An addition or a removal by someone else leaves the current value
    unchanged. With no request the current value is reported and left
    unchanged.
    """
    actor = _last_foreign_actor(events, names, script_login)
    if actor:
        value = _current_feature(present, names)
        note = f"overwritten by {actor}"
        return TypeChange("Feature", "override", (), (), (), (), value, note)
    if not requested:
        value = _current_feature(present, names)
        return TypeChange("Feature", "ours", (), (), (), (), value, "automatic")
    wanted = set(requested)
    remove = tuple(label for label in names if label in present and label not in wanted)
    add = tuple(label for label in requested if label not in present)
    return TypeChange(
        "Feature",
        "applied",
        requested,
        (),
        remove,
        add,
        requested[0],
        "automatic",
    )


def _roadmap_change(requested, present, events, script_login):
    """Return the Roadmap change. Absence is no."""
    label = ALLOWLIST["Roadmap"][0]
    actor = _last_foreign_actor(events, (label,), script_login)
    if actor:
        value = "yes" if label in present else "no"
        note = f"overwritten by {actor}"
        return TypeChange("Roadmap", "override", (), (), (), (), value, note)
    if requested:
        add = () if label in present else (label,)
        return TypeChange(
            "Roadmap", "applied", (label,), (), (), add, "yes", "automatic"
        )
    value = "yes" if label in present else "no"
    return TypeChange("Roadmap", "ours", (), (), (), (), value, "automatic")


def _category_lines(present, wanted=None):
    """Return (label, yes or no) for every category, in allowlist order."""
    labels = ALLOWLIST["Category"]
    if wanted is None:
        chosen = present
    else:
        chosen = wanted
    return tuple((label, "yes" if label in chosen else "no") for label in labels)


def _category_change(requested, present, events, script_login):
    """Return every category as yes or no.

    An addition or a removal by someone else leaves the current labels
    unchanged. With no request the current labels are reported and left
    unchanged. A request sets those labels to yes and the rest to no.
    """
    labels = ALLOWLIST["Category"]
    actor = _last_foreign_actor(events, labels, script_login)
    if actor:
        note = f"overwritten by {actor}"
        lines = _category_lines(present)
        return TypeChange("Category", "override", (), (), (), (), "", note, lines)
    if not requested:
        lines = _category_lines(present)
        return TypeChange("Category", "ours", (), (), (), (), "", "automatic", lines)
    wanted = set(requested)
    remove = tuple(
        label for label in labels if label in present and label not in wanted
    )
    add = tuple(label for label in requested if label not in present)
    lines = _category_lines(present, wanted)
    return TypeChange(
        "Category", "applied", requested, (), remove, add, "", "automatic", lines
    )


def plan_changes(labels, current, events, script_login, features=None):
    """Decide which types to apply and which to leave unchanged.

    features is (names, requested). names are the feature labels allowed
    on this pull request. requested is the one name from the command.
    """
    if features is None:
        features = ((), ())
    names, feature_request = features
    desired = _desired(labels)
    present = set(current)
    changes = []
    for name in ALLOWLIST:
        requested = tuple(desired[name])
        if name == "Roadmap":
            changes.append(_roadmap_change(requested, present, events, script_login))
        elif name == "Priority":
            changes.append(_priority_change(requested, present, events, script_login))
            changes.append(
                _feature_change(feature_request, names, present, events, script_login)
            )
        elif name == "Category":
            changes.append(_category_change(requested, present, events, script_login))
    return tuple(changes)


def _endpoint(pr, suffix):
    """Return a gh api path under this pull request's issue."""
    return f"repos/{pr.slug}/issues/{pr.number}{suffix}"


def apply_changes(pr, changes):
    """Add and remove labels for types that were not overridden."""
    for change in changes:
        for label in change.remove:
            quoted = urllib.parse.quote(label, safe="")
            _capture(
                ["gh", "api", "--method", "DELETE", _endpoint(pr, f"/labels/{quoted}")]
            )
        if not change.add:
            continue
        body = json.dumps({"labels": list(change.add)})
        _capture(
            ["gh", "api", "--method", "POST", "--input", "-", _endpoint(pr, "/labels")],
            stdin=body,
        )


def label_report(pr, link, words):
    """Apply words, or report the current labels when words is empty.

    The returned text is the same report the command prints.
    """
    tokens = parse_label_list(words) if words else ()
    names = feature_names(pr)
    if tokens:
        labels, feature_request = resolve_labels(tokens, names)
    else:
        labels, feature_request = (), ()
    changes = plan_changes(
        labels,
        set(issue_labels(pr)),
        timeline(pr),
        github_login(),
        (names, feature_request),
    )
    apply_changes(pr, changes)
    buf = io.StringIO()
    print_result(link, changes, buf)
    return buf.getvalue()


def _headline(changes):
    """Return applied, override, or partial for the report headline.

    An automatic Roadmap value does not change the headline.
    """
    statuses = {change.status for change in changes if change.status != "ours"}
    if not statuses or statuses == {"applied"}:
        return "applied"
    if statuses == {"override"}:
        return "override"
    return "partial"


def print_result(link, changes, out=None):
    """Print the label result, then one block per type.

    The first line is always "Labels: <applied, override, or partial>".
    Roadmap is "yes" or "no". Priority is a level or "not set".
    Feature is a name or "not set". Each category line is "<label>: yes|no".
    """
    if out is None:
        out = sys.stdout
    print(f"Labels: {_headline(changes)}", file=out)
    print(file=out)
    print("Details:", file=out)
    print(f"Pull request: {link}", file=out)
    for change in changes:
        if change.lines:
            print(f"{change.name}:", file=out)
            for label, value in change.lines:
                print(f"  {label}: {value} ({change.note})", file=out)
            continue
        print(f"{change.name}: {change.value} ({change.note})", file=out)


def print_help(out=None):
    """Print usage, the allowlist, and the freeze rule."""
    if out is None:
        out = sys.stdout
    prog = PROG_NAME
    flags = (("  -h, --help", "Help for pr-labels"),)
    width = max(len(name) for name, _desc in flags)
    print("Apply allowlisted labels to a pull request.", file=out)
    print(file=out)
    print("Each label is a separate word. With no labels, the command", file=out)
    print("reports the current values and changes nothing. The command", file=out)
    print("prints the result and exits 0.", file=out)
    print("Only one priority label may be set.", file=out)
    print("The report always states every value. Roadmap is yes or no.", file=out)
    print("A priority is critical, high, medium, low, or not set.", file=out)
    print("A feature is one name from release-tools/features.yaml at", file=out)
    print("the pull request head, or not set. Only one feature label", file=out)
    print("may be set. Each category is yes or no. A value is", file=out)
    print("automatic unless someone else added or removed that", file=out)
    print("type. The report says overwritten by that person, and", file=out)
    print("the label is left unchanged.", file=out)
    print(file=out)
    print("Allowlist:", file=out)
    for name, labels in ALLOWLIST.items():
        print(f"  {name}: {', '.join(labels)}", file=out)
    print(file=out)
    print("Usage:", file=out)
    print(f"  {prog} <pull-request> [label...]", file=out)
    print(file=out)
    print("Examples:", file=out)
    example = f"  {prog} https://github.com/canonical/snapd/pull/17718 critical roadmap"
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
    parser.add_argument("labels", nargs="*")
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
    """CLI entry: apply the requested allowlisted labels."""
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
        if args.labels:
            parse_label_list(args.labels)
        pr = parse_pull_request(args.link)
        text = label_report(pr, args.link, args.labels)
    except UsageError as err:
        return _fail_usage(err)
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1

    print(text, end="")
    return 0


def cli(argv=None):
    """Run main() and turn a usage or read failure into an exit status."""
    return main(argv)


if __name__ == "__main__":
    sys.exit(cli())
