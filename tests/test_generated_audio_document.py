import json
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vntts_artifacts import (
    GeneratedAudioDocument,
    GeneratedAudioEntry,
    GeneratedAudioIndex,
    GeneratedAudioManifestError,
    GeneratedAudioRecord,
    load_generated_audio_document,
    load_generated_audio_manifest,
    write_generated_audio_document,
    write_generated_audio_manifest,
)
from vntts_artifacts.file_integrity import sha256_file
from vntts_artifacts.hashing import text_sha256


def metadata():
    return {
        "game": "Synthetic Game",
        "language": "en",
        "generated_at": "2026-08-16T12:00:00Z",
        "source_queue_sha256": "a" * 64,
        "producer_run": {"worker": "offline-1"},
    }


def generated_record(audio, **overrides):
    record = {
        "queue_id": "line:1:18fdd549b2ed367a",
        "line_id": "line:1",
        "text_sha256": text_sha256("Exact generated text."),
        "audio": audio.name,
        "audio_format": "wav-pcm16-mono",
        "audio_sha256": sha256_file(audio),
        "sample_rate": 24_000,
        "sample_count": 48_000,
        "provider": "synthetic",
        "model": "synthetic-v1",
        "prompt_sha256": "0" * 64,
        "seed": 7,
        "review_status": "approved",
        "generation_profile": "stable",
        "prompt_applied": False,
        "queue_annotations_sha256": "1" * 64,
        "synthesis_provenance_sha256": "2" * 64,
        "voice_character": "Ada",
        "producer_metrics": {"rtf": 0.42, "attempt": 2},
    }
    record.update(overrides)
    return record


