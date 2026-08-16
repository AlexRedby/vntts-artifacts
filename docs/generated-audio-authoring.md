# Lossless generated-audio authoring

`vntts.generated-audio` remains wire schema version 1. The additive
`GeneratedAudioDocument` and `GeneratedAudioRecord` APIs expose the same core
identity and resolved WAV paths as `GeneratedAudioIndex`, while retaining the
complete metadata object and every entry-level producer extension.

Use the lossless API when authoring, reviewing, republishing, or auditing
generation provenance:

```python
from vntts_artifacts import GeneratedAudioDocument, write_generated_audio_document

document = GeneratedAudioDocument.load(manifest_path)
record = document.find(line_id, text_sha256)
if record is not None:
    provider = record.provider
    model = record.model
    provenance = record.synthesis_provenance_sha256
    producer_extensions = record.producer_fields

copy = write_generated_audio_document(
    output_path,
    document.metadata,
    document.records,
)
```

`GeneratedAudioRecord` is a subtype of the existing `GeneratedAudioEntry`.
`to_record()` returns the complete wire record, and the writer recognizes that
method so typed load -> write round trips do not lose extensions. The document
also exposes `entries` as an alias of `records` and performs the same exact
`(line_id, text_sha256)` lookup with optional current-file checksum checking.

Common authoring provenance is typed when present: `queue_id`, `provider`,
`model`, `prompt_sha256`, `seed`, `review_status`, `generation_profile`,
`prompt_applied`, `queue_annotations_sha256`,
`synthesis_provenance_sha256`, and `voice_character`. Unknown fields remain in
`producer_fields` and in the complete record returned by `to_record()`.

The strict document writer validates known metadata and provenance types,
lowercase SHA-256 values, safe relative audio paths, duplicate identities, JSON
values, symlink containment, referenced-file existence, and exact WAV checksums
before atomic publication. Known top-level metadata includes `game`, `language`, an ISO-8601
`generated_at` with timezone, and `source_queue_sha256`; other metadata is
retained in `producer_metadata`.

Existing APIs remain intentionally unchanged:

- `GeneratedAudioIndex.load` continues to return exact
  `GeneratedAudioEntry` values and provides the lightweight runtime lookup.
- `load_generated_audio_manifest` keeps its `(metadata, entries)` return shape.
- `write_generated_audio_manifest` still returns the published `Path`; it now
  also accepts a lossless `GeneratedAudioRecord` without flattening its internal
  helper fields into the wire record.

Because these are new Python symbols, consumers need the next immutable package
release before importing them. Older consumers remain compatible with wire
schema version 1 and may continue ignoring optional producer extensions.
