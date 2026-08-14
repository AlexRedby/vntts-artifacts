import hashlib
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from durable_file import (
    atomic_write_json,
    create_new_output_group,
    replace_file_group,
    sha256_file,
)


class PublicationTest(unittest.TestCase):
    def test_atomic_json_and_streaming_hash(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "value.json"
            atomic_write_json(path, {"name": "Beyoncé"}, sort_keys=True)
            digest = sha256_file(path)
            content = path.read_text(encoding="utf-8")

        self.assertIn('"Beyoncé"', content)
        self.assertEqual(len(digest), len(hashlib.sha256().hexdigest()))

    def test_replace_group_restores_existing_files_after_partial_failure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.write_bytes(b"old-first")
            second.write_bytes(b"old-second")
            real_replace = os.replace

            def fail_second_publication(source, destination):
                if Path(destination) == second and ".backup." not in Path(source).name:
                    raise OSError("synthetic failure")
                return real_replace(source, destination)

            with patch("durable_file.publication.os.replace", fail_second_publication):
                with self.assertRaisesRegex(OSError, "synthetic failure"):
                    replace_file_group({first: b"new-first", second: b"new-second"})

            self.assertEqual(first.read_bytes(), b"old-first")
            self.assertEqual(second.read_bytes(), b"old-second")

    def test_create_new_group_removes_partial_publication(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            with self.assertRaisesRegex(RuntimeError, "stop"):
                with create_new_output_group(first, second) as staged:
                    staged[0].write_bytes(b"one")
                    staged[1].write_bytes(b"two")
                    raise RuntimeError("stop")

            self.assertFalse(first.exists())
            self.assertFalse(second.exists())


if __name__ == "__main__":
    unittest.main()