class GeneratedAudioDocumentTest(unittest.TestCase):
    def test_lossless_document_exposes_typed_provenance_and_extensions(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "line.wav"
            audio.write_bytes(b"synthetic WAV fixture")
            raw_record = generated_record(audio)
            written = write_generated_audio_document(
                root / "generated.json", metadata(), [raw_record]
            )
            document = GeneratedAudioDocument.load(root / "generated.json")
            record = document.records[0]

        self.assertIsInstance(written, GeneratedAudioDocument)
        self.assertIsInstance(record, GeneratedAudioRecord)
        self.assertIsInstance(record, GeneratedAudioEntry)
        self.assertEqual(document.game, "Synthetic Game")
        self.assertEqual(document.language, "en")
        self.assertEqual(document.generated_at, "2026-08-16T12:00:00Z")
        self.assertEqual(document.source_queue_sha256, "a" * 64)
        self.assertEqual(document.producer_metadata["producer_run"]["worker"], "offline-1")
        self.assertEqual(record.queue_id, "line:1:18fdd549b2ed367a")
        self.assertEqual(record.provider, "synthetic")
        self.assertEqual(record.model, "synthetic-v1")
        self.assertEqual(record.seed, 7)
        self.assertFalse(record.prompt_applied)
        self.assertEqual(record.synthesis_provenance_sha256, "2" * 64)
        self.assertEqual(record.producer_fields["producer_metrics"]["attempt"], 2)
        self.assertEqual(record.to_record(), raw_record)
        self.assertIs(document.entries, document.records)

    def test_document_find_verifies_exact_identity_and_current_bytes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "line.wav"
            audio.write_bytes(b"original")
            record = generated_record(audio)
            document = write_generated_audio_document(
                root / "generated.json", metadata(), [record]
            )
            self.assertEqual(
                document.find(record["line_id"], record["text_sha256"]).provider,
                "synthetic",
            )
            self.assertIsNone(document.find(record["line_id"], "f" * 64))
            audio.write_bytes(b"modified")
            self.assertIsNone(document.find(record["line_id"], record["text_sha256"]))
            self.assertIsNotNone(
                document.find(
                    record["line_id"], record["text_sha256"], verify_file=False
                )
            )

    def test_typed_records_republish_without_extension_loss(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "line.wav"
            audio.write_bytes(b"fixture")
            first = write_generated_audio_document(
                root / "first.json", metadata(), [generated_record(audio)]
            )
            second = write_generated_audio_document(
                root / "second.json", first.metadata, first.records
            )
            legacy_path = write_generated_audio_manifest(
                root / "legacy.json", first.metadata, first.records
            )
            first_raw = json.loads((root / "first.json").read_text(encoding="utf-8"))
            second_raw = json.loads((root / "second.json").read_text(encoding="utf-8"))
            legacy_raw = json.loads(legacy_path.read_text(encoding="utf-8"))

        self.assertEqual(second.records[0].to_record(), first.records[0].to_record())
        self.assertEqual(second_raw, first_raw)
        self.assertEqual(legacy_raw, first_raw)

    def test_legacy_readers_keep_original_return_types(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "line.wav"
            audio.write_bytes(b"fixture")
            path = root / "generated.json"
            write_generated_audio_document(path, metadata(), [generated_record(audio)])
            index = GeneratedAudioIndex.load(path)
            legacy_metadata, legacy_entries = load_generated_audio_manifest(path)
            lossless = load_generated_audio_document(path)

        self.assertIs(type(index.entries[0]), GeneratedAudioEntry)
        self.assertIs(type(legacy_entries[0]), GeneratedAudioEntry)
        self.assertEqual(legacy_metadata, lossless.metadata)
        self.assertFalse(hasattr(index.entries[0], "provider"))
        self.assertEqual(lossless.records[0].provider, "synthetic")

    def test_strict_writer_rejects_invalid_provenance_without_publication(self):
        cases = (
            ("provider", "provider", {"provider": ""}),
            ("prompt-hash", "prompt_sha256", {"prompt_sha256": "ABC"}),
            ("seed", "seed", {"seed": True}),
            ("prompt-applied", "prompt_applied", {"prompt_applied": "false"}),
            (
                "provenance-hash",
                "synthesis_provenance_sha256",
                {"synthesis_provenance_sha256": "3" * 63},
            ),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "line.wav"
            audio.write_bytes(b"fixture")
            for label, pattern, overrides in cases:
                with self.subTest(label=label):
                    path = root / f"{label}.json"
                    with self.assertRaisesRegex(GeneratedAudioManifestError, pattern):
                        write_generated_audio_document(
                            path, metadata(), [generated_record(audio, **overrides)]
                        )
                    self.assertFalse(path.exists())

    def test_strict_writer_validates_metadata_and_json_extensions(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "line.wav"
            audio.write_bytes(b"fixture")
            for label, pattern, overrides in (
                ("game", "metadata game", {"game": ""}),
                ("language", "metadata language", {"language": 7}),
                ("timestamp", "ISO-8601", {"generated_at": "invalid"}),
                (
                    "timezone",
                    "timezone offset",
                    {"generated_at": "2026-08-16T12:00:00"},
                ),
                ("queue-hash", "source_queue_sha256", {"source_queue_sha256": "a"}),
            ):
                with self.subTest(label=label):
                    path = root / f"{label}.json"
                    raw_metadata = metadata()
                    raw_metadata.update(overrides)
                    with self.assertRaisesRegex(GeneratedAudioManifestError, pattern):
                        write_generated_audio_document(
                            path, raw_metadata, [generated_record(audio)]
                        )
                    self.assertFalse(path.exists())

            bad_record = root / "bad-record.json"
            with self.assertRaisesRegex(GeneratedAudioManifestError, "valid JSON"):
                write_generated_audio_document(
                    bad_record,
                    metadata(),
                    [generated_record(audio, producer_nan=math.nan)],
                )
            self.assertFalse(bad_record.exists())

            bad_metadata = root / "bad-metadata.json"
            raw_metadata = metadata()
            raw_metadata["producer_value"] = {1, 2}
            with self.assertRaisesRegex(GeneratedAudioManifestError, "valid JSON"):
                write_generated_audio_document(
                    bad_metadata, raw_metadata, [generated_record(audio)]
                )
            self.assertFalse(bad_metadata.exists())

    def test_strict_document_rejects_symlink_escape(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_root = root / "manifest"
            manifest_root.mkdir()
            external = root / "outside.wav"
            external.write_bytes(b"outside")
            link = manifest_root / "linked.wav"
            link.symlink_to(external)
            path = manifest_root / "generated.json"

            with self.assertRaisesRegex(GeneratedAudioManifestError, "must stay within"):
                write_generated_audio_document(
                    path, metadata(), [generated_record(link)]
                )
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
