# Changelog

## [0.7.0] - 2026-08-29

New sequence-first runtime contract and an intentionally versioned game-pack
component boundary.

### Added

- `vntts.live-sequence-plan` schema version 1 reader and writer with exact
  story-index SHA-256 binding, source-extract provenance, typed event graphs,
  explicit chapter entries and strict speech-line identity validation.
- Optional `live_sequence_plan` component in `vntts.game-pack` schema version
  2. Its artifact binding and nested story-index relationship are both checked
  before a consumer receives the path.

### Compatibility and safety

- The game-pack loader accepts immutable schema versions 1 and 2. Schema v1
  keeps its original component set and rejects a v2 sequence component; the
  writer emits only schema v2.
- Sequence validation rejects missing or cross-chapter successors, unreachable
  events, duplicate line bindings, unsupported controls, invalid terminal or
  manual boundaries and unguarded automatic cycles. Candidate plans are fully
  validated before atomic publication.

## [0.6.2] - 2026-08-26

Additive patch release for lossless generated-audio authoring and stricter
local-artifact containment. Existing wire schema versions remain unchanged.

### Added

- Lossless `GeneratedAudioDocument` and `GeneratedAudioRecord` APIs that retain
  complete metadata, common synthesis provenance, and all per-entry producer
  extensions while keeping generated-audio wire schema version 1 and the
  existing lightweight index API unchanged.

### Validation and safety

- The shared mono PCM16 WAV writer now rejects multi-dimensional audio,
  non-finite samples, non-float sample arrays, and invalid sample rates instead
  of silently flattening channels or coercing malformed inputs.
- Standalone voice and generated-audio manifests now require safe POSIX-relative
  artifact paths and reject symlinked references before exposing local files to
  consumers.

## [0.6.1] - 2026-08-16

Additive patch release for lossless, collection-driven story authoring. The
story-index wire contract remains schema version 1.

### Added

- Lossless `StoryIndexDocument`, `StoryIndexRecord`, and
  `StoryIndexCollection` APIs for collection-driven authoring. They preserve
  producer metadata and complete line records while validating common voice,
  context, and source-audio fields without changing story-index wire schema 1.
- Canonical story source-audio policy for queue builders: absent audio is
  generated, unavailable audio preserves source preference, available audio is
  excluded, and unknown audio requires an explicit resolve-or-review action.

## [0.6.0] - 2026-08-16

Immutable `vntts-artifacts` release containing the complete game-pack and
voice-generation-queue contracts.

### Added

- Complete `vntts.game-pack` schema version 1 reader and writer with typed,
  resolved artifact bindings.
- `vntts.voice-generation-queue` schema version 1 constants, typed reader and
  writer, stable queue identity, and source-audio action validation.
- Story-index collection metadata and canonical source-audio fields with legacy
  extractor mappings.
- Synthetic extraction-to-consumption compatibility coverage and a documented
  producer/consumer compatibility matrix.

### Validation and safety

- Game packs validate the story index, voice manifest, all referenced voice
  WAVs, the optional generated-audio manifest, and every generated WAV before
  exposing paths to consumers.
- Game-pack bindings reject missing, modified, absolute, path-traversing,
  duplicate, referenced-but-undeclared, and declared-but-unreferenced files.
- Voice-generation queues validate exact text SHA-256, deterministic queue IDs,
  source-audio status/action pairs, summary counts, and untrusted provenance
  field types while preserving producer extensions.

### Adoption

- The published annotated `v0.6.0` tag resolves to release commit
  `9898f229673b99ed77a718b18fb3247d7f1c5fcf`.
- `reverse1999-extractor` adoption commit `36c3002` pins `v0.6.0` and passed its
  160-test suite.
- VNTTS adoption commit `67e7ef9` pins `v0.6.0` and passed its 589-test suite.
