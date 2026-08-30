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
- `vntts.live-sequence-plan` JSON, schema version 1, binding explicit story
  control flow to exact story-index bytes and stable line identities
- `vntts.game-pack` JSON, schema version 2, binding a game identity, producer
  provenance, story index, voice manifest, all referenced voice WAVs, optional
  generated audio and an optional live sequence plan
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

Generic authoring and review tools can preserve and inspect those extensions
through the additive lossless document API:

```python
from vntts_artifacts import GeneratedAudioDocument, write_generated_audio_document

document = GeneratedAudioDocument.load(generated_audio_path)
record = document.find(line_id, text_sha256)
provenance = None if record is None else record.synthesis_provenance_sha256
copy = write_generated_audio_document(output_path, document.metadata, document.records)
```

`GeneratedAudioRecord` remains a subtype of `GeneratedAudioEntry`; existing
`GeneratedAudioIndex` and `load_generated_audio_manifest` callers retain their
original return types. See
[`docs/generated-audio-authoring.md`](docs/generated-audio-authoring.md) for
validation, extension, and release-boundary guidance.

Story-index metadata may declare ordered authoring collections. Each collection
requires `collection_id`, `title`, `kind`, and an integer `order`; line records
may carry an optional `collection_id`, which must refer to a declared collection.
Additional collection fields are preserved for producers.

Generic authoring tools should use the additive lossless document API:

```python
from vntts_artifacts import StoryIndexDocument, write_story_index_document

document = StoryIndexDocument.load(story_index_path)
records = document.records_for_collection("main-story", speakable_only=True)
for record in records:
    queue_id = f"{record.line_id}:{record.text_sha256[:16]}"
    voice = record.voice_character
    context = record.context or {
        "previous_text": record.previous_text,
        "next_text": record.next_text,
    }

# Typed records retain their complete producer record when republished.
copy = write_story_index_document(output_path, document.metadata, document.records)
```

`StoryIndexRecord` remains a subtype of `StoryIndexLine`, while `to_record()`
and `producer_fields` expose lossless producer data. Existing
`load_story_index` callers keep their original `(metadata, StoryIndexLine...)`
return shape. Detailed validation and compatibility guidance is in
[`docs/story-index-authoring.md`](docs/story-index-authoring.md).

## Voice-generation queues

The version 1 queue is an authoring exchange, not execution state. Its first
JSONL row is a metadata record with `schema`, `schema_version`, and
`item_count`; following rows have `record_type: "generation_item"`. The shared
reader validates the exact UTF-8 text SHA-256 and the stable queue identity:

```text
queue_id = line_id + ":" + text_sha256[:16]
```

Legacy extractor queue statuses retain their exact version 1 actions:

| Source-audio status | Action |
| --- | --- |
| `no_audio` | `generate` |
| `configured_unavailable` | `prefer_source_audio` |
| `unresolved` | `manual_review` |
| `unchecked` | `resolve_audio` |

Generic builders consuming `StoryIndexRecord` use canonical policy:

| Canonical status | Queue policy |
| --- | --- |
| `absent` | `generate` |
| `unavailable` | `prefer_source_audio` |
| `available` | Exclude the line, except `source_audio_completeness=partial` returns `generate` for the complete displayed-text continuation |
| `unknown` | Explicitly choose `resolve_audio` or `manual_review` |

```python
action = voice_generation_action(
    record.source_audio_status,
    unknown_action="resolve_audio",
)
if action is None:
    continue
```

Canonical `unknown` has no package default because legacy `unchecked` and
`unresolved` both normalize to it but require different authoring actions. The
chosen action is stored in the queue and validated by the reader.

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
    voice_generation_action,
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

## Live sequence plans

A sequence plan is producer-owned control flow for one exact story index. Its
speech events bind stable line IDs; silent boxes, passive transitions, choices
and manual waits remain explicit graph events. The reader rejects a changed
story index, missing or cross-chapter successors, unreachable nodes and
unguarded automatic cycles.

```python
from vntts_artifacts import load_live_sequence_plan, write_live_sequence_plan

plan = write_live_sequence_plan(output, producer_document, story_index)
plan = load_live_sequence_plan(output, story_index)
event = plan.event_for_line("game:chapter:line")
```

The document retains the producer name/version and SHA-256 of the source
extract. The writer calculates the story-index SHA-256 and validates a temporary
candidate before publishing the requested path.

## Game packs

A version 2 game pack is a JSON document with this envelope:

```json
{
  "schema": "vntts.game-pack",
  "schema_version": 2,
  "game": {"id": "example-game", "version": "1.2.3"},
  "producers": [{"name": "extractor", "version": "2.0.0"}],
  "created_at": "2026-08-16T12:00:00Z",
  "components": {
    "story_index": {"path": "story.jsonl", "sha256": "<lowercase SHA-256>"},
    "voice_manifest": {"path": "voices.json", "sha256": "<lowercase SHA-256>"},
    "voice_wavs": [
      {"path": "voices/ada.wav", "sha256": "<lowercase SHA-256>"}
    ],
    "live_sequence_plan": {
      "path": "live-sequence.json",
      "sha256": "<lowercase SHA-256>"
    },
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
`generated_audio` and `live_sequence_plan` are optional. Every path is
POSIX-relative to the pack
directory. The reader rejects missing or modified files, absolute paths, path
traversal, duplicate bindings, referenced-but-undeclared WAVs, declared WAVs
that are not referenced, unsupported component names, and unnamespaced unknown
top-level fields. A top-level extension name must contain at least one dot.
Extensions are returned as opaque metadata and never interpreted as trusted
artifacts. The loader retains schema-v1 read compatibility, while the writer
emits schema v2; a sequence-plan component is never accepted under schema v1.

The writer derives nested WAV bindings from the two manifests, so callers only
provide semantic component paths rather than duplicating referenced WAV lists:

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
        "live_sequence_plan": live_sequence_plan,
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

Install `vntts-artifacts[audio]` when using `write_pcm16_wav`. The writer is a
strict mono boundary: samples must be a one-dimensional finite float sequence,
and the sample rate must be a positive non-boolean integer. Callers rendering
multiple channels must downmix explicitly before invoking it.

Releases use matching package versions and immutable Git tags such as `v0.1.0`.
`v0.7.2` adds the fail-closed partial source-cue continuation exception without
changing the queue wire schema.
`v0.7.1` makes passive transitions part of unguarded automatic-cycle detection.
`v0.7.0` adds the live-sequence contract and game-pack schema v2 while retaining
schema-v1 read compatibility. `v0.6.2` adds the lossless generated-audio
document API, strict mono writer validation, and contained standalone
voice/generated reference paths. `v0.6.1`
is the first release containing the lossless story-index document API, while
`v0.6.0` remains the first complete game-pack and voice-generation-queue
release. See [`CHANGELOG.md`](CHANGELOG.md) for durable release notes and
[`docs/compatibility-matrix.md`](docs/compatibility-matrix.md) for exact API
boundaries and existing consumer adoption evidence.
