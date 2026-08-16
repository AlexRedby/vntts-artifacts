import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vntts_artifacts.voice_generation_queue import (
    VOICE_GENERATION_QUEUE_SCHEMA,
    VOICE_GENERATION_QUEUE_SCHEMA_VERSION,
    VoiceGenerationQueue,
    VoiceGenerationQueueError,
    expected_voice_generation_queue_id,
    load_voice_generation_queue,
    voice_generation_action,
    write_voice_generation_queue,
)


def queue_item(line_id="story:1", text="Generate me.", **overrides):
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    item = {
        "record_type": "generation_item",
        "queue_id": f"{line_id}:{text_hash[:16]}",
        "line_id": line_id,
        "text_sha256": text_hash,
        "speaker": "Ada",
        "voice_character": "Ada",
        "text": text,
        "kind": "dialogue",
        "previous_text": None,
        "next_text": "Next line.",
        "source_kind": "story",
        "story_group": "main",
        "chapter": "1001",
        "sequence": 1,
        "story_order": 2,
        "source_audio_status": "no_audio",
        "source_audio_reason": "not_resolved",
        "action": "generate",
        "state": "pending",
        "prompt_adapters": {"generic": "Speak naturally."},
        "producer_extension": {"preserved": True},
    }
    item.update(overrides)
    return item


def queue_metadata(**overrides):
    metadata = {
        "record_type": "metadata",
        "schema": VOICE_GENERATION_QUEUE_SCHEMA,
        "schema_version": VOICE_GENERATION_QUEUE_SCHEMA_VERSION,
        "game": "Reverse: 1999",
        "language": "en",
        "generated_at": "2026-08-16T12:00:00+00:00",
        "source_story_index": "/producer/machine/story.jsonl",
        "source_story_index_sha256": "a" * 64,
        "item_count": 1,
        "character_count": 1,
        "source_audio_status_counts": {"no_audio": 1},
        "action_counts": {"generate": 1},
        "source_kind_counts": {"story": 1},
        "delivery_annotation_version": 1,
    }
    metadata.update(overrides)
    return metadata


class VoiceGenerationQueueTest(unittest.TestCase):
    def test_extractor_v1_fixture_round_trips_unchanged_with_typed_identity(self):
        item = queue_item()
        metadata = queue_metadata()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.jsonl"
            write_voice_generation_queue(path, metadata, [item])
            loaded_metadata, items = load_voice_generation_queue(path)
            raw = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]

            rewritten = Path(directory) / "rewritten.jsonl"
            write_voice_generation_queue(rewritten, loaded_metadata, items)
            rewritten_raw = [
                json.loads(row) for row in rewritten.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(raw, [metadata, item])
        self.assertEqual(rewritten_raw, raw)
        self.assertEqual(items[0].queue_id, item["queue_id"])
        self.assertEqual(items[0].source_audio_status, "no_audio")
        self.assertEqual(items[0].document["producer_extension"], {"preserved": True})

    def test_reader_does_not_resolve_or_trust_machine_local_source_story_path(self):
        item = queue_item()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.jsonl"
            missing_source = "/machine-that-does-not-exist/private/story.jsonl"
            write_voice_generation_queue(
                path,
                queue_metadata(source_story_index=missing_source),
                [item],
            )
            queue = VoiceGenerationQueue.load(path)

        self.assertEqual(queue.metadata["source_story_index"], missing_source)

    def test_minimal_v1_item_remains_compatible_when_source_fields_are_absent(self):
        text = "A compatibility fixture."
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        item = {
            "record_type": "generation_item",
            "queue_id": f"compat:1:{text_hash[:16]}",
            "line_id": "compat:1",
            "text_sha256": text_hash,
            "text": text,
            "action": "generate",
        }
        with TemporaryDirectory() as directory:
            path = write_voice_generation_queue(
                Path(directory) / "queue.jsonl",
                {"game": "Synthetic Game", "language": "en"},
                [item],
            )
            _metadata, items = load_voice_generation_queue(path)

        self.assertIsNone(items[0].source_audio_status)
        self.assertEqual(items[0].action, "generate")

    def test_v1_identity_and_source_action_mappings_are_stable(self):
        text_hash = hashlib.sha256(b"Exact text").hexdigest()
        self.assertEqual(
            expected_voice_generation_queue_id("story:line", text_hash),
            f"story:line:{text_hash[:16]}",
        )
        self.assertEqual(voice_generation_action("no_audio"), "generate")
        self.assertEqual(
            voice_generation_action("configured_unavailable"),
            "prefer_source_audio",
        )
        self.assertEqual(voice_generation_action("unresolved"), "manual_review")
        self.assertEqual(voice_generation_action("unchecked"), "resolve_audio")

    def test_rejects_text_hash_and_queue_identity_drift(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.jsonl"
            with self.assertRaisesRegex(VoiceGenerationQueueError, "text_sha256"):
                write_voice_generation_queue(
                    path,
                    queue_metadata(),
                    [queue_item(text_sha256="0" * 64)],
                )
            with self.assertRaisesRegex(VoiceGenerationQueueError, "queue_id must be"):
                write_voice_generation_queue(
                    path,
                    queue_metadata(),
                    [queue_item(queue_id="unstable-id")],
                )
            padded_text = " Exact text is not trimmed. "
            trimmed_hash = hashlib.sha256(padded_text.strip().encode("utf-8")).hexdigest()
            with self.assertRaisesRegex(VoiceGenerationQueueError, "text_sha256"):
                write_voice_generation_queue(
                    path,
                    queue_metadata(),
                    [queue_item(text=padded_text, text_sha256=trimmed_hash)],
                )

    def test_rejects_invalid_source_audio_semantics(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.jsonl"
            with self.assertRaisesRegex(VoiceGenerationQueueError, "does not match"):
                write_voice_generation_queue(
                    path,
                    queue_metadata(action_counts={"manual_review": 1}),
                    [queue_item(action="manual_review")],
                )
            with self.assertRaisesRegex(VoiceGenerationQueueError, "source_audio_reason"):
                write_voice_generation_queue(
                    path,
                    queue_metadata(),
                    [queue_item(source_audio_reason=None)],
                )
            with self.assertRaisesRegex(VoiceGenerationQueueError, "requires source_audio_status"):
                write_voice_generation_queue(
                    path,
                    queue_metadata(),
                    [queue_item(source_audio_status=None)],
                )
            with self.assertRaisesRegex(VoiceGenerationQueueError, "Unsupported"):
                voice_generation_action("installed")

    def test_rejects_duplicate_items_and_incorrect_summary_counts(self):
        item = queue_item()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.jsonl"
            with self.assertRaisesRegex(VoiceGenerationQueueError, "Duplicate"):
                write_voice_generation_queue(
                    path,
                    queue_metadata(item_count=2),
                    [item, item],
                )
            with self.assertRaisesRegex(VoiceGenerationQueueError, "character_count"):
                write_voice_generation_queue(
                    path,
                    queue_metadata(character_count=2),
                    [item],
                )

    def test_rejects_malformed_source_metadata_and_unsafe_item_types(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "queue.jsonl"
            with self.assertRaisesRegex(VoiceGenerationQueueError, "lowercase SHA-256"):
                write_voice_generation_queue(
                    path,
                    queue_metadata(source_story_index_sha256="not-a-hash"),
                    [queue_item()],
                )
            with self.assertRaisesRegex(VoiceGenerationQueueError, "sequence"):
                write_voice_generation_queue(
                    path,
                    queue_metadata(),
                    [queue_item(sequence=True)],
                )


if __name__ == "__main__":
    unittest.main()
