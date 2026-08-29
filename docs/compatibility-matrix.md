# Contract compatibility matrix

This matrix describes wire-format support in immutable `vntts-artifacts`
releases. “Producer” means the package can publish a validated artifact;
“consumer” means it can parse and validate that artifact through a public API.

| Contract | Current wire version | First producer support | First consumer support | Current public APIs |
| --- | ---: | --- | --- | --- |
| Story index (`vntts.story-index`) | 1 | `v0.1.0` | `v0.1.0` | Legacy line APIs since `v0.1.0`; `StoryIndexDocument`, `load_story_index_document`, and `write_story_index_document` since `v0.6.1` |
| Voice manifest | 2 | `v0.1.0` | `v0.1.0` | `write_voice_manifest`, `load_voice_manifest` |
| Generated audio (`vntts.generated-audio`) | 1 | `v0.2.0` | `v0.2.0` | Legacy manifest/index APIs since `v0.2.0`; lossless `GeneratedAudioDocument`, `GeneratedAudioRecord`, `load_generated_audio_document`, and `write_generated_audio_document` since `v0.6.2` |
| Live sequence (`vntts.live-sequence-plan`) | 1 | `v0.7.0` | `v0.7.0` | `LiveSequencePlan`, `load_live_sequence_plan`, `write_live_sequence_plan` |
| Game pack (`vntts.game-pack`) | 2 | `v0.7.0` | `v0.7.0` | `write_game_pack`, `load_game_pack`; schema-v1 read compatibility since `v0.7.0` |
| Voice-generation queue (`vntts.voice-generation-queue`) | 1 | `v0.6.0` | `v0.6.0` | Reader/writer since `v0.6.0`; canonical `voice_generation_action` policy since `v0.6.1` |

## Release boundaries

- `v0.5.0` contains deterministic game-pack checksum-binding helpers, but not
  the complete `vntts.game-pack` document reader or writer. It must not be
  treated as game-pack schema version 1 support.
- `v0.6.0` is the first immutable release containing the complete game-pack and
  voice-generation-queue readers and writers. Both applications now pin this
  exact release.
- `v0.6.1` is the first release containing the lossless story-index
  `StoryIndexDocument`, `StoryIndexRecord`, and `StoryIndexCollection` APIs.
  It also adds canonical story-status queue policy while preserving legacy
  extractor queue statuses. These are package API additions without a wire
  version change.
- `v0.6.2` is the first release containing the lossless generated-audio
  document/record APIs. It also rejects absolute, traversal, backslash and
  symlinked standalone voice/generated artifact references and makes the shared
  PCM writer a strict finite one-dimensional mono boundary. Wire versions stay
  unchanged.
- `v0.7.0` introduces live-sequence schema version 1 and game-pack schema
  version 2. The new game-pack version is necessary because v0.6.x schema-v1
  readers correctly reject unknown core components. Its loader still accepts
  immutable schema-v1 packs; its writer emits schema v2.
- `v0.7.1` preserves those wire versions and rejects unguarded automatic cycles
  that cross runtime-transparent passive transitions.
- Generated-audio schema version 1 first shipped in `v0.2.0`. `v0.3.0`
  centralized its hashing and WAV primitives without changing the wire version.
  The lossless document/record APIs added in `v0.6.2` preserve complete
  provenance and producer extensions without changing that wire version.
- Story-index collection metadata, canonical source-audio fields, and their
  legacy extractor mappings were added without changing story-index schema
  version 1 because the format preserves producer extensions and older readers
  can ignore those optional fields.

## Consumer rules

- Story-index, generated-audio, live-sequence and voice-generation-queue readers
  accept only the exact schema and version shown above. The game-pack reader is
  the deliberate exception: v0.7.0 accepts schema versions 1 and 2 so existing
  packs remain consumable.
- Voice-manifest readers accept version 2. `load_voice_manifest` can also read
  the older unversioned shape when `allow_legacy=True`; writers always publish
  version 2.
- Generated audio is reusable only for an exact `(line_id, text_sha256)` match.
- Queue identity is stable only for the exact line ID and text revision:
  `queue_id = line_id + ":" + text_sha256[:16]`.
- Legacy queue status/action pairs remain unchanged. Canonical story statuses
  use `absent` -> `generate`, `unavailable` -> `prefer_source_audio`, and
  exclude `available`; `unknown` must serialize either `resolve_audio` or
  `manual_review` as an explicit producer policy.
- A game-pack consumer trusts only resolved paths returned by `load_game_pack`
  after the complete checksum and nested-reference validation succeeds.
- A live sequence plan is reusable only with the exact story-index bytes named
  by its SHA-256. A game pack additionally requires the plan and pack game IDs
  to match.

## Additive story-index APIs

The lossless story-index `StoryIndexDocument`, `StoryIndexRecord`, and
`StoryIndexCollection` APIs preserve producer-owned authoring fields without a
wire-version change. They first ship in `v0.6.1`; consumers must use `v0.6.1`
or newer before importing these Python symbols. Older schema-v1 consumers
remain wire-compatible and may continue ignoring producer extensions.

## Additive generated-audio APIs

The `GeneratedAudioDocument` and `GeneratedAudioRecord` APIs retain
complete top-level metadata and per-entry extensions, including common
generation provenance. Existing `GeneratedAudioIndex` and
`load_generated_audio_manifest` return shapes remain unchanged. The symbols
first ship in `v0.6.2`; schema-v1 files remain compatible with every release
listed in the main table.

## Adoption evidence

The release and both consumer pins were independently checked on 2026-08-16:

- The published annotated `v0.6.0` tag in origin peels to
  `9898f229673b99ed77a718b18fb3247d7f1c5fcf`.
- `reverse1999-extractor` commit
  `36c3002735afdb5d3a27c48b923ec614412b310d` pins tag `v0.6.0` in
  `pyproject.toml`; its `uv.lock` resolves that tag to `9898f229...`. Its
  adoption suite passed 160 tests.
- VNTTS commit `67e7ef95831f67d40df48a7d9df8f942eb4b7399` pins tag `v0.6.0`
  in `pyproject.toml`; its `uv.lock` resolves that tag to `9898f229...`. Its
  adoption suite passed 589 tests.

The synthetic compatibility flow in
[`authoring-exchange.md`](authoring-exchange.md) verifies the contracts together
inside this package; the consumer evidence above verifies the released boundary
across all three repositories.
