import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vntts_artifacts.live_sequence import (
    LIVE_SEQUENCE_SCHEMA,
    LIVE_SEQUENCE_SCHEMA_VERSION,
    LiveSequencePlanError,
    load_live_sequence_plan,
    write_live_sequence_plan,
)
from vntts_artifacts.story_index import write_story_index


def write_story(path):
    write_story_index(
        path,
        {"game": "Synthetic"},
        [
            {
                "record_type": "line",
                "line_id": "synthetic:chapter-1:1",
                "chapter": "chapter-1",
                "sequence": 1,
                "speaker": "Ada",
                "text": "First line.",
                "kind": "dialogue",
            },
            {
                "record_type": "line",
                "line_id": "synthetic:chapter-1:3",
                "chapter": "chapter-1",
                "sequence": 3,
                "speaker": "Bea",
                "text": "Third line.",
                "kind": "dialogue",
            },
        ],
    )


def plan_input():
    return {
        "game_id": "synthetic",
        "producer": {"name": "synthetic-extractor", "version": "1.0"},
        "source_extract_sha256": "1" * 64,
        "chapters": [
            {
                "chapter": "chapter-1",
                "entry_event_ids": ["event-1"],
                "events": [
                    {
                        "event_id": "event-1",
                        "sequence": 1,
                        "kind": "speech",
                        "line_id": "synthetic:chapter-1:1",
                        "control": "automatic",
                        "successors": ["event-2"],
                    },
                    {
                        "event_id": "event-2",
                        "sequence": 2,
                        "kind": "silent",
                        "control": "automatic",
                        "successors": ["event-3"],
                    },
                    {
                        "event_id": "event-3",
                        "sequence": 3,
                        "kind": "speech",
                        "line_id": "synthetic:chapter-1:3",
                        "control": "terminal",
                        "successors": [],
                    },
                ],
            }
        ],
    }


class LiveSequencePlanTest(unittest.TestCase):
    def test_round_trip_binds_exact_story_bytes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            story = root / "story.jsonl"
            output = root / "live-sequence.json"
            write_story(story)

            plan = write_live_sequence_plan(output, plan_input(), story)
            document = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(document["schema"], LIVE_SEQUENCE_SCHEMA)
        self.assertEqual(document["schema_version"], LIVE_SEQUENCE_SCHEMA_VERSION)
        self.assertEqual(plan.event_for_line("synthetic:chapter-1:3").event_id, "event-3")

    def test_changed_story_bytes_invalidate_plan(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            story = root / "story.jsonl"
            output = root / "live-sequence.json"
            write_story(story)
            write_live_sequence_plan(output, plan_input(), story)
            story.write_text(story.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaisesRegex(LiveSequencePlanError, "different story-index bytes"):
                load_live_sequence_plan(output, story)

    def test_invalid_graph_is_not_published(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            story = root / "story.jsonl"
            output = root / "live-sequence.json"
            write_story(story)
            document = plan_input()
            document["chapters"][0]["events"][1]["successors"] = ["missing"]

            with self.assertRaisesRegex(LiveSequencePlanError, "missing successor"):
                write_live_sequence_plan(output, document, story)

            self.assertFalse(output.exists())

    def test_unguarded_automatic_cycle_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            story = root / "story.jsonl"
            write_story(story)
            document = plan_input()
            final = document["chapters"][0]["events"][2]
            final["control"] = "automatic"
            final["successors"] = ["event-1"]

            with self.assertRaisesRegex(LiveSequencePlanError, "automatic cycle"):
                write_live_sequence_plan(root / "plan.json", document, story)

    def test_passive_transition_cannot_hide_an_automatic_cycle(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            story = root / "story.jsonl"
            write_story(story)
            document = plan_input()
            middle = document["chapters"][0]["events"][1]
            middle["kind"] = "transition"
            middle["control"] = "passive"
            final = document["chapters"][0]["events"][2]
            final["control"] = "automatic"
            final["successors"] = ["event-1"]

            with self.assertRaisesRegex(LiveSequencePlanError, "automatic cycle"):
                write_live_sequence_plan(root / "plan.json", document, story)
