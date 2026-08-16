# Contract compatibility matrix

This matrix describes wire-format support in immutable `vntts-artifacts`
releases. “Producer” means the package can publish a validated artifact;
“consumer” means it can parse and validate that artifact through a public API.

| Contract | Current wire version | First producer support | First consumer support | Current public APIs |
| --- | ---: | --- | --- | --- |
| Story index (`vntts.story-index`) | 1 | `v0.1.0` | `v0.1.0` | Legacy line APIs since `v0.1.0`; `StoryIndexDocument`, `load_story_index_document`, and `write_story_index_document` since `v0.6.1` |
| Voice manifest | 2 | `v0.1.0` | `v0.1.0` | `write_voice_manifest`, `load_voice_manifest` |
| Generated audio (`vntts.generated-audio`) | 1 | `v0.2.0` | `v0.2.0` | `write_generated_audio_manifest`, `GeneratedAudioIndex.load` |
| Game pack (`vntts.game-pack`) | 1 | `v0.6.0` | `v0.6.0` | `write_game_pack`, `load_game_pack` |
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
- Generated-audio schema version 1 first shipped in `v0.2.0`. `v0.3.0`
  centralized its hashing and WAV primitives without changing the wire version.
- Story-index collection metadata, canonical source-audio fields, and their
  legacy extractor mappings were added without changing story-index schema
  version 1 because the format preserves producer extensions and older readers
  can ignore those optional fields.

## Consumer rules

- Story-index, generated-audio, game-pack, and voice-generation-queue readers
  accept only the exact schema and version shown above.
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

## Additive story-index APIs

The lossless story-index `StoryIndexDocument`, `StoryIndexRecord`, and
`StoryIndexCollection` APIs preserve producer-owned authoring fields without a
wire-version change. They first ship in `v0.6.1`; consumers must use `v0.6.1`
or newer before importing these Python symbols. Older schema-v1 consumers
remain wire-compatible and may continue ignoring producer extensions.

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
