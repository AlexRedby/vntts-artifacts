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

## Building a generation queue

Queue builders can derive policy without reading producer-owned legacy fields:

```python
from vntts_artifacts import voice_generation_action

for record in document.records_for_collection("main-story", speakable_only=True):
    action = voice_generation_action(
        record.source_audio_status,
        unknown_action="resolve_audio",
    )
    if action is None:
        continue  # Canonical `available` source audio is not queued.
    item = {
        "record_type": "generation_item",
        "queue_id": f"{record.line_id}:{record.text_sha256[:16]}",
        "line_id": record.line_id,
        "text_sha256": record.text_sha256,
        "text": record.text,
        "speaker": record.speaker,
        "voice_character": record.voice_character,
        "source_audio_status": record.source_audio_status,
        "source_audio_reason": record.source_audio_reason or "not_reported",
        "action": action,
    }
```

Canonical `unknown` intentionally has no implicit action: schema-v1 legacy
`unchecked` and `unresolved` both normalize to `unknown`, but require different
actions. A producer must choose `resolve_audio` or `manual_review`; the queue
stores and validates that choice. Legacy queue statuses and actions remain
accepted unchanged.

## Compatibility and release boundary

The wire schema remains `vntts.story-index` version 1. Existing v1 readers can
continue reading documents written by the lossless API because producer fields
remain additive. Existing `load_story_index` behavior and return types are
unchanged.

The Python document/record API first ships in immutable release `v0.6.1`.
Consumers that import `StoryIndexDocument`, `StoryIndexRecord`,
`StoryIndexCollection`, `load_story_index_document`, or
`write_story_index_document` require `vntts-artifacts` `v0.6.1` or newer even
though the wire schema version does not change.
