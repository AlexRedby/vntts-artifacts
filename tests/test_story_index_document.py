import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import vntts_artifacts.story_index as story_index
from vntts_artifacts import (
    STORY_INDEX_SCHEMA_VERSION,
    StoryIndexDocument,
    StoryIndexError,
    StoryIndexLine,
    StoryIndexRecord,
    load_story_index,
    load_story_index_document,
    write_story_index,
    write_story_index_document,
)
from vntts_artifacts.hashing import text_sha256


def metadata():
    return {
        "game": "Synthetic Game",
        "language": "en",
        "generated_at": "2026-08-16T12:00:00Z",
        "producer_metadata": {"build": "fixture-1"},
        "collections": [
            {
                "collection_id": "main-story",
                "title": "Main Story",
                "kind": "story",
                "order": 1,
                "producer_collection_field": "preserved",
            }
        ],
    }


def authoring_record(line_id="line:1", **overrides):
    text = "Keep the exact authoring text."
    record = {
        "record_type": "line",
        "line_id": line_id,
        "chapter": "chapter-1",
        "sequence": 7,
        "speaker": "Ada (memory)",
        "voice_character": "Ada",
        "text": text,
        "text_sha256": text_sha256(text),
        "kind": "dialogue",
        "previous_text": "Earlier context.",
        "next_text": "Later context.",
        "context": {"scene": "observatory", "mood": ["quiet", "tense"]},
        "source_audio_status": "unavailable",
        "audio_status": "configured_unavailable",
        "source_audio_id": "voice-7",
        "source_voice_id": "voice-7",
        "source_audio_reason": "bank_not_installed",
        "audio_reason": "bank_not_installed",
        "source_kind": "story",
        "speakable": True,
        "collection_id": "main-story",
        "portrait": "ada-memory.png",
        "producer_line_field": {"asset": 42},
    }
    record.update(overrides)
    return record


