# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

"""Map a master commit SHA to the GitHub pull request that introduced it.

Port of ernestl/relnote PR resolution. Subject (#NNNN) is not enough:
some squash commits omit the number. Fallbacks:

1. last #NNNN in the commit subject
2. GitHub associated-pulls-for-commit API
3. "Merge pull request #N" in the subject
4. GitHub search for the SHA as a pull request
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import gitutil

_SUBJECT_PR = re.compile(r"#(\d+)")
_MERGE_PR = re.compile(r"Merge pull request #(\d+)", re.IGNORECASE)
_CHERRY_PICKED = re.compile(r"cherry picked from commit ([0-9a-f]{7,40})", re.IGNORECASE)


@dataclass(frozen=True)
class ResolvedPR:
    number: int
    title: str
    url: str
    sha: str


class GitHubError(RuntimeError):
    pass


def pr_number_from_subject(subject: str) -> int | None:
    matches = _SUBJECT_PR.findall(subject)
    if not matches:
        return None
    return int(matches[-1])


def cherry_picked_from(body: str) -> str | None:
    match = _CHERRY_PICKED.search(body)
    if match is None:
        return None
    return match.group(1)


class GitHubClient:
    """Minimal GitHub REST client. Token from GH_TOKEN / GITHUB_TOKEN."""

    def __init__(
        self,
        repo: str,
        token: str | None = None,
        api_get: Callable[[str], Any] | None = None,
    ):
        if "/" not in repo:
            raise ValueError(f"repo must be owner/name, got {repo!r}")
        self.repo = repo
        self.token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        self._api_get = api_get
        self._pr_cache: dict[int, ResolvedPR] = {}
        self._sha_cache: dict[str, ResolvedPR | None] = {}

    def _get(self, path: str) -> Any:
        if self._api_get is not None:
            return self._api_get(path)
        return self._http_get(path)

    def _http_get(self, path: str) -> Any:
        url = path if path.startswith("https://") else f"https://api.github.com{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "snapd-test-maintenance",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
        except HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            raise GitHubError(f"GET {path} failed: HTTP {err.code}: {detail}") from err
        except URLError as err:
            raise GitHubError(f"GET {path} failed: {err}") from err
        if not body.strip():
            return None
        return json.loads(body)

    def pull(self, number: int, sha: str) -> ResolvedPR:
        cached = self._pr_cache.get(number)
        if cached is not None:
            return ResolvedPR(cached.number, cached.title, cached.url, sha)
        data = self._get(f"/repos/{self.repo}/pulls/{number}")
        if not isinstance(data, dict) or "number" not in data:
            raise GitHubError(f"cannot load pull request #{number}")
        pr = ResolvedPR(
            number=int(data["number"]),
            title=str(data.get("title") or ""),
            url=str(data.get("html_url") or f"https://github.com/{self.repo}/pull/{number}"),
            sha=sha,
        )
        self._pr_cache[number] = pr
        return pr

    def associated_pulls(self, sha: str) -> list[dict[str, Any]]:
        data = self._get(f"/repos/{self.repo}/commits/{sha}/pulls")
        if data is None:
            return []
        if not isinstance(data, list):
            raise GitHubError(f"unexpected associated-pulls payload for {sha}")
        return [item for item in data if isinstance(item, dict)]

    def search_pulls(self, sha: str) -> list[dict[str, Any]]:
        query = urlencode({"q": f"{sha} repo:{self.repo} is:pr", "per_page": "5"})
        data = self._get(f"/search/issues?{query}")
        if not isinstance(data, dict):
            return []
        items = data.get("items") or []
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def resolve_commit(self, sha: str, subject: str = "", cwd: str | None = None) -> ResolvedPR | None:
        """Resolve a master commit to a PR. Results are cached per SHA."""
        if sha in self._sha_cache:
            cached = self._sha_cache[sha]
            if cached is None:
                return None
            return ResolvedPR(cached.number, cached.title, cached.url, sha)

        if not subject and cwd is not None:
            subject = gitutil.commit_subject(sha, cwd=cwd)

        resolved = self._resolve(sha, subject, cwd)
        self._sha_cache[sha] = resolved
        return resolved

    def _resolve(self, sha: str, subject: str, cwd: str | None) -> ResolvedPR | None:
        number = pr_number_from_subject(subject)
        if number is not None:
            try:
                return self.pull(number, sha)
            except GitHubError:
                pass

        merge = _MERGE_PR.search(subject)
        if merge is not None:
            try:
                return self.pull(int(merge.group(1)), sha)
            except GitHubError:
                pass

        associated = self._pick_associated(self.associated_pulls(sha), sha)
        if associated is not None:
            return associated

        # Merge commits: the PR is often associated with a parent.
        if cwd is not None:
            parents = gitutil.commit_parents(sha, cwd=cwd)
            if len(parents) > 1:
                associated = self._pick_associated(self.associated_pulls(parents[1]), sha)
                if associated is not None:
                    return associated
            original = cherry_picked_from(gitutil.commit_body(sha, cwd=cwd))
            if original:
                associated = self._pick_associated(self.associated_pulls(original), sha)
                if associated is not None:
                    return associated

        for item in self.search_pulls(sha):
            number = item.get("number")
            if not isinstance(number, int):
                continue
            try:
                return self.pull(int(number), sha)
            except GitHubError:
                continue
        return None

    def _pick_associated(self, items: list[dict[str, Any]], sha: str) -> ResolvedPR | None:
        if not items:
            return None
        preferred = None
        for item in items:
            number = item.get("number")
            if not isinstance(number, int):
                continue
            base = item.get("base") or {}
            base_ref = ""
            if isinstance(base, dict):
                base_ref = str(base.get("ref") or "")
            merged = bool(item.get("merged_at") or item.get("merged"))
            title = str(item.get("title") or "")
            url = str(item.get("html_url") or f"https://github.com/{self.repo}/pull/{number}")
            pr = ResolvedPR(number=number, title=title, url=url, sha=sha)
            self._pr_cache[number] = pr
            if merged and base_ref in ("master", "main"):
                return pr
            if preferred is None:
                preferred = pr
        return preferred
