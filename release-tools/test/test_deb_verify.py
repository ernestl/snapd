#!/usr/bin/python3

import io
import json
import os
import sys
import tarfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import deb_verify  # noqa: E402


CHANGELOG = """\
snapd (2.78) xenial; urgency=medium

  * New upstream release, LP: #1

 -- Tester <tester@example.com>  Mon, 01 Jan 2024 00:00:00 +0000

snapd (2.77) xenial; urgency=medium

  * Older release

 -- Tester <tester@example.com>  Mon, 01 Jan 2023 00:00:00 +0000
"""

SHA = "0123456789abcdef"
VERSION = "2.78+ubuntu24.04~pr17572.g0123456789ab.4242"


def clock_of(values):
    state = {"i": 0}

    def clock():
        index = min(state["i"], len(values) - 1)
        state["i"] += 1
        return values[index]

    return clock


class TestPackagingSelection(unittest.TestCase):
    def test_split_at_26_04(self):
        self.assertEqual(deb_verify.packaging_for("22.04"), "ubuntu-16.04")
        self.assertEqual(deb_verify.packaging_for("24.04 LTS"), "ubuntu-16.04")
        self.assertEqual(deb_verify.packaging_for("25.10"), "ubuntu-16.04")
        self.assertEqual(deb_verify.packaging_for("26.04"), "ubuntu-26.04")
        self.assertEqual(deb_verify.packaging_for("26.10"), "ubuntu-26.04")

    def test_discover_series_includes_devel_once(self):
        answers = {
            ("ubuntu-distro-info", "--supported"): "jammy\nnoble\nresolute\nstonking\n",
            ("ubuntu-distro-info", "--devel"): "stonking\n",
            ("ubuntu-distro-info", "--series", "jammy", "--release"): "22.04 LTS\n",
            ("ubuntu-distro-info", "--series", "noble", "--release"): "24.04 LTS\n",
            ("ubuntu-distro-info", "--series", "resolute", "--release"): "26.04 LTS\n",
            ("ubuntu-distro-info", "--series", "stonking", "--release"): "26.10\n",
        }

        def run(args):
            return answers[tuple(args)]

        entries = deb_verify.discover_series(run)
        self.assertEqual(
            [item["series"] for item in entries],
            ["jammy", "noble", "resolute", "stonking"],
        )
        by_series = {item["series"]: item["packaging"] for item in entries}
        self.assertEqual(by_series["jammy"], "ubuntu-16.04")
        self.assertEqual(by_series["noble"], "ubuntu-16.04")
        self.assertEqual(by_series["resolute"], "ubuntu-26.04")
        self.assertEqual(by_series["stonking"], "ubuntu-26.04")


class TestVersionAndChangelog(unittest.TestCase):
    def test_package_version(self):
        self.assertEqual(
            deb_verify.package_version("2.78", "24.04", "17572", SHA, "4242"),
            VERSION,
        )

    def test_package_version_rejects_short_sha(self):
        with self.assertRaises(ValueError):
            deb_verify.package_version("2.78", "24.04", "17572", "abc", "1")

    def test_upstream_strips_suffix(self):
        self.assertEqual(deb_verify.upstream_version("2.78+ubuntu24.04"), "2.78")
        self.assertEqual(deb_verify.upstream_version("2.77.1"), "2.77.1")

    def test_rewrite_only_first_header(self):
        updated = deb_verify.rewrite_changelog_header(CHANGELOG, VERSION, "noble")
        self.assertTrue(updated.startswith("snapd (%s) noble; urgency=medium\n" % VERSION))
        self.assertIn("snapd (2.77) xenial; urgency=medium", updated)
        self.assertEqual(updated.count("New upstream release"), 1)
        self.assertTrue(updated.endswith("\n"))

    def test_version_plan_reads_each_packaging_changelog(self):
        texts = {
            "ubuntu-16.04": CHANGELOG,
            "ubuntu-26.04": CHANGELOG.replace("xenial", "resolute"),
        }
        plan = deb_verify.build_version_plan(
            [
                {"series": "jammy", "ubuntu_version": "22.04", "packaging": "ubuntu-16.04"},
                {"series": "resolute", "ubuntu_version": "26.04", "packaging": "ubuntu-26.04"},
            ],
            lambda packaging: texts[packaging],
            "17572",
            SHA,
            "4242",
        )
        self.assertEqual(plan[0]["version"], "2.78+ubuntu22.04~pr17572.g0123456789ab.4242")
        self.assertEqual(plan[1]["version"], "2.78+ubuntu26.04~pr17572.g0123456789ab.4242")
        self.assertEqual(plan[0]["upstream"], "2.78")