class StoryIndexDocumentTest(unittest.TestCase):
    def test_lossless_document_exposes_typed_authoring_fields_and_extensions(self):
        raw_metadata = metadata()
        raw_record = authoring_record()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            written = write_story_index_document(path, raw_metadata, [raw_record])
            document = StoryIndexDocument.load(path)
            record = document.records[0]

        self.assertEqual(STORY_INDEX_SCHEMA_VERSION, 1)
        self.assertIsInstance(written, StoryIndexDocument)
        self.assertIsInstance(record, StoryIndexRecord)
        self.assertIsInstance(record, StoryIndexLine)
        self.assertEqual(document.game, "Synthetic Game")
        self.assertEqual(document.language, "en")
        self.assertEqual(document.generated_at, "2026-08-16T12:00:00Z")
        self.assertEqual(record.voice_character, "Ada")
        self.assertEqual(record.previous_text, "Earlier context.")
        self.assertEqual(record.next_text, "Later context.")
        self.assertEqual(record.context["scene"], "observatory")
        self.assertEqual(record.source_audio_reason, "bank_not_installed")
        self.assertEqual(record.source_audio_status, "unavailable")
        self.assertEqual(record.source_audio_id, "voice-7")
        self.assertEqual(record.producer_fields["portrait"], "ada-memory.png")
        self.assertEqual(record.producer_fields["producer_line_field"], {"asset": 42})
        self.assertEqual(record.to_record(), raw_record)
        self.assertEqual(document.producer_metadata["producer_metadata"], {"build": "fixture-1"})
        self.assertEqual(
            document.collections[0].producer_fields["producer_collection_field"],
            "preserved",
        )
        self.assertEqual(document.collections[0].to_record(), raw_metadata["collections"][0])

    def test_collection_helpers_are_queue_builder_friendly(self):
        hidden = authoring_record("line:hidden", sequence=8, speakable=False)
        with TemporaryDirectory() as directory:
            document = write_story_index_document(
                Path(directory) / "story.jsonl",
                metadata(),
                [authoring_record(), hidden],
            )

        self.assertEqual(document.find("line:1").voice_character, "Ada")
        self.assertIsNone(document.find("missing"))
        self.assertEqual(
            [record.line_id for record in document.records_for_collection("main-story")],
            ["line:1", "line:hidden"],
        )
        self.assertEqual(
            [
                record.line_id
                for record in document.records_for_collection("main-story", speakable_only=True)
            ],
            ["line:1"],
        )
        with self.assertRaisesRegex(StoryIndexError, "Unknown"):
            document.records_for_collection("missing")

    def test_writer_returns_normalized_data_detached_from_its_input(self):
        raw_metadata = metadata()
        raw_metadata["producer_metadata"] = {1: ("fixture-1",)}
        raw_metadata["collections"][0]["producer_collection_field"] = {"tags": ["story"]}
        raw_record = authoring_record(producer_line_field={1: (42,)})
        expected_metadata = json.loads(json.dumps(raw_metadata))
        expected_record = json.loads(json.dumps(raw_record))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            written = write_story_index_document(path, raw_metadata, [raw_record])
            loaded = load_story_index_document(path)

            raw_metadata["producer_metadata"][1] = ("changed",)
            raw_metadata["collections"][0]["producer_collection_field"]["tags"].append("changed")
            raw_record["producer_line_field"][1] = (99,)
            raw_record["context"]["mood"].append("changed")

            self.assertEqual(written.path, path.resolve())
            self.assertEqual(written.metadata, loaded.metadata)
            self.assertEqual(written.producer_metadata["producer_metadata"], {"1": ["fixture-1"]})
            self.assertEqual(written.records[0].to_record(), expected_record)
            self.assertEqual(written.records[0].to_record(), loaded.records[0].to_record())
            self.assertEqual(written.records[0].context, expected_record["context"])
            self.assertEqual(written.records[0].producer_fields["producer_line_field"], {"1": [42]})
            self.assertEqual(
                written.collections[0].to_record(), expected_metadata["collections"][0]
            )
            self.assertEqual(written.collections[0].to_record(), loaded.collections[0].to_record())

    def test_reader_and_writer_adopt_owned_rows_without_changing_mutable_boundaries(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            write_story_index_document(path, metadata(), [authoring_record()])
            for operation in ("reader", "writer"):
                with self.subTest(operation=operation):
                    decoded_rows = []
                    decode = story_index._load_strict_json

                    def capture_owned_row(value):
                        row = decode(value)
                        decoded_rows.append(row)
                        return row

                    with patch.object(story_index, "_load_strict_json", capture_owned_row):
                        if operation == "reader":
                            document = load_story_index_document(path)
                        else:
                            document = write_story_index_document(
                                path, metadata(), [authoring_record()]
                            )

                    record = document.records[0]
                    self.assertIs(record.document, decoded_rows[-1])
                    self.assertIsNot(record.context, record.document["context"])
                    record.context["scene"] = "changed"
                    record.producer_fields["portrait"] = "changed.png"
                    exported = record.to_record()
                    exported["line_id"] = "changed"
                    self.assertEqual(record.to_record(), authoring_record())

                    collection = document.collections[0]
                    self.assertIsNot(collection.document, decoded_rows[0]["collections"][0])
                    collection.producer_fields["producer_collection_field"] = "changed"
                    collection.to_record().clear()
                    self.assertEqual(collection.to_record(), metadata()["collections"][0])

                    record.document["context"]["mood"].append("changed")
                    self.assertEqual(
                        load_story_index_document(path).records[0].to_record(), authoring_record()
                    )

    def test_writer_snapshots_reused_generator_mappings(self):
        def records():
            record = authoring_record()
            for number in (1, 2):
                record["line_id"] = f"line:{number}"
                record["sequence"] = number
                yield record

        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            written = write_story_index_document(path, metadata(), records())
            loaded = load_story_index_document(path)

        for document in (written, loaded):
            self.assertEqual([record.line_id for record in document.records], ["line:1", "line:2"])
            self.assertEqual([record.sequence for record in document.records], [1, 2])

    def test_typed_records_republish_without_losing_fields(self):
        raw_record = authoring_record()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = write_story_index_document(root / "first.jsonl", metadata(), [raw_record])
            second = write_story_index_document(
                root / "second.jsonl", first.metadata, first.records
            )
            legacy_writer_path = write_story_index(
                root / "legacy-writer.jsonl", first.metadata, first.records
            )
            first_rows = [
                json.loads(row)
                for row in (root / "first.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            second_rows = [
                json.loads(row)
                for row in (root / "second.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            legacy_writer_rows = [
                json.loads(row)
                for row in legacy_writer_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(second.records[0].to_record(), raw_record)
        self.assertEqual(second_rows, first_rows)
        self.assertEqual(legacy_writer_rows, first_rows)

    def test_legacy_loader_keeps_its_existing_return_shape(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            write_story_index_document(path, metadata(), [authoring_record()])
            legacy_metadata, legacy_lines = load_story_index(path)
            lossless = load_story_index_document(path)

        self.assertEqual(legacy_metadata, lossless.metadata)
        self.assertIs(type(legacy_lines[0]), StoryIndexLine)
        self.assertEqual(legacy_lines[0].line_id, lossless.records[0].line_id)

    def test_strict_reader_rejects_ambiguous_authoring_identity_and_types(self):
        cases = (
            ("duplicate", "[Dd]uplicate", [authoring_record(), authoring_record()]),
            ("sequence", "sequence", [authoring_record(sequence=True)]),
            (
                "conflicts with legacy audio_status",
                "conflicts with legacy audio_status",
                [authoring_record(source_audio_status="available")],
            ),
            (
                "context",
                "context",
                [authoring_record(context=["not", "an", "object"])],
            ),
            (
                "conflicts with legacy audio_reason",
                "conflicts with legacy audio_reason",
                [authoring_record(source_audio_reason="different")],
            ),
            (
                "conflicts with legacy source_voice_id",
                "conflicts with legacy source_voice_id",
                [authoring_record(source_audio_id="different")],
            ),
            ("text hash", "text_sha256", [authoring_record(text_sha256="0" * 64)]),
            ("speakable", "speakable", [authoring_record(speakable=1)]),
            (
                "undeclared collection",
                "not declared",
                [authoring_record(collection_id="missing")],
            ),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for label, pattern, records in cases:
                with self.subTest(label=label):
                    path = root / f"{label.replace(' ', '-')}.jsonl"
                    with self.assertRaisesRegex(StoryIndexError, pattern):
                        write_story_index_document(path, metadata(), records)
                    self.assertFalse(path.exists())

    def test_strict_writer_validates_common_producer_metadata(self):
        class SchemaVersion(int):
            pass

        cases = (
            ("game", "metadata game", {"game": ""}),
            ("language", "metadata language", {"language": 7}),
            (
                "generated-at-format",
                "ISO-8601",
                {"generated_at": "not-a-timestamp"},
            ),
            (
                "generated-at-timezone",
                "timezone offset",
                {"generated_at": "2026-08-16T12:00:00"},
            ),
            ("collections-tuple", "collections", {"collections": tuple(metadata()["collections"])}),
            ("schema-version-type", "schema version", {"schema_version": SchemaVersion(1)}),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for label, pattern, overrides in cases:
                with self.subTest(label=label):
                    raw_metadata = metadata()
                    raw_metadata.update(overrides)
                    path = root / f"{label}.jsonl"
                    with self.assertRaisesRegex(StoryIndexError, pattern):
                        write_story_index_document(path, raw_metadata, [authoring_record()])
                    self.assertFalse(path.exists())

    def test_strict_writer_rejects_non_json_extensions_before_publication(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            metadata_path = root / "metadata.jsonl"
            raw_metadata = metadata()
            raw_metadata["producer_metadata"] = {"not_json": {1, 2}}
            with self.assertRaisesRegex(StoryIndexError, "valid JSON"):
                write_story_index_document(metadata_path, raw_metadata, [authoring_record()])
            self.assertFalse(metadata_path.exists())

            record_path = root / "record.jsonl"
            with self.assertRaisesRegex(StoryIndexError, "valid JSON"):
                write_story_index_document(
                    record_path,
                    metadata(),
                    [authoring_record(producer_nan=float("nan"))],
                )
            self.assertFalse(record_path.exists())

    def test_invalid_records_preserve_an_existing_destination(self):
        cases = (
            [authoring_record(), authoring_record()],
            [authoring_record(sequence=True)],
            [authoring_record(text_sha256="0" * 64)],
            [authoring_record(producer_nan=float("nan"))],
            [authoring_record(producer_line_field={1, 2})],
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            write_story_index_document(path, metadata(), [authoring_record()])
            original = path.read_bytes()
            for records in cases:
                with self.subTest(records=records):
                    with self.assertRaises(StoryIndexError):
                        write_story_index_document(path, metadata(), records)
                    self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
