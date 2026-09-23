#!/usr/bin/env python3
"""Early snapd deb verification against a Launchpad PPA.

Selects active Ubuntu series, rewrites changelog headers for a
per-run version, waits for Launchpad builds, triggers autopkgtests,
and renders a failure summary. Network access is injected so the
decision logic can be tested offline.
"""

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO

PACKAGING_SPLIT = (26, 4)
PACKAGE = "snapd"
SUCCESS_BUILD = "Successfully built"
FAIL_BUILDS = {
    "Failed to build",
    "Failed to upload",
    "Chroot problem",
    "Cancelled build",
    "Build for superseded Source",
}
BAD_PUBLICATION = {"Deleted", "Obsolete", "Superseded"}
PASS_TEST = {"PASS", "SKIP"}
LP_API = "https://api.launchpad.net/1.0"
ADT_REQUEST = "https://autopkgtest.ubuntu.com/request.cgi"
_HEADER = re.compile(
    r"^(?P<source>\S+) \((?P<version>[^)]+)\) (?P<distribution>[^;]+);(?P<rest>.*)$"
)
_RUN_ID = re.compile(r"(\d{8}_\d{6}_[0-9a-fA-F]+)@")
_UNSUPPORTED_ARCH = (
    "unknown architecture",
    "invalid architecture",
    "not a valid architecture",
    "unsupported architecture",
    "architecture not found",
    "bad architecture",
    "no workers",
)


class HTTPStatus(Exception):
    def __init__(self, status, url, body):
        super().__init__("HTTP %s for %s" % (status, url))
        self.status = status
        self.url = url
        self.body = body


def ubuntu_version_string(text):
    """Return YY.MM from distro-info output such as '22.04 LTS'."""
    match = re.search(r"(\d+)\.(\d+)", text or "")
    if not match:
        raise ValueError("cannot parse Ubuntu version from %r" % (text,))
    return "%s.%s" % (match.group(1), match.group(2))


def _version_tuple(ubuntu_version):
    text = ubuntu_version_string(ubuntu_version)
    major, minor = text.split(".")
    return int(major), int(minor)


def packaging_for(ubuntu_version):
    """Packaging directory name for an Ubuntu release version."""
    if _version_tuple(ubuntu_version) >= PACKAGING_SPLIT:
        return "ubuntu-26.04"
    return "ubuntu-16.04"


def upstream_version(changelog_version):
    """Debian upstream piece of a native changelog version."""
    return re.split(r"[+~-]", changelog_version, maxsplit=1)[0]


