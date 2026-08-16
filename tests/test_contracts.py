import hashlib
import json
import unittest
import wave
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from vntts_artifacts.audio import (
    PCM16_MONO_WAV_FORMAT,
    Pcm16MonoWavError,
    probe_pcm16_mono_wav,
    read_pcm16_mono_wav,
    write_pcm16_wav,
)
from vntts_artifacts.file_integrity import sha256_file
from vntts_artifacts.game_pack import (
    GAME_PACK_SCHEMA,
    GAME_PACK_SCHEMA_VERSION,
    GamePackError,
    create_game_pack_artifact_bindings,
    load_game_pack,
    validate_game_pack_artifact_bindings,
    write_game_pack,
)
from vntts_artifacts.generated_audio import (
    GeneratedAudioIndex,
    GeneratedAudioManifestError,
    text_sha256,
    write_generated_audio_manifest,
)
from vntts_artifacts.hashing import text_sha256 as shared_text_sha256
from vntts_artifacts.story_index import StoryIndexError, load_story_index, write_story_index
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
    def _write_complete_game_pack_fixture(self, root):
        story = root / "story.jsonl"
        write_story_index(
            story,
            {"game": "Example"},
            [
                {
                    "record_type": "line",
                    "line_id": "game:1",
                    "chapter": "1",
                    "sequence": 1,
                    "speaker": "Ada",
                    "text": "Hello",
                    "kind": "dialogue",
                }
            ],
        )
        voice_wav = root / "voices" / "ada.wav"
        voice_wav.parent.mkdir()
        voice_wav.write_bytes(b"voice WAV fixture")
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
        generated_wav = root / "generated" / "game-1.wav"
        generated_wav.parent.mkdir()
        generated_wav.write_bytes(b"generated WAV fixture")
        generated_manifest = root / "generated-audio.json"
        write_generated_audio_manifest(
            generated_manifest,
            {},
            [
                {
                    "line_id": "game:1",
                    "text_sha256": text_sha256("Hello"),
                    "audio": "generated/game-1.wav",
                    "audio_format": "wav-pcm16-mono",
                    "audio_sha256": sha256_file(generated_wav),
                    "sample_rate": 24_000,
                    "sample_count": 10,
                }
            ],
        )
        manifest = root / "game-pack.json"
        pack = write_game_pack(
            manifest,
            {
                "game": {"id": "example", "version": "1.2.3"},
                "producers": [{"name": "fixture-builder", "version": "2.0"}],
                "created_at": "2026-08-16T12:00:00+03:00",
                "org.example.provenance": {"source": "synthetic"},
            },
            {
                "story_index": story,
                "voice_manifest": voice_manifest,
                "generated_audio": generated_manifest,
            },
        )
        return pack, manifest, voice_wav, generated_wav

    def test_game_pack_document_round_trip_returns_resolved_typed_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pack, manifest, voice_wav, generated_wav = self._write_complete_game_pack_fixture(root)
            document = json.loads(manifest.read_text(encoding="utf-8"))

        self.assertEqual(document["schema"], GAME_PACK_SCHEMA)
        self.assertEqual(document["schema_version"], GAME_PACK_SCHEMA_VERSION)
        self.assertEqual(pack.game_id, "example")
        self.assertEqual(pack.producers[0].name, "fixture-builder")
        self.assertEqual(pack.story_index.path.name, "story.jsonl")
        self.assertEqual(pack.voice_wavs[0].path, voice_wav.resolve())
        self.assertEqual(pack.generated_wavs[0].path, generated_wav.resolve())
        self.assertEqual(pack.extensions["org.example.provenance"]["source"], "synthetic")

    def test_game_pack_generated_audio_component_is_optional(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            complete, _manifest, _voice_wav, _generated_wav = (
                self._write_complete_game_pack_fixture(root)
            )
            pack = write_game_pack(
                root / "minimal-game-pack.json",
                {
                    "game": {"id": "example", "version": "1.2.3"},
                    "producers": [{"name": "fixture-builder", "version": "2.0"}],
                    "created_at": "2026-08-16T12:00:00Z",
                },
                {
                    "story_index": complete.story_index.path,
                    "voice_manifest": complete.voice_manifest.path,
                },
            )

        self.assertIsNone(pack.generated_audio)
        self.assertEqual(pack.generated_wavs, ())

    def test_game_pack_rejects_tampered_and_undeclared_referenced_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _pack, manifest, voice_wav, _generated_wav = self._write_complete_game_pack_fixture(
                root
            )
            voice_wav.write_bytes(b"tampered")
            with self.assertRaisesRegex(GamePackError, "checksum does not match"):
                load_game_pack(manifest)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _pack, manifest, _voice_wav, _generated_wav = self._write_complete_game_pack_fixture(
                root
            )
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["components"]["voice_wavs"] = []
            manifest.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(GamePackError, "not declared"):
                load_game_pack(manifest)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _pack, manifest, _voice_wav, _generated_wav = self._write_complete_game_pack_fixture(
                root
            )
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["components"]["generated_audio"]["wavs"] = []
            manifest.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(GamePackError, "not declared"):
                load_game_pack(manifest)

    def test_game_pack_rejects_extra_declared_wav(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _pack, manifest, _voice_wav, _generated_wav = self._write_complete_game_pack_fixture(
                root
            )
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["components"]["voice_wavs"].append(
                document["components"]["generated_audio"]["wavs"][0]
            )
            manifest.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(GamePackError, "not referenced"):
                load_game_pack(manifest)

    def test_game_pack_rejects_unsafe_paths_unknown_core_fields_and_components(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _pack, manifest, _voice_wav, _generated_wav = self._write_complete_game_pack_fixture(
                root
            )
            original = json.loads(manifest.read_text(encoding="utf-8"))
            unsafe = json.loads(json.dumps(original))
            unsafe["components"]["story_index"]["path"] = "../story.jsonl"
            manifest.write_text(json.dumps(unsafe), encoding="utf-8")
            with self.assertRaisesRegex(GamePackError, "safe relative path"):
                load_game_pack(manifest)

            absolute = json.loads(json.dumps(original))
            absolute["components"]["story_index"]["path"] = str(root / "story.jsonl")
            manifest.write_text(json.dumps(absolute), encoding="utf-8")
            with self.assertRaisesRegex(GamePackError, "safe relative path"):
                load_game_pack(manifest)

            unknown_field = json.loads(json.dumps(original))
            unknown_field["producer_notes"] = "not namespaced"
            manifest.write_text(json.dumps(unknown_field), encoding="utf-8")
            with self.assertRaisesRegex(GamePackError, "Unsupported game-pack field"):
                load_game_pack(manifest)

            unknown_component = json.loads(json.dumps(original))
            unknown_component["components"]["subtitles"] = original["components"]["story_index"]
            manifest.write_text(json.dumps(unknown_component), encoding="utf-8")
            with self.assertRaisesRegex(GamePackError, "Unsupported game-pack component"):
                load_game_pack(manifest)

    def test_game_pack_rejects_invalid_metadata_and_missing_required_component(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            story = root / "story.jsonl"
            story.write_text("unused", encoding="utf-8")
            with self.assertRaisesRegex(GamePackError, "missing required component"):
                write_game_pack(
                    root / "game-pack.json",
                    {
                        "game": {"id": "example", "version": "1"},
                        "producers": [{"name": "test", "version": "1"}],
                        "created_at": "2026-08-16T12:00:00",
                    },
                    {"story_index": story},
                )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _pack, manifest, _voice_wav, _generated_wav = self._write_complete_game_pack_fixture(
                root
            )
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["created_at"] = "2026-08-16T12:00:00"
            manifest.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(GamePackError, "timezone"):
                load_game_pack(manifest)

    def test_game_pack_artifact_checksums_bind_and_validate_portable_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            story = root / "story" / "index.jsonl"
            voices = root / "voices" / "manifest.json"
            story.parent.mkdir()
            voices.parent.mkdir()
            story.write_bytes(b"story index")
            voices.write_bytes(b"voice manifest")

            bindings = create_game_pack_artifact_bindings(
                root,
                {
                    "voice_manifest": voices,
                    "story_index": story,
                },
            )
            bindings["voice_manifest"]["producer_field"] = "preserved compatibility"
            validated = validate_game_pack_artifact_bindings(
                root,
                bindings,
                required=("story_index", "voice_manifest"),
            )

        self.assertEqual(list(bindings), ["story_index", "voice_manifest"])
        self.assertEqual(bindings["story_index"]["path"], "story/index.jsonl")
        self.assertEqual(
            bindings["story_index"]["sha256"], hashlib.sha256(b"story index").hexdigest()
        )
        self.assertEqual(
            [(entry.name, entry.path.name) for entry in validated],
            [("story_index", "index.jsonl"), ("voice_manifest", "manifest.json")],
        )

    def test_game_pack_artifact_checksum_rejects_modified_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            story = root / "story.jsonl"
            story.write_bytes(b"original")
            bindings = create_game_pack_artifact_bindings(root, {"story_index": story})
            story.write_bytes(b"modified")

            with self.assertRaisesRegex(GamePackError, "checksum does not match"):
                validate_game_pack_artifact_bindings(root, bindings)

    def test_game_pack_artifact_checksum_rejects_unsafe_or_missing_bindings(self):
        digest = hashlib.sha256(b"outside").hexdigest()
        with TemporaryDirectory() as directory:
            root = Path(directory) / "pack"
            root.mkdir()
            outside = root.parent / "outside.json"
            outside.write_bytes(b"outside")
            with self.assertRaisesRegex(GamePackError, "leaves the pack directory"):
                create_game_pack_artifact_bindings(root, {"story_index": outside})
            with self.assertRaisesRegex(GamePackError, "safe relative path"):
                validate_game_pack_artifact_bindings(
                    root,
                    {"story_index": {"path": "../outside", "sha256": digest}},
                )
            with self.assertRaisesRegex(GamePackError, "missing required"):
                validate_game_pack_artifact_bindings(
                    root,
                    {"story_index": {"path": "story.jsonl", "sha256": digest}},
                    required=("story_index", "voice_manifest"),
                )

    def test_game_pack_artifact_checksum_rejects_malformed_digest(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            story = root / "story.jsonl"
            story.write_bytes(b"story")

            with self.assertRaisesRegex(GamePackError, "lowercase SHA-256"):
                validate_game_pack_artifact_bindings(
                    root,
                    {"story_index": {"path": "story.jsonl", "sha256": "ABC"}},
                )

    def test_pcm16_wav_round_trip_and_probe(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "audio.wav"
            write_pcm16_wav(path, [-1.0, -0.5, 0.0, 0.5, 1.0], 24_000)
            samples, info = read_pcm16_mono_wav(path)
            probed = probe_pcm16_mono_wav(path)

        self.assertEqual(PCM16_MONO_WAV_FORMAT, "wav-pcm16-mono")
        self.assertEqual(len(samples), 5)
        self.assertEqual(info.sample_rate, 24_000)
        self.assertEqual(info.sample_count, 5)
        self.assertEqual(probed, info)
        self.assertAlmostEqual(info.peak, 32767 / 32768)

    def test_pcm16_wav_probe_rejects_stereo(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "stereo.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(24_000)
                output.writeframes(b"\0" * 8)
            with self.assertRaisesRegex(Pcm16MonoWavError, "mono 16-bit"):
                probe_pcm16_mono_wav(path)

    def test_text_hash_is_shared_across_contracts(self):
        self.assertEqual(text_sha256("Hello"), shared_text_sha256("Hello"))

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

    def test_story_index_loads_canonical_source_audio_metadata(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            write_story_index(
                path,
                {"game": "Example"},
                [
                    {
                        "record_type": "line",
                        "line_id": "game:1",
                        "chapter": "1",
                        "sequence": 1,
                        "speaker": "Ada",
                        "text": "Hello",
                        "kind": "dialogue",
                        "source_audio_status": "available",
                        "source_audio_id": "voice-7",
                    }
                ],
            )
            _metadata, lines = load_story_index(path)

        self.assertEqual(lines[0].source_audio_status, "available")
        self.assertEqual(lines[0].source_audio_id, "voice-7")

    def test_story_index_maps_legacy_extractor_audio_metadata(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            write_story_index(
                path,
                {"game": "Example"},
                [
                    {
                        "record_type": "line",
                        "line_id": "game:1",
                        "chapter": "1",
                        "sequence": 1,
                        "speaker": "Ada",
                        "text": "Hello",
                        "kind": "dialogue",
                        "audio_status": "installed",
                        "source_voice_id": "voice-7",
                    }
                ],
            )
            _metadata, lines = load_story_index(path)

        self.assertEqual(lines[0].source_audio_status, "available")
        self.assertEqual(lines[0].source_audio_id, "voice-7")

    def test_story_index_validates_and_preserves_collections(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            metadata, lines = load_story_index(
                write_story_index(
                    path,
                    {
                        "game": "Example",
                        "collections": [
                            {
                                "collection_id": "main-story",
                                "title": "Main Story",
                                "kind": "story",
                                "order": 1,
                                "producer_field": "preserved",
                            }
                        ],
                    },
                    [
                        {
                            "record_type": "line",
                            "line_id": "game:1",
                            "chapter": "1",
                            "sequence": 1,
                            "speaker": "Ada",
                            "text": "Hello",
                            "collection_id": "main-story",
                        }
                    ],
                )
            )

        self.assertEqual(lines[0].collection_id, "main-story")
        self.assertEqual(metadata["collections"][0]["producer_field"], "preserved")

    def test_story_index_rejects_unknown_or_duplicate_collection_ids(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            record = {
                "record_type": "line",
                "line_id": "game:1",
                "chapter": "1",
                "sequence": 1,
                "speaker": "Ada",
                "text": "Hello",
                "collection_id": "missing",
            }
            with self.assertRaisesRegex(StoryIndexError, "not declared"):
                write_story_index(
                    path,
                    {
                        "collections": [
                            {
                                "collection_id": "main",
                                "title": "Main",
                                "kind": "story",
                                "order": 1,
                            }
                        ]
                    },
                    [record],
                )
            with self.assertRaisesRegex(StoryIndexError, "not declared"):
                write_story_index(path, {}, [record])
            with self.assertRaisesRegex(StoryIndexError, "Duplicate"):
                write_story_index(
                    path,
                    {
                        "collections": [
                            {
                                "collection_id": "main",
                                "title": "Main",
                                "kind": "story",
                                "order": 1,
                            },
                            {
                                "collection_id": "main",
                                "title": "Other",
                                "kind": "story",
                                "order": 2,
                            },
                        ]
                    },
                    [],
                )
            with self.assertRaisesRegex(StoryIndexError, "non-empty title"):
                write_story_index(
                    path,
                    {
                        "collections": [
                            {
                                "collection_id": "main",
                                "title": "",
                                "kind": "story",
                                "order": 1,
                            }
                        ]
                    },
                    [],
                )
            with self.assertRaisesRegex(StoryIndexError, "order must be an integer"):
                write_story_index(
                    path,
                    {
                        "collections": [
                            {
                                "collection_id": "main",
                                "title": "Main",
                                "kind": "story",
                                "order": True,
                            }
                        ]
                    },
                    [],
                )

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

    def test_generated_audio_round_trip_and_exact_lookup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio" / "game-1.wav"
            audio.parent.mkdir()
            audio.write_bytes(b"synthetic audio fixture")
            manifest = root / "generated-audio.json"
            write_generated_audio_manifest(
                manifest,
                {"game": "Example", "language": "en"},
                [
                    {
                        "line_id": "game:1",
                        "text_sha256": text_sha256("Hello"),
                        "audio": "audio/game-1.wav",
                        "audio_format": "wav-pcm16-mono",
                        "audio_sha256": sha256_file(audio),
                        "sample_rate": 24_000,
                        "sample_count": 48_000,
                        "provider": "synthetic-test",
                    }
                ],
            )

            index = GeneratedAudioIndex.load(manifest)
            raw_entry = json.loads(manifest.read_text(encoding="utf-8"))["entries"][0]

        self.assertEqual(index.metadata["schema"], "vntts.generated-audio")
        self.assertEqual(
            index.find("game:1", text_sha256("Hello"), verify_file=False).sample_rate,
            24_000,
        )
        self.assertIsNone(index.find("game:1", text_sha256("Changed")))
        self.assertEqual(raw_entry["provider"], "synthetic-test")

    def test_generated_audio_rejects_duplicate_identity_and_unsafe_paths(self):
        entry = {
            "line_id": "game:1",
            "text_sha256": hashlib.sha256(b"Hello").hexdigest(),
            "audio": "../outside.wav",
            "audio_format": "wav-pcm16-mono",
            "audio_sha256": hashlib.sha256(b"audio").hexdigest(),
            "sample_rate": 24_000,
            "sample_count": 1,
        }
        with TemporaryDirectory() as directory:
            manifest = Path(directory) / "generated-audio.json"
            with self.assertRaisesRegex(GeneratedAudioManifestError, "safe relative"):
                write_generated_audio_manifest(manifest, {}, [entry])

            safe_entry = {**entry, "audio": "audio.wav"}
            with self.assertRaisesRegex(GeneratedAudioManifestError, "Duplicate"):
                write_generated_audio_manifest(manifest, {}, [safe_entry, safe_entry])

    def test_generated_audio_lookup_rejects_modified_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "line.wav"
            audio.write_bytes(b"original")
            manifest = root / "generated-audio.json"
            write_generated_audio_manifest(
                manifest,
                {},
                [
                    {
                        "line_id": "game:1",
                        "text_sha256": text_sha256("Hello"),
                        "audio": "line.wav",
                        "audio_format": "wav-pcm16-mono",
                        "audio_sha256": sha256_file(audio),
                        "sample_rate": 24_000,
                        "sample_count": 1,
                    }
                ],
            )
            index = GeneratedAudioIndex.load(manifest)
            audio.write_bytes(b"modified")

            self.assertIsNone(index.find("game:1", text_sha256("Hello")))

    def test_story_index_rejects_text_hash_drift(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "story.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "record_type": "metadata",
                        "schema": "vntts.story-index",
                        "schema_version": 1,
                        "line_count": 1,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "record_type": "line",
                        "line_id": "game:1",
                        "chapter": "1",
                        "sequence": 1,
                        "speaker": "Ada",
                        "text": "Hello",
                        "text_sha256": "0" * 64,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StoryIndexError, "text_sha256"):
                load_story_index(path)


if __name__ == "__main__":
    unittest.main()
