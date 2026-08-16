# Changelog

## [0.6.0] - Unreleased

Release candidate for the next immutable `vntts-artifacts` release. The package
metadata is prepared, but no `v0.6.0` tag or published release exists yet.

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

### Adoption status

- This release candidate is not an immutable release. VNTTS and
  `reverse1999-extractor` must remain on their existing pins until `v0.6.0` is
  tagged and published, after which both applications can be pinned to that
  same release.
