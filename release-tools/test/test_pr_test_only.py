#!/usr/bin/python3
"""Unit tests for pr-test-only.py.

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
    """Load the hyphenated pr-test-only.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-test-only.py",
    )
    spec = importlib.util.spec_from_file_location("pr_test_only", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pto = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"


def changed(path, previous=""):
    return pto.ChangedFile(path, previous)


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
        rc = pto.main(argv)
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
        self.original = pto.subprocess.run

        def fake_run(command, **_kwargs):
            if command[0] != "gh":
                raise AssertionError(command)
            if isinstance(self.payload, Exception):
                raise self.payload
            return pto.subprocess.CompletedProcess(
                command, 0, stdout=self.payload, stderr=""
            )

        pto.subprocess.run = fake_run
        return self

    def __exit__(self, exc_type, exc, tb):
        pto.subprocess.run = self.original


class TestPaths(unittest.TestCase):
    def test_go_unit_test_is_a_test(self):
        self.assertEqual(pto.path_kind("daemon/daemon_test.go"), "test")

    def test_export_test_is_a_test(self):
        self.assertEqual(pto.path_kind("daemon/export_test.go"), "test")
        self.assertEqual(pto.path_kind("cmd/snap/export_foo_test.go"), "test")

    def test_c_unit_test_is_a_test(self):
        path = "cmd/libsnap-confine-private/feature-test.c"
        self.assertEqual(pto.path_kind(path), "test")
        self.assertEqual(pto.path_kind("cmd/snap-confine/mount-support-test.h"), "test")

    def test_confine_harness_is_a_test(self):
        for name in (
            "test-utils.c",
            "test-utils.h",
            "unit-tests.c",
            "unit-tests.h",
            "unit-tests-main.c",
        ):
            path = f"cmd/libsnap-confine-private/{name}"
            self.assertEqual(pto.path_kind(path), "test", path)

    def test_spread_task_is_a_test(self):
        self.assertEqual(pto.path_kind("tests/main/foo/task.yaml"), "test")

    def test_testdata_is_a_test(self):
        self.assertEqual(
            pto.path_kind("cmd/snap-update-ns/testdata/opt/Makefile"), "test"
        )

    def test_release_tool_unit_test_is_a_test(self):
        self.assertEqual(pto.path_kind("release-tools/test/test_pr_summary.py"), "test")

    def test_autopkgtest_script_is_a_test(self):
        path = "packaging/ubuntu-26.04/tests/integrationtests"
        self.assertEqual(pto.path_kind(path), "test")

    def test_spread_yaml_is_configuration(self):
        self.assertEqual(pto.path_kind("spread.yaml"), "configuration")
        self.assertEqual(pto.path_kind("osutil/vfs/spread.yaml"), "configuration")
        nested = "tests/lib/external/snapd-testing-tools/spread.yaml"
        self.assertEqual(pto.path_kind(nested), "configuration")

    def test_autopkgtest_control_is_configuration(self):
        path = "packaging/ubuntu-26.04/tests/control"
        self.assertEqual(pto.path_kind(path), "configuration")
        config = "packaging/debian-sid/tests/testconfig.json"
        self.assertEqual(pto.path_kind(config), "configuration")

    def test_package_control_is_other(self):
        self.assertEqual(pto.path_kind("packaging/ubuntu-26.04/control"), "other")

    def test_production_and_workflow_are_other(self):
        self.assertEqual(pto.path_kind("daemon/daemon.go"), "other")
        self.assertEqual(pto.path_kind(".github/workflows/unit-tests.yaml"), "other")
        self.assertEqual(pto.path_kind("go.mod"), "other")
        self.assertEqual(pto.path_kind("cmd/Makefile.am"), "other")


class TestDecision(unittest.TestCase):
    def test_only_tests_is_yes(self):
        rows = [
            changed("daemon/daemon_test.go"),
            changed("tests/main/foo/task.yaml"),
        ]
        classified = [pto.classify_file(item) for item in rows]
        self.assertEqual(pto.test_only(classified), "yes")

    def test_spread_yaml_alone_is_not_test_only(self):
        classified = [pto.classify_file(changed("spread.yaml"))]
        self.assertEqual(classified[0].kind, "configuration")
        self.assertEqual(pto.test_only(classified), "no")

    def test_spread_task_beside_spread_yaml_is_not_test_only(self):
        rows = [
            changed("tests/main/foo/task.yaml"),
            changed("spread.yaml"),
        ]
        classified = [pto.classify_file(item) for item in rows]
        self.assertEqual(pto.test_only(classified), "no")

    def test_production_beside_a_unit_test_is_not_test_only(self):
        rows = [
            changed("daemon/daemon.go"),
            changed("daemon/daemon_test.go"),
        ]
        classified = [pto.classify_file(item) for item in rows]
        self.assertEqual(pto.test_only(classified), "no")
        others = [item.shown for item in classified if item.kind == "other"]
        self.assertEqual(others, ["daemon/daemon.go"])

    def test_rename_from_production_to_a_test_is_other(self):
        item = changed("daemon/daemon_test.go", "daemon/daemon.go")
        classified = pto.classify_file(item)
        self.assertEqual(classified.kind, "other")
        self.assertEqual(classified.shown, "daemon/daemon.go")

    def test_empty_change_is_not_test_only(self):
        self.assertEqual(pto.test_only([]), "no")


class TestFilesPayload(unittest.TestCase):
    def test_reads_paginated_arrays_and_previous_filename(self):
        first = files_payload([("daemon/daemon_test.go", "")])
        second = json.dumps(
            [
                {
                    "filename": "daemon/export_test.go",
                    "previous_filename": "daemon/daemon.go",
                }
            ]
        )
        files = pto.parse_changed_files(first + "\n" + second)
        self.assertEqual(files[0], changed("daemon/daemon_test.go"))
        self.assertEqual(files[1].path, "daemon/export_test.go")
        self.assertEqual(files[1].previous, "daemon/daemon.go")

    def test_reads_previous_filename_from_a_view_payload(self):
        payload = json.dumps(
            {"files": [{"path": "spread.yaml", "previousFilename": "old.yaml"}]}
        )
        files = pto.parse_changed_files(payload)
        self.assertEqual(files, [changed("spread.yaml", "old.yaml")])


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("only tests", out)
        self.assertIn("spread.yaml", out)
        self.assertIn("<pull-request>", out)
        self.assertIn("exits 0", out)

    def test_only_tests_print_the_decision_first(self):
        payload = files_payload(
            [
                ("daemon/export_test.go", ""),
                ("cmd/libsnap-confine-private/feature-test.c", ""),
            ]
        )
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Test only: yes\n"))
        self.assertLess(out.index("Test only:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertLess(out.index("Changed files: 2"), out.index("Tests: 2"))
        self.assertLess(out.index("Tests: 2"), out.index("Test configuration: 0"))
        self.assertLess(out.index("Test configuration: 0"), out.index("Other files: 0"))
        self.assertNotIn("export_test.go", out)
        with StubGh(payload):
            result = pto.review(pto.parse_pull_request(PR))
        self.assertEqual(result.facts, ("Test only: yes",))
        self.assertEqual(result.labels, ())
        self.assertEqual(result.findings, ())

    def test_configuration_is_listed(self):
        payload = files_payload(
            [
                ("tests/main/foo/task.yaml", ""),
                ("osutil/vfs/spread.yaml", ""),
            ]
        )
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Test only: no\n"))
        self.assertIn("Tests: 1", out)
        self.assertIn("Test configuration: 1", out)
        self.assertIn("Other files: 0", out)
        self.assertLess(
            out.index("Test configuration:"), out.index("osutil/vfs/spread.yaml")
        )

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
