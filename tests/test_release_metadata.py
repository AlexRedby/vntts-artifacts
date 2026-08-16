import tomllib
import unittest
from pathlib import Path

import vntts_artifacts


class ReleaseMetadataTest(unittest.TestCase):
    def test_package_and_release_candidate_versions_match(self):
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        package_version = project["project"]["version"]
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertEqual(package_version, "0.6.0")
        self.assertEqual(vntts_artifacts.__version__, package_version)
        self.assertIn(f"## [{package_version}] - Unreleased", changelog)


if __name__ == "__main__":
    unittest.main()