class TestLaunchpad(unittest.TestCase):
    def test_failed_build_is_terminal(self):
        seen = []

        def fetch(url):
            seen.append(url)
            if "getPublishedSources" in url:
                return {"entries": [{
                    "self_link": "https://lp.example/pub/1",
                    "status": "Published",
                }]}
            if url.startswith("https://lp.example/pub/1"):
                return {"entries": [
                    {
                        "arch_tag": "amd64",
                        "buildstate": "Successfully built",
                        "build_log_url": "https://lp.example/amd64",
                        "datecreated": "2026-01-02T00:00:00",
                    },
                    {
                        "arch_tag": "arm64",
                        "buildstate": "Failed to build",
                        "build_log_url": "https://lp.example/arm64",
                        "datecreated": "2026-01-02T00:00:00",
                    },
                ]}
            raise AssertionError(url)

        snap = deb_verify.snapshot_builds(
            fetch, "snappy-dev", "beta",
            [{"series": "jammy", "version": VERSION}],
        )
        self.assertTrue(snap["done"])
        self.assertFalse(snap["ok"])
        arm = [item for item in snap["builds"] if item["architecture"] == "arm64"][0]
        self.assertEqual(arm["log_url"], "https://lp.example/arm64")
        self.assertTrue(any("jammy" in url for url in seen))

    def test_pending_build_is_not_done(self):
        def fetch(url):
            if "getPublishedSources" in url:
                return {"entries": [{
                    "self_link": "https://lp.example/pub/1",
                    "status": "Pending",
                }]}
            return {"entries": [{
                "arch_tag": "amd64",
                "buildstate": "Needs building",
                "build_log_url": None,
                "datecreated": "2026-01-02T00:00:00",
            }]}

        snap = deb_verify.snapshot_builds(
            fetch, "snappy-dev", "beta",
            [{"series": "noble", "version": VERSION}],
        )
        self.assertFalse(snap["done"])

    def test_timeout_records_missing_publication(self):
        snap = deb_verify.poll_builds(
            lambda url: {"entries": []},
            "snappy-dev",
            "beta",
            [{"series": "jammy", "version": VERSION}],
            timeout=10,
            interval=0,
            sleep=lambda _seconds: None,
            monotonic=clock_of([0, 50]),
        )
        self.assertTrue(snap["timed_out"])
        self.assertFalse(snap["ok"])
        self.assertIn("not published", snap["builds"][0]["state"])


class TestAutopkgtest(unittest.TestCase):
    def test_submit_url_encodes_version(self):
        url = deb_verify.submit_url("noble", "amd64", VERSION, "snappy-dev", "beta")
        self.assertIn("release=noble", url)
        self.assertIn("arch=amd64", url)
        self.assertIn("ppa=snappy-dev%2Fbeta", url)
        self.assertIn("%2B", url)
        self.assertNotIn("+", url.split("?", 1)[1])

    def test_classify_submit(self):
        self.assertEqual(deb_verify.classify_submit(200, "Test request submitted"), "submitted")
        self.assertEqual(
            deb_verify.classify_submit(400, "Unknown architecture amd64v3"),
            "skipped",
        )
        self.assertEqual(deb_verify.classify_submit(403, "Not allowed"), "error")

    def test_summary_failure_names_the_test(self):
        state, detail = deb_verify.summary_state("cmd_snap FAIL exit status 1\n", "1\n")
        self.assertEqual(state, "fail")
        self.assertIn("cmd_snap FAIL", detail)

    def test_read_result_tar(self):
        buff = io.BytesIO()
        with tarfile.open(fileobj=buff, mode="w") as archive:
            payload = b"cmd_snap PASS\n"
            info = tarfile.TarInfo("summary")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        parsed = deb_verify.read_result_tar(buff.getvalue())
        self.assertIn("PASS", parsed["summary"])

    def test_poll_passes_after_retry_and_skips_unknown_arch(self):
        version = VERSION

        class Client(object):
            def __init__(self):
                self.lists = 0
                self.urls = []

            def submit(self, url):
                self.urls.append(url)
                if "arch=amd64v3" in url:
                    return 400, "Unknown architecture amd64v3"
                return 200, "Test request submitted"

            def list_runs(self, series, arch):
                self.lists += 1
                if self.lists < 2:
                    return ""
                return '<a href="20260923_120000_abcd@/">run</a>'

            def fetch_result(self, series, arch, run_id):
                return {
                    "summary": "cmd_snap PASS\n",
                    "exitcode": "0\n",
                    "text": "snapd %s\n" % version,
                    "log_url": "https://example.test/log.gz",
                }

        client = Client()
        report = deb_verify.poll_autopkgtests(
            client,
            {
                "owner": "snappy-dev",
                "ppa": "beta",
                "publications": [{
                    "series": "noble",
                    "version": version,
                    "architectures": ["amd64", "amd64v3"],
                }],
            },
            timeout=100,
            interval=0,
            sleep=lambda _seconds: None,
            monotonic=clock_of([0, 1]),
        )
        self.assertTrue(report["ok"])
        states = {item["architecture"]: item["state"] for item in report["results"]}
        self.assertEqual(states["amd64"], "pass")
        self.assertEqual(states["amd64v3"], "skipped")
        passed = [item for item in report["results"] if item["state"] == "pass"][0]
        self.assertEqual(passed["log_url"], "https://example.test/log.gz")


