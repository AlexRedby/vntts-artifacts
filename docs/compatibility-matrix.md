# Contract compatibility matrix

This matrix describes wire-format support in immutable `vntts-artifacts`
releases and in the current unreleased repository state. “Producer” means the
package can publish a validated artifact; “consumer” means it can parse and
validate that artifact through a public API.

| Contract | Current wire version | First producer support | First consumer support | Current public APIs |
| --- | ---: | --- | --- | --- |
| Story index (`vntts.story-index`) | 1 | `v0.1.0` | `v0.1.0` | `write_story_index`, `load_story_index` |
| Voice manifest | 2 | `v0.1.0` | `v0.1.0` | `write_voice_manifest`, `load_voice_manifest` |
| Generated audio (`vntts.generated-audio`) | 1 | `v0.2.0` | `v0.2.0` | `write_generated_audio_manifest`, `GeneratedAudioIndex.load` |
| Game pack (`vntts.game-pack`) | 1 | Unreleased, after `f52535c` | Unreleased, after `f52535c` | `write_game_pack`, `load_game_pack` |
| Voice-generation queue (`vntts.voice-generation-queue`) | 1 | Unreleased, after `9ce1d50` | Unreleased, after `9ce1d50` | `write_voice_generation_queue`, `load_voice_generation_queue` |

## Release boundaries

- `v0.5.0` contains deterministic game-pack checksum-binding helpers, but not
  the complete `vntts.game-pack` document reader or writer. It must not be
  treated as game-pack schema version 1 support.
- The complete game-pack and voice-generation-queue rows remain unreleased.
  Applications must not claim immutable package support for them until the
  release-and-pinning TODO is completed.
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
- A game-pack consumer trusts only resolved paths returned by `load_game_pack`
  after the complete checksum and nested-reference validation succeeds.

The synthetic compatibility flow in
[`authoring-exchange.md`](authoring-exchange.md) verifies the current contracts
together. It does not replace the immutable release and application pinning
required for cross-project adoption.
