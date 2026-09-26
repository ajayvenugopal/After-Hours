import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.check_release import inspect_archive


class ReleaseTests(unittest.TestCase):
    def make_wheel(self, path, extra=None):
        with zipfile.ZipFile(path, "w") as archive:
            for name in ("agentdock/cli.py", "agentdock/__main__.py", "agentdock-0.1.0.dist-info/licenses/LICENSE"):
                archive.writestr(name, "example")
            archive.writestr("agentdock-0.1.0.dist-info/entry_points.txt",
                             "[console_scripts]\nagentdock = agentdock.cli:agentdock_main\n")
            if extra:
                archive.writestr(extra, "do not publish")

    def test_expected_wheel_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agentdock.whl"
            self.make_wheel(path)
            self.assertEqual(inspect_archive(path), 4)

    def test_private_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agentdock.whl"
            for extra in (".agentdock/config.json", ".env", "id.key", "../outside"):
                self.make_wheel(path, extra)
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    inspect_archive(path)

    def test_incomplete_wheel_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agentdock.whl"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("agentdock/__init__.py", "")
            with self.assertRaises(ValueError):
                inspect_archive(path)