class TestSummary(unittest.TestCase):
    def test_source_failure_marks_later_stages_not_run(self):
        versions = [{
            "series": "jammy",
            "version": VERSION,
            "ubuntu_version": "22.04",
            "packaging": "ubuntu-16.04",
        }]
        report = deb_verify.assemble_build_report(
            versions,
            [{"packaging": "ubuntu-16.04", "series": "", "ok": False, "error": "gbp exploded"}],
            [],
            [],
        )
        self.assertFalse(report["ok"])
        text, ok = deb_verify.render_summary(report, None)
        self.assertFalse(ok)
        self.assertIn("gbp exploded", text)
        self.assertIn("Not run", text)
        self.assertIn("jammy", text)

    def test_autopkgtest_failure_includes_log(self):
        build = {
            "ok": True,
            "skipped": False,
            "sources": [{"packaging": "ubuntu-16.04", "series": "jammy", "ok": True, "error": ""}],
            "uploads": [{"series": "jammy", "version": VERSION, "ok": True, "error": ""}],
            "builds": [{
                "series": "jammy",
                "version": VERSION,
                "architecture": "amd64",
                "state": "Successfully built",
                "log_url": "https://lp.example/log",
                "ok": True,
            }],
        }
        adt = {
            "ok": False,
            "status": "failed",
            "results": [{
                "series": "jammy",
                "architecture": "amd64",
                "version": VERSION,
                "state": "fail",
                "log_url": "https://autopkgtest.example/log.gz",
                "detail": "cmd_snap FAIL",
                "ok": False,
            }],
        }
        text, ok = deb_verify.render_summary(build, adt)
        self.assertFalse(ok)
        self.assertIn("https://autopkgtest.example/log.gz", text)
        self.assertIn("https://lp.example/log", text)
        self.assertIn("cmd_snap FAIL", text)

    def test_superseded_is_success(self):
        report = deb_verify.skipped_report("pull request head is abc")
        text, ok = deb_verify.render_summary(report, None)
        self.assertTrue(ok)
        self.assertIn("Superseded", text)
        self.assertEqual(deb_verify.publications_payload(report)["publications"], [])

    def test_build_only_success_does_not_require_autopkgtest(self):
        build = deb_verify.assemble_build_report(
            [{"series": "jammy", "version": VERSION, "packaging": "ubuntu-16.04"}],
            [{"packaging": "ubuntu-16.04", "series": "jammy", "ok": True, "error": ""}],
            [{"series": "jammy", "version": VERSION, "ok": True, "error": ""}],
            [{
                "series": "jammy",
                "version": VERSION,
                "architecture": "amd64",
                "state": "Successfully built",
                "log_url": "",
                "ok": True,
            }],
        )
        self.assertTrue(build["ok"])
        text, ok = deb_verify.render_summary(build, None, build_only=True)
        self.assertTrue(ok)
        self.assertIn("autopkgtest workflow", text)
        pubs = deb_verify.publications_payload(build)
        self.assertEqual(pubs["publications"][0]["architectures"], ["amd64"])

    def test_append_and_summarize_cli(self):
        path = os.path.join(self._tmpdir(), "uploads.json")
        code = deb_verify.main([
            "append-upload", "--report", path, "--series", "jammy",
            "--version", VERSION, "--error", "rejected by launchpad",
        ])
        self.assertEqual(code, 0)
        with open(path, encoding="utf-8") as handle:
            rows = json.load(handle)
        self.assertFalse(rows[0]["ok"])
        self.assertIn("rejected", rows[0]["error"])

    def _tmpdir(self):
        import tempfile
        path = tempfile.mkdtemp(prefix="deb-verify-")
        self.addCleanup(lambda: __import__("shutil").rmtree(path))
        return path


if __name__ == "__main__":
    unittest.main()
