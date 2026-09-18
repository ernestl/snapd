# Copyright (C) 2026 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.

from __future__ import annotations

import unittest

from test_maintenance.paths import is_tests_only, is_tests_only_path


class PathsTest(unittest.TestCase):
    def test_spread_tree(self):
        self.assertTrue(is_tests_only_path("tests/main/foo/task.yaml"))
        self.assertTrue(is_tests_only_path("tests"))
        self.assertTrue(is_tests_only_path("./tests/lib/reset.sh"))

    def test_unit_and_export(self):
        self.assertTrue(is_tests_only_path("overlord/snapstate/snapstate_test.go"))
        self.assertTrue(is_tests_only_path("daemon/export_test.go"))
        self.assertTrue(is_tests_only_path("daemon/export_api_snaps_test.go"))

    def test_helpers_and_testdata(self):
        self.assertTrue(is_tests_only_path("testutil/base.go"))
        self.assertTrue(is_tests_only_path("testtime/testtime.go"))
        self.assertTrue(is_tests_only_path("overlord/snapstate/snapstatetest/backend.go"))
        self.assertTrue(is_tests_only_path("interfaces/ifacetest/backend.go"))
        self.assertTrue(is_tests_only_path("secboot/testdata/foo.bin"))
        self.assertTrue(is_tests_only_path("cmd/snap-update-ns/testdata/x"))

    def test_c_and_packaging_and_ci(self):
        self.assertTrue(is_tests_only_path("cmd/libsnap-confine-private/mountinfo-test.c"))
        self.assertTrue(is_tests_only_path("cmd/snap-confine/unit-tests.c"))
        self.assertTrue(is_tests_only_path("cmd/test-driver"))
        self.assertTrue(is_tests_only_path("packaging/ubuntu-16.04/tests/integrationtests"))
        self.assertTrue(is_tests_only_path("release-tools/test/test_changelog.py"))
        self.assertTrue(is_tests_only_path(".github/workflows/ci-test.yaml"))
        self.assertTrue(is_tests_only_path("run-checks"))
        self.assertTrue(is_tests_only_path("run-spread"))
        self.assertTrue(is_tests_only_path("spread.yaml"))
        self.assertTrue(is_tests_only_path("osutil/vfs/spread.yaml"))
        self.assertTrue(is_tests_only_path("osutil/vfs/tests/foo"))
        self.assertTrue(is_tests_only_path("check-pr-title.py"))

    def test_production_rejected(self):
        self.assertFalse(is_tests_only_path("overlord/snapstate/snapstate.go"))
        self.assertFalse(is_tests_only_path("daemon/daemon.go"))
        self.assertFalse(is_tests_only_path("osutil/disks/mockdisk.go"))
        self.assertFalse(is_tests_only_path("asserts/sysdb/testkeys.go"))
        self.assertFalse(is_tests_only_path("packaging/ubuntu-16.04/snapd.install"))
        self.assertFalse(is_tests_only_path("NEWS.md"))
        self.assertFalse(is_tests_only_path("cmd/snapd/main.c"))
        self.assertFalse(is_tests_only_path("tests/../daemon/daemon.go"))

    def test_set_must_be_all_tests(self):
        self.assertTrue(is_tests_only(["tests/main/foo/task.yaml", "spread.yaml"]))
        self.assertFalse(is_tests_only(["tests/main/foo/task.yaml", "daemon/daemon.go"]))
        self.assertFalse(is_tests_only([]))


if __name__ == "__main__":
    unittest.main()
