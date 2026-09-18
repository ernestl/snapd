# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

"""Human-readable GitHub Actions step summaries."""

from __future__ import annotations

from .apply import BranchResult
from .select import Candidate


def _pr_line(cand: Candidate) -> str:
    short = cand.sha[:12]
    if cand.pr is None:
        return f"- unresolved `{short}` {cand.subject}"
    title = cand.pr.title or cand.subject
    url = cand.pr.url
    return f"- [#{cand.pr.number}]({url}) {title} (`{short}`)"


def format_branch_summary(result: BranchResult) -> str:
    lines = [f"## `{result.branch}`", ""]
    lines.append(f"Fork point: `{result.fork[:12]}`")
    lines.append("")
    if result.dry_run:
        lines.append(f"Planned ({len(result.planned)}):")
        if result.planned:
            lines.extend(_pr_line(c) for c in result.planned)
        else:
            lines.append("- none")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"Planned ({len(result.planned)}):")
    if result.planned:
        lines.extend(_pr_line(c) for c in result.planned)
    else:
        lines.append("- none")
    lines.append("")
    lines.append(f"Cherry-picked ({len(result.applied)}):")
    if result.applied:
        lines.extend(_pr_line(c) for c in result.applied)
    else:
        lines.append("- none")
    lines.append("")
    if result.skipped_empty:
        lines.append("Skipped empty (already applied):")
        lines.extend(_pr_line(c) for c in result.skipped_empty)
        lines.append("")
    if result.conflict is not None:
        conf = result.conflict
        ident = f"#{conf.pr_number}" if conf.pr_number is not None else "unresolved"
        title = conf.pr_title or conf.subject
        lines.append(f"**Blocked on:** {ident} {title} (`{conf.sha[:12]}`)")
        if conf.pr_url:
            lines.append(f"- PR: {conf.pr_url}")
        lines.append(f"- subject: {conf.subject}")
        if conf.files:
            lines.append("- source files: " + ", ".join(f"`{p}`" for p in conf.files[:30]))
        if conf.conflicted:
            lines.append("- conflicted paths: " + ", ".join(f"`{p}`" for p in conf.conflicted))
        remaining = [c for c in result.planned if c.sha not in {a.sha for a in result.applied} and c.sha != conf.sha]
        if remaining:
            lines.append("- remaining after block: " + ", ".join(_remaining_id(c) for c in remaining))
        lines.append("")
        if conf.status.strip():
            lines.append("<details><summary>git status</summary>")
            lines.append("")
            lines.append("```")
            lines.append(conf.status.rstrip())
            lines.append("```")
            lines.append("</details>")
            lines.append("")
        if conf.stderr.strip():
            lines.append("<details><summary>cherry-pick stderr</summary>")
            lines.append("")
            lines.append("```")
            lines.append(conf.stderr.rstrip())
            lines.append("```")
            lines.append("</details>")
            lines.append("")
    if result.error:
        lines.append(f"**Error:** {result.error}")
        lines.append("")
    if result.pushed:
        lines.append("Pushed successful prefix to the release branch.")
        lines.append("")
    return "\n".join(lines)


def _remaining_id(cand: Candidate) -> str:
    if cand.pr is None:
        return f"`{cand.sha[:12]}`"
    return f"#{cand.pr.number}"


def format_conflict_log(result: BranchResult) -> str:
    if result.conflict is None:
        return ""
    conf = result.conflict
    ident = f"#{conf.pr_number}" if conf.pr_number is not None else conf.sha[:12]
    lines = [
        "****************************************",
        f"CHERRY-PICK CONFLICT: {result.branch} blocked on {ident}",
        f"master SHA: {conf.sha}",
        f"subject: {conf.subject}",
    ]
    if conf.pr_url:
        lines.append(f"PR: {conf.pr_url}")
    if conf.conflicted:
        lines.append("conflicted paths:")
        lines.extend(f"  {p}" for p in conf.conflicted)
    lines.append("****************************************")
    return "\n".join(lines)
