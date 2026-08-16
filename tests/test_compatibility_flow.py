import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from vntts_artifacts.file_integrity import sha256_file
from vntts_artifacts.game_pack import GamePackError, load_game_pack, write_game_pack
from vntts_artifacts.generated_audio import (
    GeneratedAudioIndex,
    write_generated_audio_manifest,
)
from vntts_artifacts.story_index import load_story_index, write_story_index
from vntts_artifacts.voice_generation_queue import (
    expected_voice_generation_queue_id,
    load_voice_generation_queue,
    write_voice_generation_queue,
)
from vntts_artifacts.voice_manifest import write_voice_manifest


class SyntheticCompatibilityFlowTest(unittest.TestCase):
    def test_extractor_output_reaches_consumer_with_every_identity_and_checksum_intact(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            story_path = root / "story.jsonl"
            extractor_line = {
                "record_type": "line",
                "line_id": "synthetic:chapter-1:line-7",
                "chapter": "chapter-1",
                "sequence": 7,
                "speaker": "Ada",
                "voice_character": "Ada",
                "text": "Keep this exact line intact.",
                "kind": "dialogue",
                "collection_id": "main-story",
                "audio_status": "no_audio",
                "audio_reason": "not_resolved",
                "source_kind": "story",
            }
            write_story_index(
                story_path,
                {
                    "game": "Synthetic Game",
                    "language": "en",
                    "collections": [
                        {
                            "collection_id": "main-story",
                            "title": "Main Story",
                            "kind": "story",
                            "order": 1,
                        }
                    ],
                },
                [extractor_line],
            )
            story_metadata, story_lines = load_story_index(story_path)
            story_line = story_lines[0]

            queue_path = root / "generation-queue.jsonl"
            queue_id = expected_voice_generation_queue_id(
                story_line.line_id, story_line.text_sha256
            )
            write_voice_generation_queue(
                queue_path,
                {
                    "game": story_metadata["game"],
                    "language": story_metadata["language"],
                    "generated_at": "2026-08-16T12:00:00Z",
                    "source_story_index": str(story_path),
                    "source_story_index_sha256": sha256_file(story_path),
                    "character_count": 1,
                    "source_audio_status_counts": {"no_audio": 1},
                    "action_counts": {"generate": 1},
                    "source_kind_counts": {"story": 1},
                },
                [
                    {
                        "record_type": "generation_item",
                        "queue_id": queue_id,
                        "line_id": story_line.line_id,
                        "text_sha256": story_line.text_sha256,
                        "speaker": story_line.speaker,
                        "voice_character": extractor_line["voice_character"],
                        "text": story_line.text,
                        "kind": story_line.kind,
                        "source_kind": extractor_line["source_kind"],
                        "source_audio_status": extractor_line["audio_status"],
                        "source_audio_reason": extractor_line["audio_reason"],
                        "action": "generate",
                        "state": "pending",
                    }
                ],
            )
            queue_metadata, queue_items = load_voice_generation_queue(queue_path)
            queue_item = queue_items[0]

            generated_wav = root / "generated" / "line-7.wav"
            generated_wav.parent.mkdir()
            generated_wav.write_bytes(b"synthetic generated WAV")
            generated_manifest = root / "generated-audio.json"
            write_generated_audio_manifest(
                generated_manifest,
                {
                    "game": queue_metadata["game"],
                    "language": queue_metadata["language"],
                    "source_queue_sha256": sha256_file(queue_path),
                },
                [
                    {
                        "line_id": queue_item.line_id,
                        "text_sha256": queue_item.text_sha256,
                        "audio": "generated/line-7.wav",
                        "audio_format": "wav-pcm16-mono",
                        "audio_sha256": sha256_file(generated_wav),
                        "sample_rate": 24_000,
                        "sample_count": 24_000,
                        "source_queue_id": queue_item.queue_id,
                    }
                ],
            )

            voice_wav = root / "voices" / "ada.wav"
            voice_wav.parent.mkdir()
            voice_wav.write_bytes(b"synthetic reference WAV")
            voice_manifest = root / "voice-manifest.json"
            write_voice_manifest(
                voice_manifest,
                {
                    "version": 2,
                    "voices": [
                        {
                            "character": "Ada",
                            "speaker": "ada-v1",
                            "references": ["voices/ada.wav"],
                        }
                    ],
                },
            )

            game_pack_path = root / "game-pack.json"
            write_game_pack(
                game_pack_path,
                {
                    "game": {"id": "synthetic-game", "version": "1.0"},
                    "producers": [
                        {"name": "synthetic-extractor", "version": "1.0"},
                        {"name": "synthetic-vntts", "version": "1.0"},
                    ],
                    "created_at": "2026-08-16T12:05:00Z",
                    "org.example.compatibility": {"source_queue": queue_path.name},
                },
                {
                    "story_index": story_path,
                    "voice_manifest": voice_manifest,
                    "generated_audio": generated_manifest,
                },
            )

            pack = load_game_pack(game_pack_path)
            consumer_story_metadata, consumer_story_lines = load_story_index(pack.story_index.path)
            generated_index = GeneratedAudioIndex.load(pack.generated_audio.path)
            generated_entry = generated_index.find(
                consumer_story_lines[0].line_id,
                consumer_story_lines[0].text_sha256,
            )

            self.assertEqual(consumer_story_metadata["game"], "Synthetic Game")
            self.assertEqual(story_line.source_audio_status, "absent")
            self.assertEqual(queue_item.queue_id, queue_id)
            self.assertEqual(generated_entry.audio, generated_wav.resolve())
            self.assertEqual(pack.generated_wavs[0].path, generated_wav.resolve())
            self.assertEqual(
                pack.extensions["org.example.compatibility"]["source_queue"],
                queue_path.name,
            )

            generated_wav.write_bytes(b"tampered generated WAV")
            with self.assertRaisesRegex(GamePackError, "checksum does not match"):
                load_game_pack(game_pack_path)


if __name__ == "__main__":
    unittest.main()
