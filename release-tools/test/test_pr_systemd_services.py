#!/usr/bin/python3
"""Unit tests for pr-systemd-services.py.

The script filename contains a hyphen, so tests load it with importlib.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring,duplicate-code

import importlib.util
import json
import os
import sys
import unittest
from io import StringIO


def load_module():
    """Load the hyphenated pr-systemd-services.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-systemd-services.py",
    )
    spec = importlib.util.spec_from_file_location("pr_systemd_services", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ss = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"


def changed(path, previous=""):
    return ss.ChangedFile(path, previous)


def files_payload(entries):
    """REST-shaped gh api payload. entries are (path, previous)."""
    items = []
    for path, previous in entries:
        item = {"filename": path}
        if previous:
            item["previous_filename"] = previous
        items.append(item)
    return json.dumps(items)


def run_main(argv):
    out = StringIO()
    err = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = out
        sys.stderr = err
        rc = ss.main(argv)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return rc, out.getvalue(), err.getvalue()


class StubGh:
    """Replace gh for one test. payload is stdout, or an exception to raise."""

    def __init__(self, payload):
        self.payload = payload
        self.original = None

    def __enter__(self):
        self.original = ss.subprocess.run

        def fake_run(command, **_kwargs):
            if command[0] != "gh":
                raise AssertionError(command)
            if isinstance(self.payload, Exception):
                raise self.payload
            return ss.subprocess.CompletedProcess(
                command, 0, stdout=self.payload, stderr=""
            )

        ss.subprocess.run = fake_run
        return self

    def __exit__(self, exc_type, exc, tb):
        ss.subprocess.run = self.original


class TestPaths(unittest.TestCase):
    def test_each_classic_unit(self):
        units = [
            "data/systemd/snapd.service.in",
            "data/systemd/snapd.socket",
            "data/systemd/snapd.apparmor.service.in",
            "data/systemd/snapd.mounts.target",
            "data/systemd/snapd.mounts-pre.target",
            "data/systemd/snapd.seeded.service.in",
            "data/systemd-user/snapd.session-agent.service.in",
            "data/systemd-user/snapd.session-agent.socket",
        ]
        for path in units:
            self.assertTrue(ss.is_systemd_service(path), path)

    def test_core_unit_is_not_a_systemd_service(self):
        core = [
            "data/systemd/snapd.autoimport.service.in",
            "data/systemd/snapd.snap-repair.service.in",
            "data/systemd/snapd.snap-repair.timer",
            "data/systemd/snapd.core-fixup.service.in",
            "data/systemd/snapd.system-shutdown.service.in",
            "data/systemd/snapd.recovery-chooser-trigger.service.in",
            "data/systemd/snapd.gpio-chardev-setup.target",
            "data/systemd/snapd.core-fixup.sh",
            "data/systemd/Makefile",
        ]
        for path in core:
            self.assertFalse(ss.is_systemd_service(path), path)

    def test_failure_unit_is_not_a_systemd_service(self):
        path = "data/systemd/snapd.failure.service.in"
        self.assertFalse(ss.is_systemd_service(path))

    def test_unit_under_tests_is_not_a_systemd_service(self):
        path = "tests/main/classic-boot/snapd.service"
        self.assertFalse(ss.is_systemd_service(path))

    def test_product_code_is_other(self):
        self.assertFalse(ss.is_systemd_service("daemon/daemon.go"))


class TestDecision(unittest.TestCase):
    def test_unit_and_product_file(self):
        rows = [
            changed("data/systemd/snapd.service.in"),
            changed("daemon/daemon.go"),
        ]
        self.assertEqual(ss.systemd_decision(rows), "yes")
        self.assertIn(ss.SYSTEMD, ss.file_kinds(rows[0]))
        self.assertEqual(ss.file_kinds(rows[1]), {ss.OTHER})

    def test_unit_rename_into_product_code(self):
        item = changed("daemon/daemon.go", "data/systemd/snapd.socket")
        self.assertEqual(ss.file_kinds(item), {ss.SYSTEMD, ss.OTHER})
        self.assertEqual(ss.systemd_decision([item]), "yes")

    def test_empty_change_is_not_systemd(self):
        self.assertEqual(ss.systemd_decision([]), "no")


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("classic systemd", out)
        self.assertIn("<pull-request>", out)
        self.assertIn("exits 0", out)

    def test_service_template_prints_the_decision_first(self):
        payload = files_payload(
            [
                ("data/systemd/snapd.service.in", ""),
                ("daemon/daemon.go", ""),
            ]
        )
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Systemd services: yes\n"))
        self.assertLess(out.index("Systemd services:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertIn("Changed files: 2", out)
        self.assertIn("Systemd services: 1", out)
        self.assertIn("Other files: 1", out)
        self.assertIn("data/systemd/snapd.service.in", out)
        self.assertIn("daemon/daemon.go", out)

    def test_session_agent_socket_is_listed(self):
        path = "data/systemd-user/snapd.session-agent.socket"
        with StubGh(files_payload([(path, "")])):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Systemd services: yes\n"))
        self.assertIn(path, out)

    def test_core_unit_and_failure_unit_are_other(self):
        payload = files_payload(
            [
                ("data/systemd/snapd.autoimport.service.in", ""),
                ("data/systemd/snapd.failure.service.in", ""),
            ]
        )
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Systemd services: no\n"))
        self.assertIn("Systemd services: 0", out)
        self.assertIn("Other files: 2", out)

    def test_unit_rename_into_product_code(self):
        payload = files_payload([("daemon/daemon.go", "data/systemd/snapd.socket")])
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Systemd services: yes\n"))
        self.assertIn("Changed files: 1", out)
        self.assertIn("Systemd services: 1", out)
        self.assertIn("Other files: 1", out)
        self.assertIn("data/systemd/snapd.socket", out)
        self.assertIn("daemon/daemon.go", out)

    def test_unit_under_tests_is_not_systemd(self):
        path = "tests/main/classic-boot/snapd.service"
        with StubGh(files_payload([(path, "")])):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Systemd services: no\n"))
        self.assertIn("Other files: 1", out)

    def test_empty_file_list(self):
        with StubGh("[]"):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Systemd services: no\n"))
        self.assertIn("Changed files: 0", out)
        self.assertIn("Systemd services: 0", out)
        self.assertIn("Other files: 0", out)

    def test_missing_link_prints_help(self):
        rc, out, err = run_main([])
        self.assertEqual(rc, 2)
        self.assertEqual(err, "")
        self.assertIn("Usage:", out)

    def test_invalid_link(self):
        rc, _out, err = run_main(["not-a-pull-request"])
        self.assertEqual(rc, 2)
        self.assertIn("invalid pull request link: not-a-pull-request", err)

    def test_unknown_flag(self):
        rc, _out, err = run_main(["--nope"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown flag: --nope", err)

    def test_gh_failure(self):
        with StubGh(RuntimeError("cannot run gh: missing")):
            rc, _out, err = run_main([PR])
        self.assertEqual(rc, 1)
        self.assertIn("cannot run gh: missing", err)


if __name__ == "__main__":
    unittest.main()
