# VNTTS Artifacts

Small Python contracts shared by applications that produce or consume VNTTS
data. The core is dependency-free; PCM WAV publication has an optional NumPy
extra.

The package owns versioned artifact formats and delegates generic publication
and checksum primitives to the separately released `durable-file` package. It
intentionally excludes OCR, TTS engines, user interfaces, provider integrations,
and game-specific extraction.

## Contracts

- `vntts.story-index` JSONL, schema version 1
- `vntts.generated-audio` JSON, schema version 1, with exact lookup by stable
  story line ID and SHA-256 of the current story text
- `vntts.voice-generation-queue` JSONL, schema version 1, with immutable line,
  text, queue, source-audio, and authoring-action identity
- `vntts.game-pack` JSON, schema version 1, binding a game identity, producer
  provenance, story index, voice manifest, all referenced voice WAVs, and an
  optional generated-audio manifest with all of its WAVs
- VNTTS voice manifest JSON, version 2, with read compatibility for legacy
  unversioned manifests
- atomic file publication, streaming SHA-256, stable text hashes and artifact
  slugs
- deterministic game-pack artifact bindings with portable relative paths and
  full-file SHA-256 validation before a consumer trusts a pack
- the `wav-pcm16-mono` format constant plus shared PCM WAV probing, reading and
  atomic publication helpers

Generated-audio entries use portable POSIX-relative paths, mono 16-bit PCM WAV,
and include the audio SHA-256, sample rate, and sample count. Consumers reject
missing or modified files and must fall back to live synthesis when an exact
identity is not available.

```json
{
  "schema": "vntts.generated-audio",
  "schema_version": 1,
  "entry_count": 1,
  "entries": [
    {
      "line_id": "game:chapter:line",
      "text_sha256": "<lowercase SHA-256 of exact UTF-8 story text>",
      "audio": "audio/game-chapter-line.wav",
      "audio_format": "wav-pcm16-mono",
      "audio_sha256": "<lowercase SHA-256 of the WAV file>",
      "sample_rate": 24000,
      "sample_count": 48000
    }
  ]
}
```

Top-level and entry-level producer provenance fields are preserved as contract
extensions.

Story-index metadata may declare ordered authoring collections. Each collection
requires `collection_id`, `title`, `kind`, and an integer `order`; line records
may carry an optional `collection_id`, which must refer to a declared collection.
Additional collection fields are preserved for producers.

## Voice-generation queues

The version 1 queue is an authoring exchange, not execution state. Its first
JSONL row is a metadata record with `schema`, `schema_version`, and
`item_count`; following rows have `record_type: "generation_item"`. The shared
reader validates the exact UTF-8 text SHA-256 and the stable queue identity:

```text
queue_id = line_id + ":" + text_sha256[:16]
```

When `source_audio_status` is present, its action is fixed:

| Source-audio status | Action |
| --- | --- |
| `no_audio` | `generate` |
| `configured_unavailable` | `prefer_source_audio` |
| `unresolved` | `manual_review` |
| `unchecked` | `resolve_audio` |

The reader also rejects duplicate line or queue IDs, mismatched summary counts,
invalid hashes and timestamps, unsupported actions, non-pending embedded states,
and unsafe source-field types. A producer's `source_story_index` is retained
only as untrusted provenance text: the reader never resolves or opens that
machine-local path. Delivery annotations and other producer fields are
preserved verbatim.

```python
from vntts_artifacts import (
    VoiceGenerationQueue,
    load_voice_generation_queue,
    write_voice_generation_queue,
)

queue_path = write_voice_generation_queue(output, metadata, generation_items)
metadata, typed_items = load_voice_generation_queue(queue_path)
queue = VoiceGenerationQueue.load(queue_path)

# A loaded typed item can be republished without losing producer extensions.
write_voice_generation_queue(copy, queue.metadata, queue.items)
```

Queue construction, filtering, model execution, retries, review state, and
resumable job state remain application responsibilities.

The complete extraction-to-consumption identity flow and its synthetic
compatibility fixture are documented in
[`docs/authoring-exchange.md`](docs/authoring-exchange.md).
Release-level producer and consumer support for every current wire format is
listed in [`docs/compatibility-matrix.md`](docs/compatibility-matrix.md).

## Game packs

A version 1 game pack is a JSON document with this envelope:

```json
{
  "schema": "vntts.game-pack",
  "schema_version": 1,
  "game": {"id": "example-game", "version": "1.2.3"},
  "producers": [{"name": "extractor", "version": "2.0.0"}],
  "created_at": "2026-08-16T12:00:00Z",
  "components": {
    "story_index": {"path": "story.jsonl", "sha256": "<lowercase SHA-256>"},
    "voice_manifest": {"path": "voices.json", "sha256": "<lowercase SHA-256>"},
    "voice_wavs": [
      {"path": "voices/ada.wav", "sha256": "<lowercase SHA-256>"}
    ],
    "generated_audio": {
      "manifest": {
        "path": "generated-audio.json",
        "sha256": "<lowercase SHA-256>"
      },
      "wavs": [
        {"path": "generated/line-1.wav", "sha256": "<lowercase SHA-256>"}
      ]
    }
  },
  "org.example.provenance": {"build_id": "optional opaque extension"}
}
```

`story_index`, `voice_manifest`, and `voice_wavs` are required;
`generated_audio` is optional. Every path is POSIX-relative to the pack
directory. The reader rejects missing or modified files, absolute paths, path
traversal, duplicate bindings, referenced-but-undeclared WAVs, declared WAVs
that are not referenced, unsupported component names, and unnamespaced unknown
top-level fields. A top-level extension name must contain at least one dot.
Extensions are returned as opaque metadata and never interpreted as trusted
artifacts.

The writer derives nested WAV bindings from the two manifests, so callers only
provide the three semantic component paths:

```python
from vntts_artifacts import load_game_pack, write_game_pack

pack = write_game_pack(
    pack_directory / "game-pack.json",
    {
        "game": {"id": "example-game", "version": "1.2.3"},
        "producers": [{"name": "extractor", "version": "2.0.0"}],
        "created_at": "2026-08-16T12:00:00Z",
    },
    {
        "story_index": story_index,
        "voice_manifest": voice_manifest,
        "generated_audio": generated_audio_manifest,
    },
)

# Loading repeats complete validation before returning absolute, resolved paths.
pack = load_game_pack(pack_directory / "game-pack.json")
story_index_path = pack.story_index.path
voice_wav_paths = tuple(binding.path for binding in pack.voice_wavs)
```

The lower-level checksum helpers remain available when assembling other
contracts. They bind files without embedding machine-local paths:

```python
from vntts_artifacts.game_pack import (
    create_game_pack_artifact_bindings,
    validate_game_pack_artifact_bindings,
)

bindings = create_game_pack_artifact_bindings(
    pack_directory,
    {
        "story_index": story_index,
        "voice_manifest": voice_manifest,
        "generated_audio": generated_audio_manifest,
    },
)
validated = validate_game_pack_artifact_bindings(
    pack_directory,
    bindings,
    required=("story_index", "voice_manifest"),
)
```

## Development

```bash
python -m unittest discover -s tests
```

Install `vntts-artifacts[audio]` when using `write_pcm16_wav`.

Releases use matching package versions and immutable Git tags such as `v0.1.0`.
Package metadata currently targets the unpublished `0.6.0` release candidate;
see [`CHANGELOG.md`](CHANGELOG.md) for its durable release notes. Do not treat
it as available until the immutable `v0.6.0` tag and release are published.
