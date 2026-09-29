"""Run flake8 on the release-tools tree."""

import os
import subprocess
import unittest


def is_24_04():
    """Return whether this host is Ubuntu 24.04."""
    with open("/etc/os-release", encoding="utf-8") as inf:
        return 'VERSION_ID="24.04"' in inf.read()


class TestFlake8(unittest.TestCase):
    """flake8 stays clean for release-tools."""

    @unittest.skipIf(is_24_04(), "flake8 is broken on 24.04")
    def test_flake8(self):
        """flake8 accepts every Python file under release-tools."""
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        subprocess.check_call(["flake8", "--ignore=E501", p])