def package_version(upstream, ubuntu_version, pr_number, sha, run_id):
    """Version that sorts before the official upload and is unique per run.

    Example: 2.78+ubuntu24.04~pr17572.g0123456789ab.4242
    """
    short = (sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{12,64}", short):
        raise ValueError("commit sha must be at least 12 hexadecimal characters")
    short = short[:12]
    if not re.fullmatch(r"[1-9][0-9]*", str(pr_number)):
        raise ValueError("pull request number must be a positive integer")
    if not re.fullmatch(r"[1-9][0-9]*", str(run_id)):
        raise ValueError("run id must be a positive integer")
    ubuntu = ubuntu_version_string(ubuntu_version)
    if not upstream:
        raise ValueError("upstream version is empty")
    return "%s+ubuntu%s~pr%s.g%s.%s" % (upstream, ubuntu, pr_number, short, run_id)


def changelog_header_version(text):
    """Return the version from the first changelog header line."""
    line = (text or "").splitlines()[0] if text else ""
    match = _HEADER.match(line)
    if not match:
        raise ValueError("changelog does not start with a Debian header")
    return match.group("version")


def rewrite_changelog_header(text, version, distribution):
    """Replace only the first changelog header's version and distribution."""
    if text is None:
        raise ValueError("changelog is empty")
    newline = "\n" if text.endswith("\n") or text == "" else ""
    lines = text.splitlines()
    if not lines:
        raise ValueError("changelog is empty")
    match = _HEADER.match(lines[0])
    if not match:
        raise ValueError("changelog does not start with a Debian header")
    lines[0] = "%s (%s) %s;%s" % (
        match.group("source"),
        version,
        distribution,
        match.group("rest"),
    )
    return "\n".join(lines) + ("\n" if text.endswith("\n") else newline)


def _lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def discover_series(run):
    """Active Ubuntu series from distro-info, including the devel series.

    ``run(args)`` returns the command stdout. Supported series and the
    devel series are de-duplicated, preserving supported order.
    """
    supported = _lines(run(["ubuntu-distro-info", "--supported"]))
    devel = _lines(run(["ubuntu-distro-info", "--devel"]))
    names = []
    for name in supported + devel:
        if name not in names:
            names.append(name)
    entries = []
    for name in names:
        release = run(["ubuntu-distro-info", "--series", name, "--release"])
        version = ubuntu_version_string(release)
        entries.append({
            "series": name,
            "ubuntu_version": version,
            "packaging": packaging_for(version),
        })
    return entries


def command_stdout(args):
    completed = subprocess.run(
        args, check=True, text=True, capture_output=True,
    )
    return completed.stdout


def build_version_plan(series_entries, changelog_for, pr_number, sha, run_id):
    """Attach an upstream version and a unique upload version to each series.

    ``changelog_for(packaging)`` returns the changelog text for that
    packaging directory.
    """
    cache = {}
    plan = []
    for entry in series_entries:
        packaging = entry["packaging"]
        if packaging not in cache:
            cache[packaging] = upstream_version(
                changelog_header_version(changelog_for(packaging))
            )
        version = package_version(
            cache[packaging], entry["ubuntu_version"], pr_number, sha, run_id,
        )
        item = dict(entry)
        item["upstream"] = cache[packaging]
        item["version"] = version
        plan.append(item)
    return plan


def validate_request(head_repo, head_sha, pr_number, run_id, ppa):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", head_repo or ""):
        raise ValueError("head repository must be owner/name")
    if not re.fullmatch(r"[0-9a-fA-F]{12,64}", head_sha or ""):
        raise ValueError("head sha must be hexadecimal")
    if not re.fullmatch(r"[1-9][0-9]*", str(pr_number)):
        raise ValueError("pull request number must be a positive integer")
    if not re.fullmatch(r"[1-9][0-9]*", str(run_id)):
        raise ValueError("run id must be a positive integer")
    split_ppa(ppa)


def split_ppa(ppa):
    """Return (owner, archive) from 'snappy-dev/beta'."""
    parts = (ppa or "").split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("PPA must be owner/name")
    if not re.fullmatch(r"[A-Za-z0-9_+.-]+", parts[0]):
        raise ValueError("PPA owner is not a Launchpad name")
    if not re.fullmatch(r"[A-Za-z0-9_+.-]+", parts[1]):
        raise ValueError("PPA name is not a Launchpad name")
    return parts[0], parts[1]


def pull_request_head(repo, pr_number, run=command_stdout):
    stdout = run([
        "gh", "api", "repos/%s/pulls/%s" % (repo, pr_number),
        "--jq", ".head.sha",
    ])
    return stdout.strip()


def tail_text(text, lines=80, limit=4000):
    chunk = "\n".join((text or "").splitlines()[-lines:])
    if len(chunk) > limit:
        chunk = chunk[-limit:]
    return chunk


def append_record(path, record):
    rows = []
    if path and os.path.exists(path) and os.path.getsize(path):
        with open(path, "r", encoding="utf-8") as handle:
            rows = json.load(handle)
    rows.append(record)
    _write_json(path, rows)
    return rows


def _write_json(path, payload):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def skipped_report(reason, ppa="snappy-dev/beta"):
    owner, archive = split_ppa(ppa)
    return {
        "ok": True,
        "skipped": True,
        "skip_reason": reason,
        "timed_out": False,
        "ppa": ppa,
        "owner": owner,
        "archive": archive,
        "sources": [],
        "uploads": [],
        "builds": [],
    }


def _not_run_upload(spec, error):
    return {
        "series": spec["series"],
        "version": spec["version"],
        "ok": False,
        "error": error,
    }


def _not_run_build(spec, state):
    return {
        "series": spec["series"],
        "version": spec["version"],
        "architecture": "-",
        "state": state,
        "log_url": "",
        "ok": False,
    }


def assemble_build_report(versions, sources, uploads, builds, ppa="snappy-dev/beta",
                          timed_out=False, error=""):
    """Combine stage records into one build report.

    Series that never reached upload or build are recorded as not run
    so the summary can name them.
    """
    owner, archive = split_ppa(ppa)
    sources = list(sources or [])
    uploads = list(uploads or [])
    builds = list(builds or [])
    upload_by_series = {item["series"]: item for item in uploads}
    build_series = {item["series"] for item in builds}
    failed_sources = [item for item in sources if not item.get("ok")]
    source_error = "not run: source package failed"
    for spec in versions or []:
        if spec["series"] in upload_by_series:
            continue
        reason = source_error if failed_sources else "not run"
        upload_by_series[spec["series"]] = _not_run_upload(spec, reason)
    for spec in versions or []:
        if spec["series"] in build_series:
            continue
        builds.append(_not_run_build(spec, "not run"))
    uploads_out = [upload_by_series[spec["series"]] for spec in (versions or [])
                   if spec["series"] in upload_by_series]
    # Preserve upload records that were not in the version plan.
    known = {item["series"] for item in uploads_out}
    for item in uploads:
        if item["series"] not in known:
            uploads_out.append(item)
    ok = True
    if not versions:
        ok = False
    if any(not item.get("ok") for item in sources):
        ok = False
    if any(not item.get("ok") for item in uploads_out):
        ok = False
    if any(not item.get("ok") for item in builds):
        ok = False
    if timed_out or error:
        ok = False
    return {
        "ok": ok,
        "skipped": False,
        "skip_reason": "",
        "timed_out": timed_out,
        "error": error,
        "ppa": ppa,
        "owner": owner,
        "archive": archive,
        "sources": sources,
        "uploads": uploads_out,
        "builds": builds,
    }


def publications_payload(report):
    """Slim JSON the autopkgtest workflow consumes."""
    by_series = {}
    for build in report.get("builds") or []:
        if not build.get("ok"):
            continue
        if build.get("architecture") in ("", "-"):
            continue
        key = (build["series"], build["version"])
        by_series.setdefault(key, [])
        if build["architecture"] not in by_series[key]:
            by_series[key].append(build["architecture"])
    publications = []
    for (series, version), arches in by_series.items():
        upload_ok = True
        for upload in report.get("uploads") or []:
            if upload.get("series") == series and not upload.get("ok"):
                upload_ok = False
        if not upload_ok:
            continue
        publications.append({
            "series": series,
            "version": version,
            "architectures": arches,
        })
    return {
        "owner": report.get("owner", ""),
        "ppa": report.get("archive", ""),
        "package": PACKAGE,
        "publications": publications,
    }


def _excerpt(text, limit=1500):
    chunk = tail_text(text or "", lines=40, limit=limit)
    if not chunk:
        return ""
    return "\n```\n%s\n```\n" % chunk


def _link(url, label):
    if not url:
        return label
    return "[%s](%s)" % (label, url)


def render_summary(build, autopkgtest, build_only=False):
    """Return (markdown, ok).

    ``autopkgtest`` is None when that stage did not produce a report.
    A superseded build is a successful no-op. ``build_only`` is the
    build workflow's own summary: autopkgtests are a separate workflow.
    """
    if not build:
        text = "## Deb verification\n\nBuild report is missing.\n"
        return text, False
    if build.get("skipped"):
        reason = build.get("skip_reason") or "a newer commit is current"
        text = "## Deb verification\n\nSuperseded: %s.\n\nAutopkgtests were not run.\n" % reason
        return text, True

    lines = ["## Deb verification", ""]
    if build_only:
        ok = bool(build.get("ok"))
    else:
        ok = report_failed(build, autopkgtest) is None

    lines.append("### Source packages")
    lines.append("")
    if not build.get("sources"):
        lines.append("- no source packages were recorded")
    for item in build.get("sources") or []:
        label = item.get("packaging") or "unknown"
        if item.get("series"):
            label = "%s / %s" % (label, item["series"])
        if item.get("ok"):
            lines.append("- %s: ok" % label)
        else:
            lines.append("- %s: failed" % label)
            excerpt = _excerpt(item.get("error"))
            if excerpt:
                lines.append(excerpt.rstrip())
    lines.append("")
    lines.append("### Uploads")
    lines.append("")
    if not build.get("uploads"):
        lines.append("- no uploads were recorded")
    for item in build.get("uploads") or []:
        if item.get("ok"):
            lines.append("- %s `%s`: accepted" % (item.get("series"), item.get("version")))
        else:
            lines.append("- %s `%s`: failed" % (item.get("series"), item.get("version")))
            excerpt = _excerpt(item.get("error"))
            if excerpt:
                lines.append(excerpt.rstrip())
    lines.append("")
    lines.append("### Launchpad builds")
    lines.append("")
    if build.get("timed_out"):
        lines.append("Timed out waiting for Launchpad.")
        lines.append("")
    if build.get("error"):
        lines.append(build["error"])
        lines.append("")
    if not build.get("builds"):
        lines.append("- no builds were recorded")
    for item in build.get("builds") or []:
        state = item.get("state") or "unknown"
        where = "%s/%s" % (item.get("series"), item.get("architecture"))
        if item.get("log_url"):
            lines.append("- %s: %s (%s)" % (where, state, _link(item["log_url"], "log")))
        else:
            lines.append("- %s: %s" % (where, state))
    lines.append("")
    lines.append("### Autopkgtests")
    lines.append("")
    if build_only and build.get("ok"):
        lines.append("Reported separately by the autopkgtest workflow.")
    else:
        lines.extend(_autopkgtest_lines(build, autopkgtest))
    return "\n".join(lines).rstrip() + "\n", ok


def report_failed(build, autopkgtest):
    """Return a short failure reason, or None when the run passed."""
    if not build:
        return "build report is missing"
    if build.get("skipped"):
        return None
    if not build.get("ok"):
        return "build stage failed"
    if autopkgtest is None:
        return "autopkgtest report is missing"
    if autopkgtest.get("status") == "not-run" or not autopkgtest.get("ok"):
        return autopkgtest.get("reason") or "autopkgtests failed"
    return None


def render_autopkgtest_only(report):
    """Summary for a standalone autopkgtest workflow run."""
    lines = ["## Autopkgtests", ""]
    if report is None:
        lines.append("Autopkgtest report is missing.")
        ok = False
    else:
        lines.extend(_autopkgtest_lines({"ok": True}, report))
        ok = bool(report.get("ok"))
    return "\n".join(lines).rstrip() + "\n", ok


def _autopkgtest_lines(build, autopkgtest):
    if not build.get("ok"):
        return ["Not run because source packages, the upload, or Launchpad builds failed."]
    if autopkgtest is None:
        return ["Autopkgtest report is missing."]
    if autopkgtest.get("status") == "not-run":
        return ["Not run. %s" % (autopkgtest.get("reason") or "")]
    lines = []
    if autopkgtest.get("error"):
        lines.append(autopkgtest["error"])
        lines.append("")
    results = autopkgtest.get("results") or []
    if not results:
        lines.append("- no autopkgtest results were recorded")
    for item in results:
        where = "%s/%s" % (item.get("series"), item.get("architecture"))
        state = item.get("state") or "unknown"
        if item.get("log_url"):
            lines.append("- %s: %s (%s)" % (where, state, _link(item["log_url"], "log")))
        else:
            lines.append("- %s: %s" % (where, state))
        detail = (item.get("detail") or "").strip()
        if detail and state != "pass":
            lines.append("")
            lines.append(_excerpt(detail).rstrip())
    return lines


def _collection(fetch_json, url):
    entries = []
    seen = set()
    while url and url not in seen:
        seen.add(url)
        payload = fetch_json(url)
        if not isinstance(payload, dict):
            break
        entries.extend(payload.get("entries") or [])
        url = payload.get("next_collection_link")
    return entries


def published_sources_url(owner, archive, version, series):
    params = urllib.parse.urlencode({
        "ws.op": "getPublishedSources",
        "source_name": PACKAGE,
        "exact_match": "true",
        "version": version,
        "distro_series": "%s/ubuntu/%s" % (LP_API, series),
    })
    return "%s/~%s/+archive/ubuntu/%s?%s" % (LP_API, owner, archive, params)


def _latest_by_arch(entries):
    chosen = {}
    for entry in entries:
        arch = entry.get("arch_tag") or "unknown"
        current = chosen.get(arch)
        stamp = entry.get("datebuilt") or entry.get("datecreated") or ""
        if current is None:
            chosen[arch] = entry
            continue
        current_stamp = current.get("datebuilt") or current.get("datecreated") or ""
        if stamp >= current_stamp:
            chosen[arch] = entry
    return chosen


def _build_record(series, version, entry):
    state = entry.get("buildstate") or "unknown"
    return {
        "series": series,
        "version": version,
        "architecture": entry.get("arch_tag") or "unknown",
        "state": state,
        "log_url": entry.get("build_log_url") or "",
        "ok": state == SUCCESS_BUILD,
    }


def snapshot_builds(fetch_json, owner, archive, wanted):
    """One Launchpad poll.

    ``wanted`` is a list of ``{"series", "version"}`` for uploads that
    were accepted. Returns done=True only when every series has reached
    a terminal result.
    """
    records = []
    done = True
    ok = True
    for item in wanted:
        series = item["series"]
        version = item["version"]
        url = published_sources_url(owner, archive, version, series)
        pubs = _collection(fetch_json, url)
        if not pubs:
            done = False
            ok = False
            continue
        pub = pubs[0]
        status = pub.get("status") or ""
        if status in BAD_PUBLICATION:
            records.append({
                "series": series,
                "version": version,
                "architecture": "-",
                "state": "publication %s" % status,
                "log_url": pub.get("self_link") or "",
                "ok": False,
            })
            ok = False
            continue
        link = pub.get("self_link")
        if not link:
            done = False
            ok = False
            continue
        builds = _latest_by_arch(_collection(
            fetch_json, link + "?ws.op=getBuilds",
        ))
        if not builds:
            done = False
            ok = False
            continue
        for entry in builds.values():
            record = _build_record(series, version, entry)
            records.append(record)
            state = record["state"]
            if state == SUCCESS_BUILD:
                continue
            if state in FAIL_BUILDS:
                ok = False
                continue
            done = False
            ok = False
    if done and not records and wanted:
        done = False
        ok = False
    return {"done": done, "ok": ok and done, "timed_out": False, "builds": records, "error": ""}


def mark_build_timeout(snapshot, wanted):
    snapshot = dict(snapshot)
    snapshot["done"] = True
    snapshot["ok"] = False
    snapshot["timed_out"] = True
    seen = {(item["series"], item.get("architecture")) for item in snapshot.get("builds") or []}
    builds = []
    for item in snapshot.get("builds") or []:
        record = dict(item)
        if record.get("state") != SUCCESS_BUILD:
            record["ok"] = False
            if "timed out" not in (record.get("state") or ""):
                record["state"] = "%s (timed out)" % record.get("state")
        builds.append(record)
    present_series = {item["series"] for item in builds}
    for item in wanted:
        if item["series"] in present_series:
            continue
        if (item["series"], "-") in seen:
            continue
        builds.append({
            "series": item["series"],
            "version": item["version"],
            "architecture": "-",
            "state": "not published (timed out)",
            "log_url": "",
            "ok": False,
        })
    snapshot["builds"] = builds
    if not snapshot.get("error"):
        snapshot["error"] = "timed out waiting for Launchpad builds"
    return snapshot


def poll_builds(fetch_json, owner, archive, wanted, timeout, interval,
                sleep=time.sleep, monotonic=time.monotonic):
    if not wanted:
        return {"done": True, "ok": True, "timed_out": False, "builds": [], "error": ""}
    deadline = monotonic() + timeout
    last = {"done": False, "ok": False, "timed_out": False, "builds": [], "error": ""}
    while True:
        try:
            last = snapshot_builds(fetch_json, owner, archive, wanted)
        except HTTPStatus as exc:
            if exc.status not in (429, 500, 502, 503):
                raise
            last = {
                "done": False,
                "ok": False,
                "timed_out": False,
                "builds": last.get("builds") or [],
                "error": str(exc),
            }
        if last.get("done"):
            return last
        if monotonic() >= deadline:
            return mark_build_timeout(last, wanted)
        sleep(interval)


def submit_url(series, arch, version, owner, archive, package=PACKAGE):
    query = urllib.parse.urlencode({
        "release": series,
        "arch": arch,
        "package": package,
        "ppa": "%s/%s" % (owner, archive),
        "trigger": "%s/%s" % (package, version),
    }, quote_via=urllib.parse.quote)
    return "%s?%s" % (ADT_REQUEST, query)


def classify_submit(status, body):
    """Return submitted, skipped, or error."""
    text = (body or "").lower()
    if status in (200, 202, 302) and (
        "submitted" in text or "queued" in text or "request accepted" in text
    ):
        return "submitted"
    if any(marker in text for marker in _UNSUPPORTED_ARCH):
        return "skipped"
    if status == 400 and "architecture" in text:
        return "skipped"
    return "error"


def html_excerpt(body, limit=500):
    text = re.sub(r"<[^>]+>", " ", body or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def parse_run_ids(listing):
    found = []
    for run_id in _RUN_ID.findall(listing or ""):
        if run_id not in found:
            found.append(run_id)
    return found


def parse_autopkgtest_summary(text):
    rows = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        rows.append((parts[0], parts[1]))
    return rows


def summary_state(summary_text, exitcode):
    """Return (state, detail) where state is pass or fail."""
    rows = parse_autopkgtest_summary(summary_text)
    failed = ["%s %s" % (name, status) for name, status in rows if status not in PASS_TEST]
    code = (exitcode or "").strip()
    if failed:
        return "fail", ", ".join(failed)
    if code not in ("", "0"):
        return "fail", "exitcode %s" % code
    if not rows and code != "0":
        return "fail", "empty autopkgtest summary"
    return "pass", ", ".join("%s %s" % (name, status) for name, status in rows)


def results_prefix(series, owner, archive, arch, package=PACKAGE):
    return (
        "https://autopkgtest.ubuntu.com/results/"
        "autopkgtest-%s-%s-%s/%s/%s/%s/%s/"
        % (series, owner, archive, series, arch, package[0], package)
    )


def read_result_tar(data):
    """Pull summary, exitcode, and any text members from result.tar."""
    summary = ""
    exitcode = ""
    blobs = []
    with tarfile.open(fileobj=BytesIO(data), mode="r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            raw = extracted.read()
            name = os.path.basename(member.name)
            text = raw.decode("utf-8", "replace")
            if name == "summary":
                summary = text
            elif name == "exitcode":
                exitcode = text
            if len(text) <= 200000:
                blobs.append(text)
    return {"summary": summary, "exitcode": exitcode, "text": "\n".join(blobs)}


def version_in_text(text, version):
    return bool(version) and version in (text or "")


def autopkgtest_log_url(series, owner, archive, arch, run_id, package=PACKAGE):
    return results_prefix(series, owner, archive, arch, package) + run_id + "@/log.gz"


def not_run_autopkgtest(reason):
    return {
        "ok": False,
        "status": "not-run",
        "reason": reason,
        "error": "",
        "results": [],
    }


def _result_record(series, version, arch, state, log_url, detail):
    return {
        "series": series,
        "version": version,
        "architecture": arch,
        "state": state,
        "log_url": log_url,
        "detail": detail,
        "ok": state in ("pass", "skipped"),
    }


def assess_autopkgtest(results):
    tested = [item for item in results if item.get("state") != "skipped"]
    ok = bool(tested) and all(item.get("ok") for item in tested)
    if ok:
        reason = ""
        status = "passed"
    elif not tested:
        reason = "no autopkgtest architectures were accepted"
        status = "failed"
    else:
        reason = "autopkgtests failed"
        status = "failed"
    return {
        "ok": ok,
        "status": status,
        "reason": reason,
        "error": "",
        "results": results,
    }


def _match_run(client, item, listing):
    """Return (run_id, result) for the newest run that contains this version."""
    for run_id in sorted(parse_run_ids(listing), reverse=True):
        fetched = client.fetch_result(item["series"], item["architecture"], run_id)
        if not fetched:
            continue
        blob = (fetched.get("text") or "") + "\n" + (fetched.get("summary") or "")
        if not version_in_text(blob, item["version"]) and hasattr(client, "fetch_log"):
            blob = blob + "\n" + (client.fetch_log(
                item["series"], item["architecture"], run_id,
            ) or "")
        if version_in_text(blob, item["version"]):
            return run_id, fetched
    return None


def poll_autopkgtests(client, publications, timeout, interval,
                      sleep=time.sleep, monotonic=time.monotonic):
    """Submit autopkgtests and wait until each requested run finishes.

    ``client.submit(url)`` returns ``(status, body)``.
    ``client.list_runs(series, arch)`` returns a listing string.
    ``client.fetch_result(series, arch, run_id)`` returns a dict with
    summary, exitcode, and text, or None when the result is not ready.
    ``publications`` is the slim payload from :func:`publications_payload`.
    """
    owner = publications["owner"]
    archive = publications["ppa"]
    pending = []
    results = []
    for pub in publications.get("publications") or []:
        for arch in pub.get("architectures") or []:
            url = submit_url(pub["series"], arch, pub["version"], owner, archive)
            status, body = client.submit(url)
            kind = classify_submit(status, body)
            if kind == "skipped":
                results.append(_result_record(
                    pub["series"], pub["version"], arch, "skipped", url,
                    html_excerpt(body) or "architecture not supported",
                ))
                continue
            if kind == "error":
                results.append(_result_record(
                    pub["series"], pub["version"], arch, "error", url,
                    "HTTP %s %s" % (status, html_excerpt(body)),
                ))
                continue
            pending.append({
                "series": pub["series"],
                "version": pub["version"],
                "architecture": arch,
            })
    if not pending:
        return assess_autopkgtest(results)

    deadline = monotonic() + timeout
    while pending:
        still = []
        for item in pending:
            listing = client.list_runs(item["series"], item["architecture"])
            matched = _match_run(client, item, listing)
            if matched is None:
                still.append(item)
                continue
            run_id, fetched = matched
            state, detail = summary_state(
                fetched.get("summary") or "", fetched.get("exitcode") or "",
            )
            log_url = fetched.get("log_url") or autopkgtest_log_url(
                item["series"], owner, archive, item["architecture"], run_id,
            )
            results.append(_result_record(
                item["series"], item["version"], item["architecture"],
                state, log_url, detail,
            ))
        pending = still
        if not pending:
            break
        if monotonic() >= deadline:
            for item in pending:
                results.append(_result_record(
                    item["series"], item["version"], item["architecture"],
                    "timeout", "", "timed out waiting for autopkgtest results",
                ))
            break
        sleep(interval)
    return assess_autopkgtest(results)


def http_request(url, headers=None, timeout=60):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def launchpad_fetch(url, timeout=60):
    status, body = http_request(url, headers={
        "Accept": "application/json",
        "User-Agent": "snapd-deb-verify",
    }, timeout=timeout)
    text = body.decode("utf-8", "replace")
    if status >= 400:
        raise HTTPStatus(status, url, text)
    if not text:
        return {"entries": []}
    return json.loads(text)


class AutopkgtestClient(object):
    def __init__(self, owner, archive, api_key="", timeout=60):
        self.owner = owner
        self.archive = archive
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self):
        headers = {"User-Agent": "snapd-deb-verify"}
        if self.api_key:
            headers["Cookie"] = "X-Api-Key=%s" % self.api_key
        return headers

    def submit(self, url):
        status, body = http_request(url, headers=self._headers(), timeout=self.timeout)
        return status, body.decode("utf-8", "replace")

    def list_runs(self, series, arch):
        url = results_prefix(series, self.owner, self.archive, arch)
        status, body = http_request(url, headers=self._headers(), timeout=self.timeout)
        if status == 404:
            return ""
        if status >= 400:
            raise HTTPStatus(status, url, body.decode("utf-8", "replace"))
        return body.decode("utf-8", "replace")

    def fetch_result(self, series, arch, run_id):
        prefix = results_prefix(series, self.owner, self.archive, arch)
        url = prefix + run_id + "@/result.tar"
        status, body = http_request(url, headers=self._headers(), timeout=self.timeout)
        if status == 404:
            return None
        if status >= 400:
            raise HTTPStatus(status, url, body.decode("utf-8", "replace"))
        try:
            parsed = read_result_tar(body)
        except tarfile.TarError:
            return None
        parsed["log_url"] = autopkgtest_log_url(
            series, self.owner, self.archive, arch, run_id,
        )
        return parsed

    def fetch_log(self, series, arch, run_id):
        url = autopkgtest_log_url(series, self.owner, self.archive, arch, run_id)
        status, body = http_request(url, headers=self._headers(), timeout=self.timeout)
        if status >= 400:
            return ""
        try:
            text = gzip.decompress(body).decode("utf-8", "replace")
        except OSError:
            text = body.decode("utf-8", "replace")
        return text[:200000]


def _die(message):
    print(message, file=sys.stderr)
    return 2


def _cmd_series(args):
    entries = discover_series(command_stdout)
    _emit(entries, args.write)
    return 0


def _changelog_text(tree, packaging):
    path = os.path.join(tree, "packaging", packaging, "changelog")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _cmd_versions(args):
    series_entries = _read_json(args.series)
    plan = build_version_plan(
        series_entries,
        lambda packaging: _changelog_text(args.tree, packaging),
        args.pr,
        args.sha,
        args.run_id,
    )
    _emit(plan, args.write)
    return 0


def _cmd_rewrite(args):
    with open(args.changelog, "r", encoding="utf-8") as handle:
        text = handle.read()
    updated = rewrite_changelog_header(text, args.version, args.distribution)
    with open(args.changelog, "w", encoding="utf-8") as handle:
        handle.write(updated)
    return 0


def _cmd_append_source(args):
    error = ""
    if args.error_file:
        with open(args.error_file, "r", encoding="utf-8", errors="replace") as handle:
            error = tail_text(handle.read())
    elif args.error:
        error = tail_text(args.error)
    append_record(args.report, {
        "packaging": args.packaging,
        "series": args.series or "",
        "ok": bool(args.ok),
        "error": "" if args.ok else error,
    })
    return 0


def _cmd_append_upload(args):
    error = ""
    if args.error_file:
        with open(args.error_file, "r", encoding="utf-8", errors="replace") as handle:
            error = tail_text(handle.read())
    elif args.error:
        error = tail_text(args.error)
    append_record(args.report, {
        "series": args.series,
        "version": args.version,
        "ok": bool(args.ok),
        "error": "" if args.ok else error,
    })
    return 0


def _cmd_validate(args):
    try:
        validate_request(args.head_repo, args.head_sha, args.pr, args.run_id, args.ppa)
    except ValueError as exc:
        return _die(str(exc))
    return 0


def _cmd_pr_head(args):
    print(pull_request_head(args.repo, args.pr))
    return 0


def _cmd_skipped(args):
    report = skipped_report(args.reason, args.ppa)
    _write_json(args.write, report)
    _write_json(args.publications, publications_payload(report))
    return 0


def _accepted_uploads(versions, uploads):
    ok_series = {item["series"] for item in uploads if item.get("ok")}
    return [item for item in versions if item["series"] in ok_series]


def _cmd_wait_builds(args):
    owner, archive = split_ppa(args.ppa)
    versions = _read_json(args.versions)
    uploads = _read_json(args.uploads) if args.uploads else []
    wanted = _accepted_uploads(versions, uploads)
    snapshot = poll_builds(
        launchpad_fetch, owner, archive, wanted,
        timeout=args.timeout, interval=args.interval,
    )
    _write_json(args.write, snapshot)
    return 0 if snapshot.get("ok") else 1


def _cmd_autopkgtest(args):
    publications = _read_json(args.publications)
    if not publications.get("publications"):
        report = not_run_autopkgtest("no successful publications to test")
        _write_json(args.write, report)
        return 1
    api_key = os.environ.get("SNAPD_AUTOPKGTEST_API_KEY", "")
    client = AutopkgtestClient(
        publications["owner"], publications["ppa"], api_key=api_key,
    )
    report = poll_autopkgtests(
        client, publications, timeout=args.timeout, interval=args.interval,
    )
    _write_json(args.write, report)
    return 0 if report.get("ok") else 1


def _cmd_assemble(args):
    versions = _read_json(args.versions) if args.versions else []
    sources = _read_json(args.sources) if args.sources else []
    uploads = _read_json(args.uploads) if args.uploads else []
    builds_doc = _read_json(args.builds) if args.builds else {}
    builds = builds_doc.get("builds") if isinstance(builds_doc, dict) else builds_doc
    report = assemble_build_report(
        versions, sources, uploads, builds or [],
        ppa=args.ppa,
        timed_out=bool(builds_doc.get("timed_out")) if isinstance(builds_doc, dict) else False,
        error=builds_doc.get("error", "") if isinstance(builds_doc, dict) else "",
    )
    _write_json(args.write, report)
    if args.publications:
        _write_json(args.publications, publications_payload(report))
    return 0 if report["ok"] else 1


def _load_optional(path):
    if not path or not os.path.exists(path):
        return None
    return _read_json(path)


def _cmd_summarize(args):
    build = _load_optional(args.build_report)
    autopkgtest = _load_optional(args.autopkgtest_report)
    if args.autopkgtest_only:
        text, ok = render_autopkgtest_only(autopkgtest)
    elif build is None:
        text, ok = render_summary(None, autopkgtest)
    elif build.get("skipped"):
        text, ok = render_summary(build, None)
    elif args.build_only:
        text, ok = render_summary(build, autopkgtest, build_only=True)
    elif not build.get("ok"):
        if autopkgtest is None:
            autopkgtest = not_run_autopkgtest(
                "source packages, the upload, or Launchpad builds failed",
            )
        text, ok = render_summary(build, autopkgtest)
    else:
        text, ok = render_summary(build, autopkgtest)
    sys.stdout.write(text)
    if args.write_summary:
        with open(args.write_summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    if args.write_result:
        _write_json(args.write_result, {"ok": ok, "skipped": bool(build and build.get("skipped"))})
    return 0 if ok else 1


def _cmd_list_versions(args):
    for item in _read_json(args.versions):
        print(json.dumps(item))
    return 0


def _cmd_packagings(args):
    seen = []
    for item in _read_json(args.versions):
        if item["packaging"] not in seen:
            seen.append(item["packaging"])
    for name in seen:
        print(name)
    return 0


def _emit(payload, path):
    text = json.dumps(payload, indent=2) + "\n"
    if path:
        _write_json(path, payload)
    else:
        sys.stdout.write(text)


def _add_common_wait(parser):
    parser.add_argument("--timeout", type=int, default=21000)
    parser.add_argument("--interval", type=int, default=60)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Early snapd deb verification helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    series = sub.add_parser("series")
    series.add_argument("--write")
    series.set_defaults(func=_cmd_series)

    versions = sub.add_parser("versions")
    versions.add_argument("--series", required=True)
    versions.add_argument("--tree", required=True)
    versions.add_argument("--pr", required=True)
    versions.add_argument("--sha", required=True)
    versions.add_argument("--run-id", required=True)
    versions.add_argument("--write")
    versions.set_defaults(func=_cmd_versions)

    rewrite = sub.add_parser("rewrite-changelog")
    rewrite.add_argument("changelog")
    rewrite.add_argument("--version", required=True)
    rewrite.add_argument("--distribution", required=True)
    rewrite.set_defaults(func=_cmd_rewrite)

    source = sub.add_parser("append-source")
    source.add_argument("--report", required=True)
    source.add_argument("--packaging", required=True)
    source.add_argument("--series", default="")
    source.add_argument("--ok", action="store_true")
    source.add_argument("--error", default="")
    source.add_argument("--error-file")
    source.set_defaults(func=_cmd_append_source)

    upload = sub.add_parser("append-upload")
    upload.add_argument("--report", required=True)
    upload.add_argument("--series", required=True)
    upload.add_argument("--version", required=True)
    upload.add_argument("--ok", action="store_true")
    upload.add_argument("--error", default="")
    upload.add_argument("--error-file")
    upload.set_defaults(func=_cmd_append_upload)

    validate = sub.add_parser("validate")
    validate.add_argument("--head-repo", required=True)
    validate.add_argument("--head-sha", required=True)
    validate.add_argument("--pr", required=True)
    validate.add_argument("--run-id", required=True)
    validate.add_argument("--ppa", default="snappy-dev/beta")
    validate.set_defaults(func=_cmd_validate)

    pr_head = sub.add_parser("pr-head")
    pr_head.add_argument("--repo", required=True)
    pr_head.add_argument("--pr", required=True)
    pr_head.set_defaults(func=_cmd_pr_head)

    skipped = sub.add_parser("skipped-report")
    skipped.add_argument("--reason", required=True)
    skipped.add_argument("--ppa", default="snappy-dev/beta")
    skipped.add_argument("--write", required=True)
    skipped.add_argument("--publications", required=True)
    skipped.set_defaults(func=_cmd_skipped)

    wait = sub.add_parser("wait-builds")
    wait.add_argument("--ppa", default="snappy-dev/beta")
    wait.add_argument("--versions", required=True)
    wait.add_argument("--uploads", required=True)
    wait.add_argument("--write", required=True)
    _add_common_wait(wait)
    wait.set_defaults(func=_cmd_wait_builds)

    adt = sub.add_parser("run-autopkgtests")
    adt.add_argument("--publications", required=True)
    adt.add_argument("--write", required=True)
    _add_common_wait(adt)
    adt.set_defaults(func=_cmd_autopkgtest)

    assemble = sub.add_parser("assemble")
    assemble.add_argument("--ppa", default="snappy-dev/beta")
    assemble.add_argument("--versions")
    assemble.add_argument("--sources")
    assemble.add_argument("--uploads")
    assemble.add_argument("--builds")
    assemble.add_argument("--write", required=True)
    assemble.add_argument("--publications")
    assemble.set_defaults(func=_cmd_assemble)

    summary = sub.add_parser("summarize")
    summary.add_argument("--build-report")
    summary.add_argument("--autopkgtest-report")
    summary.add_argument("--write-summary")
    summary.add_argument("--write-result")
    summary.add_argument("--build-only", action="store_true")
    summary.add_argument("--autopkgtest-only", action="store_true")
    summary.set_defaults(func=_cmd_summarize)

    listing = sub.add_parser("list-versions")
    listing.add_argument("--versions", required=True)
    listing.set_defaults(func=_cmd_list_versions)

    packs = sub.add_parser("packagings")
    packs.add_argument("--versions", required=True)
    packs.set_defaults(func=_cmd_packagings)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, subprocess.CalledProcessError, OSError, HTTPStatus, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
