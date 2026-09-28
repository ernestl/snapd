#!/usr/bin/python3
"""Unit tests for pr-packaging.py.

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
    """Load the hyphenated pr-packaging.py script as a module."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "pr-packaging.py",
    )
    spec = importlib.util.spec_from_file_location("pr_packaging", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pp = load_module()
PR = "https://github.com/canonical/snapd/pull/17718"


def changed(path, previous=""):
    return pp.ChangedFile(path, previous)


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
        rc = pp.main(argv)
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
        self.original = pp.subprocess.run

        def fake_run(command, **_kwargs):
            if command[0] != "gh":
                raise AssertionError(command)
            if isinstance(self.payload, Exception):
                raise self.payload
            return pp.subprocess.CompletedProcess(
                command, 0, stdout=self.payload, stderr=""
            )

        pp.subprocess.run = fake_run
        return self

    def __exit__(self, exc_type, exc, tb):
        pp.subprocess.run = self.original


class TestPaths(unittest.TestCase):
    def test_snapcraft_yaml_is_snap(self):
        self.assertEqual(pp.path_kind("build-aux/snap/snapcraft.yaml"), pp.SNAP)

    def test_ubuntu_control_is_ubuntu_deb(self):
        self.assertEqual(pp.path_kind("packaging/ubuntu-26.04/control"), pp.UBUNTU)
        autopkg = "packaging/ubuntu-16.04/tests/control"
        self.assertEqual(pp.path_kind(autopkg), pp.UBUNTU)

    def test_core_initrd_debian_is_ubuntu_deb(self):
        path = "core-initrd/26.04/debian/control"
        self.assertEqual(pp.path_kind(path), pp.UBUNTU)

    def test_fedora_spec_is_cross_distro(self):
        self.assertEqual(pp.path_kind("packaging/fedora/snapd.spec"), pp.CROSS)

    def test_shared_packaging_helper_is_cross_distro(self):
        self.assertEqual(pp.path_kind("packaging/snapd.mk"), pp.CROSS)
        self.assertEqual(pp.path_kind("packaging/debian-sid/rules"), pp.CROSS)

    def test_vendor_and_root_module_files_are_vendoring(self):
        self.assertEqual(pp.path_kind("vendor/gopkg.in/yaml.v3/yaml.go"), pp.VENDOR)
        self.assertEqual(pp.path_kind("go.mod"), pp.VENDOR)
        self.assertEqual(pp.path_kind("go.sum"), pp.VENDOR)
        bpf = "cmd/libsnap-confine-private/bpf/vendor/linux/bpf.h"
        self.assertEqual(pp.path_kind(bpf), pp.VENDOR)

    def test_test_snap_is_not_packaging(self):
        path = "tests/lib/snaps/store/test-snapd-hello-classic/snapcraft.yaml"
        self.assertEqual(pp.path_kind(path), pp.OTHER)

    def test_product_code_is_other(self):
        self.assertEqual(pp.path_kind("daemon/daemon.go"), pp.OTHER)
        self.assertEqual(pp.path_kind("data/selinux/snappy.te"), pp.OTHER)
        self.assertEqual(pp.path_kind(".github/workflows/spread-tests.yaml"), pp.OTHER)


class TestDecision(unittest.TestCase):
    def test_snap_and_product_file(self):
        rows = [
            changed("build-aux/snap/snapcraft.yaml"),
            changed("daemon/daemon.go"),
        ]
        self.assertEqual(pp.packaging_decision(rows), "yes")
        self.assertIn(pp.OTHER, pp.file_kinds(rows[1]))
        self.assertIn(pp.SNAP, pp.file_kinds(rows[0]))

    def test_vendor_rename_into_product_code(self):
        item = changed("daemon/daemon.go", "vendor/example.com/mod/mod.go")
        kinds = pp.file_kinds(item)
        self.assertEqual(kinds, {pp.VENDOR, pp.OTHER})
        self.assertEqual(pp.packaging_decision([item]), "yes")

    def test_empty_change_is_not_packaging(self):
        self.assertEqual(pp.packaging_decision([]), "no")


class TestCLI(unittest.TestCase):
    def test_help(self):
        rc, out, err = run_main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("packaging", out)
        self.assertIn("vendoring", out)
        self.assertIn("<pull-request>", out)
        self.assertIn("exits 0", out)

    def test_snap_and_ubuntu_print_the_decision_first(self):
        payload = files_payload(
            [
                ("build-aux/snap/snapcraft.yaml", ""),
                ("packaging/ubuntu-16.04/control", ""),
                ("packaging/ubuntu-26.04/rules", ""),
            ]
        )
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Packaging: yes\n"))
        self.assertLess(out.index("Packaging:"), out.index("Details:"))
        self.assertLess(out.index("Details:"), out.index(f"Pull request: {PR}"))
        self.assertIn("Snap: 1", out)
        self.assertIn("Ubuntu deb: 2", out)
        self.assertIn("Cross-distro: 0", out)
        self.assertIn("Vendoring: 0", out)
        self.assertIn("build-aux/snap/snapcraft.yaml", out)
        self.assertIn("packaging/ubuntu-16.04/control", out)
        self.assertIn("packaging/ubuntu-26.04/rules", out)

    def test_cross_distro_and_vendoring_are_listed(self):
        payload = files_payload(
            [
                ("packaging/fedora/snapd.spec", ""),
                ("packaging/snapd.mk", ""),
                ("go.mod", ""),
                ("go.sum", ""),
                ("vendor/gopkg.in/yaml.v3/yaml.go", ""),
            ]
        )
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("Cross-distro: 2", out)
        self.assertIn("Vendoring: 3", out)
        self.assertIn("packaging/fedora/snapd.spec", out)
        self.assertIn("packaging/snapd.mk", out)
        self.assertIn("go.mod", out)
        self.assertIn("go.sum", out)
        self.assertIn("vendor/", out)
        self.assertNotIn("vendor/gopkg.in", out)

    def test_product_file_beside_snapcraft_is_listed(self):
        payload = files_payload(
            [
                ("build-aux/snap/snapcraft.yaml", ""),
                ("daemon/daemon.go", ""),
            ]
        )
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Packaging: yes\n"))
        self.assertIn("Snap: 1", out)
        self.assertIn("Other files: 1", out)
        self.assertIn("daemon/daemon.go", out)

    def test_vendor_rename_into_product_code(self):
        payload = files_payload([("daemon/daemon.go", "vendor/example.com/mod/mod.go")])
        with StubGh(payload):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Packaging: yes\n"))
        self.assertIn("Changed files: 1", out)
        self.assertIn("Vendoring: 1", out)
        self.assertIn("Other files: 1", out)
        self.assertIn("vendor/", out)
        self.assertIn("daemon/daemon.go", out)
        self.assertNotIn("vendor/example.com", out)

    def test_empty_file_list(self):
        with StubGh("[]"):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Packaging: no\n"))
        self.assertIn("Changed files: 0", out)
        self.assertIn("Snap: 0", out)
        self.assertIn("Ubuntu deb: 0", out)
        self.assertIn("Cross-distro: 0", out)
        self.assertIn("Vendoring: 0", out)
        self.assertIn("Other files: 0", out)

    def test_test_snap_is_not_packaging(self):
        path = "tests/lib/snaps/store/test-snapd-hello-classic/snapcraft.yaml"
        with StubGh(files_payload([(path, "")])):
            rc, out, err = run_main([PR])
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("Packaging: no\n"))
        self.assertIn("Snap: 0", out)
        self.assertIn("Other files: 1", out)

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
