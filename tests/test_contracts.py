import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from vntts_artifacts.file_integrity import sha256_file
from vntts_artifacts.story_index import load_story_index, write_story_index
from vntts_artifacts.text_utils import slugify
from vntts_artifacts.voice_manifest import (
    VoiceManifestError,
    load_voice_manifest,
    upsert_voice_manifest_entry,
    write_voice_manifest,
)


@dataclass(frozen=True)
class ProducerLine:
    record_type: str
    line_id: str
    chapter: str
    sequence: int
    speaker: str
    text: str
    kind: str
    producer_field: str


class ContractTest(unittest.TestCase):
    def test_story_index_round_trip_preserves_producer_extensions(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            write_story_index(
                path,
                {"game": "Example"},
                [ProducerLine("line", "game:1", "1", 1, "Ada", "Hello", "dialogue", "x")],
            )
            metadata, lines = load_story_index(path)
            raw_line = json.loads(path.read_text(encoding="utf-8").splitlines()[1])
        self.assertEqual(metadata["schema"], "vntts.story-index")
        self.assertEqual(lines[0].line_id, "game:1")
        self.assertEqual(raw_line["producer_field"], "x")

    def test_voice_manifest_upsert_is_readable_by_consumer(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            manifest = upsert_voice_manifest_entry(
                {"version": 2, "voices": []},
                {
                    "character": "Ada",
                    "speaker": "ada-v1",
                    "aliases": ["A.D.A."],
                    "references": ["references/ada.wav"],
                },
            )
            write_voice_manifest(path, manifest)
            _document, entries = load_voice_manifest(path)
        self.assertEqual(entries[0].references, ("references/ada.wav",))

    def test_voice_manifest_rejects_duplicate_normalized_aliases(self):
        with self.assertRaisesRegex(VoiceManifestError, "Duplicate voice"):
            write_voice_manifest(
                Path("unused.json"),
                {
                    "version": 2,
                    "voices": [
                        {"character": "Ada", "speaker": "ada-v1"},
                        {
                            "character": "Other",
                            "speaker": "other-v1",
                            "aliases": ["A.D.A"],
                        },
                    ],
                },
            )

    def test_integrity_and_slug_helpers_are_stable(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "value"
            path.write_bytes(b"abc")
            digest = sha256_file(path)
        self.assertEqual(
            digest,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        self.assertEqual(slugify("Ms. NewBabel"), "ms-newbabel")


if __name__ == "__main__":
    unittest.main()
