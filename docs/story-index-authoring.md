# Lossless story-index authoring

Story-index schema version 1 intentionally allows producer metadata and line
extensions. The original `load_story_index` API returns the stable playback
fields as `StoryIndexLine`; it does not expose every producer field. Generic
authoring and queue-building code must use the lossless document API when those
fields affect output.

## Public API

- `StoryIndexDocument.load(path)` and `load_story_index_document(path)` read the
  same strict, lossless representation.
- `StoryIndexError` is the public validation/read error for both APIs.
- `write_story_index_document(path, metadata, records)` validates the complete
  document before atomic publication and returns the published document.
- `StoryIndexDocument.metadata` preserves the complete validated metadata
  record; `producer_metadata` contains fields outside the schema envelope.
- Common producer metadata is also exposed as typed `game`, `language`, and
  `generated_at` attributes. When present, the first two must be non-empty text
  and `generated_at` must be an ISO-8601 timestamp with a timezone.
- `StoryIndexDocument.collections` contains typed `StoryIndexCollection`
  records with lossless `to_record()` and `producer_fields` access.
- `StoryIndexDocument.records` contains `StoryIndexRecord` values. A record is
  also a `StoryIndexLine`, so existing typed-line helpers can accept it.
- `find(line_id)` and `records_for_collection(collection_id,
  speakable_only=True)` support collection-driven queue construction without
  reparsing JSON.

## Validated authoring fields

In addition to the existing line identity, text, collection, and canonical
source-audio fields, `StoryIndexRecord` exposes:

- `voice_character`, falling back to `speaker` when absent;
- `previous_text` and `next_text` as nullable context strings;
- `context` as an optional producer-defined JSON object;
- `source_audio_reason`, with read compatibility for legacy `audio_reason`;
- `source_kind`, defaulting to `story`;
- `speakable`, defaulting to `true`.

The strict reader rejects duplicate line IDs, non-integer sequences, text-hash
drift, undeclared collections, invalid context or boolean types, unsupported
legacy audio statuses, and conflicting canonical/legacy status, ID, or reason
fields. Producer extensions must contain standard JSON values; non-finite
numbers are rejected before publication. `text_sha256` is calculated from the
exact stored UTF-8 text.

Every complete line and collection record is available through `to_record()`.
Fields outside the typed contract remain in `producer_fields`; nested values
are preserved through JSON publication and reload. This includes extractor
provenance such as portraits, source asset IDs, media IDs, story grouping, and
provider-specific annotations. Unknown producer metadata is likewise preserved
but remains producer-owned and is not assigned package-specific semantics.

## Compatibility and release boundary

The wire schema remains `vntts.story-index` version 1. Existing v1 readers can
continue reading documents written by the lossless API because producer fields
remain additive. Existing `load_story_index` behavior and return types are
unchanged.

The Python document/record API itself is newer than immutable release `v0.6.0`.
Consumers that import `StoryIndexDocument`, `StoryIndexRecord`,
`StoryIndexCollection`, `load_story_index_document`, or
`write_story_index_document` require the next immutable `vntts-artifacts`
release even though the wire schema version does not change.
