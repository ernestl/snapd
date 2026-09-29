#!/usr/bin/python3
"""Unit tests for pr-interface.py.

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
    """Load the hyphenated pr-interface.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-interface.py",
    )
    spec = importlib.util.spec_from_file_location("pr_interface", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pi = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"


def changed(path, previous=""):
    return pi.ChangedFile(path, previous)


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
        rc = pi.main(argv)
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
        self.original = pi.subprocess.run

        def fake_run(command, **_kwargs):
            if command[0] != "gh":
                raise AssertionError(command)
            if isinstance(self.payload, Exception):
                raise self.payload
            return pi.subprocess.CompletedProcess(
                command, 0, stdout=self.payload, stderr=""
            )

        pi.subprocess.run = fake_run
        return self

    def __exit__(self, exc_type, exc, tb):
        pi.subprocess.run = self.original


class TestPaths(unittest.TestCase):
    def test_interface_file_and_shared_builtin_files(self):
        paths = [
            "interfaces/builtin/alsa.go",
            "interfaces/builtin/common.go",
            "interfaces/builtin/all.go",
            "interfaces/builtin/README.md",
        ]
        for path in paths:
            self.assertTrue(pi.is_interface(path), path)

    def test_builtin_test_is_not_an_interface(self):
        self.assertFalse(pi.is_interface("interfaces/builtin/alsa_test.go"))

    def test_backend_policy_and_engine_are_not_interfaces(self):
        paths = [
            "interfaces/apparmor/backend.go",
            "interfaces/seccomp/spec.go",
            "interfaces/udev/udev.go",
            "interfaces/policy/policy.go",
            "interfaces/repo.go",
            "interfaces/core.go",
        ]
        for path in paths:
            self.assertFalse(pi.is_interface(path), path)

    def test_interface_path_under_tests_is_not_an_interface(self):
        path = "tests/main/interfaces-alsa/task.yaml"
        self.assertFalse(pi.is_interface(path))

    def test_product_code_is_other(self):
        self.assertFalse(pi.is_interface("daemon/daemon.go"))


class TestDecision(unittest.TestCase):
    def test_interface_and_product_file(self):
        rows = [
            changed("interfaces/builtin/alsa.go"),
            changed("daemon/daemon.go"),
        ]
        self.assertEqual(pi.interface_decision(rows), "yes")
        self.assertIn(pi.INTERFACE, pi.file_kinds(rows[0]))
        self.assertEqual(pi.file_kinds(rows[1]), {pi.OTHER})

    def test_interface_rename_into_product_code(self):
        item = changed("daemon/daemon.go", "interfaces/builtin/alsa.go")
        self.assertEqual(pi.file_kinds(item), {pi.INTERFACE, pi.OTHER})
        self.assertEqual(pi.interface_decision([item]), "yes")

    def test_empty_change_is_not_an_interface(self):
        self.assertEqual(pi.interface_decision([]), "no")


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("interface definition", out)
        self.assertIn("interfaces/builtin", out)
        self.assertIn("<pull-request>", out)
        self.assertIn("exits 0", out)

    def test_interface_prints_the_decision_first(self):
        payload = files_payload(
            [
                ("interfaces/builtin/alsa.go", ""),
                ("daemon/daemon.go", ""),
            ]
        )
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Interface: yes\n"))
        self.assertLess(out.index("Interface:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertIn("Changed files: 2", out)
        self.assertIn("Interface: 1", out)
        self.assertIn("Other files: 1", out)
        self.assertIn("interfaces/builtin/alsa.go", out)
        self.assertIn("daemon/daemon.go", out)
        with StubGh(payload):
            result = pi.review(pi.parse_pull_request(PR))
        self.assertEqual(result.facts, ("Interface: yes",))
        self.assertEqual(result.labels, ())
        self.assertEqual(result.findings, ())

    def test_common_go_is_an_interface(self):
        with StubGh(files_payload([("interfaces/builtin/common.go", "")])):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Interface: yes\n"))
        self.assertIn("interfaces/builtin/common.go", out)

    def test_backend_policy_and_test_are_other(self):
        payload = files_payload(
            [
                ("interfaces/builtin/alsa_test.go", ""),
                ("interfaces/apparmor/backend.go", ""),
                ("interfaces/policy/policy.go", ""),
                ("interfaces/repo.go", ""),
            ]
        )
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Interface: no\n"))
        self.assertIn("Interface: 0", out)
        self.assertIn("Other files: 4", out)

    def test_interface_rename_into_product_code(self):
        payload = files_payload([("daemon/daemon.go", "interfaces/builtin/alsa.go")])
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Interface: yes\n"))
        self.assertIn("Changed files: 1", out)
        self.assertIn("Interface: 1", out)
        self.assertIn("Other files: 1", out)
        self.assertIn("interfaces/builtin/alsa.go", out)
        self.assertIn("daemon/daemon.go", out)

    def test_interface_path_under_tests_is_not_an_interface(self):
        path = "tests/main/interfaces-alsa/task.yaml"
        with StubGh(files_payload([(path, "")])):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Interface: no\n"))
        self.assertIn("Other files: 1", out)

    def test_empty_file_list(self):
        with StubGh("[]"):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Interface: no\n"))
        self.assertIn("Changed files: 0", out)
        self.assertIn("Interface: 0", out)
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
