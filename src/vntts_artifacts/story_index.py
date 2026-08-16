"""Reader and writer for the versioned VNTTS story-index JSONL contract."""

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path

from vntts_artifacts.atomic_io import atomic_output_path
from vntts_artifacts.hashing import text_sha256

STORY_INDEX_SCHEMA = "vntts.story-index"
STORY_INDEX_SCHEMA_VERSION = 1
SOURCE_AUDIO_STATUSES = frozenset({"absent", "available", "unavailable", "unknown"})

_LEGACY_SOURCE_AUDIO_STATUSES = {
    "configured_unavailable": "unavailable",
    "installed": "available",
    "no_audio": "absent",
    "unchecked": "unknown",
    "unresolved": "unknown",
}


class StoryIndexError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoryIndexLine:
    line_id: str
    chapter: str
    sequence: int
    speaker: str
    text: str
    kind: str
    text_sha256: str
    source_audio_status: str = "unknown"
    source_audio_id: str | None = None
    collection_id: str | None = None


@dataclass(frozen=True)
class StoryIndexCollection:
    collection_id: str
    title: str
    kind: str
    order: int
    producer_fields: dict[str, object] = field(default_factory=dict)
    document: dict[str, object] = field(default_factory=dict, repr=False, compare=False)

    def to_record(self):
        """Return the complete collection record, including producer fields."""
        return dict(self.document)


@dataclass(frozen=True)
class StoryIndexRecord(StoryIndexLine):
    """A validated story line with lossless producer-owned authoring fields."""

    voice_character: str = ""
    previous_text: str | None = None
    next_text: str | None = None
    context: dict[str, object] | None = None
    source_audio_reason: str | None = None
    source_kind: str = "story"
    speakable: bool = True
    producer_fields: dict[str, object] = field(default_factory=dict)
    document: dict[str, object] = field(default_factory=dict, repr=False, compare=False)

    def to_record(self):
        """Return the complete original line record, including producer fields."""
        return dict(self.document)


@dataclass(frozen=True)
class StoryIndexDocument:
    """A strict, lossless story-index document for generic authoring workflows."""

    path: Path
    game: str | None
    language: str | None
    generated_at: str | None
    metadata: dict[str, object]
    producer_metadata: dict[str, object]
    collections: tuple[StoryIndexCollection, ...]
    records: tuple[StoryIndexRecord, ...]

    @classmethod
    def load(cls, path):
        return load_story_index_document(path)

    @property
    def lines(self):
        """Alias allowing records to be consumed anywhere typed lines are accepted."""
        return self.records

    def find(self, line_id):
        """Return one record by stable line ID, or ``None`` when it is absent."""
        if not isinstance(line_id, str):
            return None
        target = line_id.strip()
        return next((record for record in self.records if record.line_id == target), None)

    def records_for_collection(self, collection_id, *, speakable_only=False):
        """Return records in one declared collection, preserving document order."""
        if not isinstance(collection_id, str) or not collection_id.strip():
            raise StoryIndexError("collection_id must be non-empty text")
        target = collection_id.strip()
        if not any(collection.collection_id == target for collection in self.collections):
            raise StoryIndexError(f"Unknown story-index collection_id: {target!r}")
        return tuple(
            record
            for record in self.records
            if record.collection_id == target and (record.speakable or not speakable_only)
        )


_STANDARD_LINE_FIELDS = frozenset(
    {
        "record_type",
        "line_id",
        "chapter",
        "sequence",
        "speaker",
        "text",
        "kind",
        "text_sha256",
        "source_audio_status",
        "audio_status",
        "source_audio_id",
        "source_voice_id",
        "collection_id",
        "voice_character",
        "previous_text",
        "next_text",
        "context",
        "source_audio_reason",
        "audio_reason",
        "source_kind",
        "speakable",
    }
)
_STANDARD_METADATA_FIELDS = frozenset(
    {"record_type", "schema", "schema_version", "line_count", "collections"}
)
_STANDARD_COLLECTION_FIELDS = frozenset({"collection_id", "title", "kind", "order"})


def load_story_index(path):
    path = Path(path).expanduser().resolve()
    try:
        stream = path.open(encoding="utf-8")
    except OSError as error:
        raise StoryIndexError(f"Unable to open story index {path}: {error}") from error

    with stream:
        try:
            metadata = json.loads(next(stream))
        except StopIteration as error:
            raise StoryIndexError(f"Story index is empty: {path}") from error
        except json.JSONDecodeError as error:
            raise StoryIndexError(f"Invalid story-index metadata in {path}: {error}") from error
        collection_ids = _validate_metadata(metadata)

        lines = []
        for row_number, row in enumerate(stream, start=2):
            try:
                record = json.loads(row)
                if not isinstance(record, dict) or record.get("record_type") != "line":
                    raise ValueError("expected a line record")
                line_id = _required_text(record, "line_id")
                chapter = _required_text(record, "chapter")
                speaker = _required_text(record, "speaker")
                text = _required_text(record, "text")
                sequence = int(record["sequence"])
                kind = str(record.get("kind") or "dialogue").strip()
                calculated_text_hash = text_sha256(text)
                declared_text_hash = str(record.get("text_sha256") or "").strip()
                if declared_text_hash and declared_text_hash != calculated_text_hash:
                    raise ValueError(f"text_sha256 does not match line {line_id!r}")
                source_audio_status = _source_audio_status(record)
                source_audio_id = _optional_text(
                    record.get("source_audio_id", record.get("source_voice_id"))
                )
                collection_id = _optional_text(record.get("collection_id"), "collection_id")
                if collection_id is not None and (
                    collection_ids is None or collection_id not in collection_ids
                ):
                    raise ValueError(
                        f"collection_id {collection_id!r} is not declared in metadata collections"
                    )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise StoryIndexError(
                    f"Invalid story-index record at {path}:{row_number}: {error}"
                ) from error
            lines.append(
                StoryIndexLine(
                    line_id,
                    chapter,
                    sequence,
                    speaker,
                    text,
                    kind,
                    calculated_text_hash,
                    source_audio_status,
                    source_audio_id,
                    collection_id,
                )
            )

    declared_count = metadata.get("line_count")
    if isinstance(declared_count, int) and declared_count != len(lines):
        raise StoryIndexError(
            f"Story-index line count mismatch: metadata says {declared_count}, read {len(lines)}"
        )
    return metadata, tuple(lines)


def load_story_index_document(path):
    """Load a strict lossless document while retaining the legacy line API."""
    path = Path(path).expanduser().resolve()
    try:
        stream = path.open(encoding="utf-8")
    except OSError as error:
        raise StoryIndexError(f"Unable to open story index {path}: {error}") from error
    with stream:
        try:
            metadata = _load_strict_json(next(stream))
        except StopIteration as error:
            raise StoryIndexError(f"Story index is empty: {path}") from error
        except (json.JSONDecodeError, ValueError) as error:
            raise StoryIndexError(f"Invalid story-index metadata in {path}: {error}") from error
        records = []
        for row_number, row in enumerate(stream, start=2):
            try:
                records.append(_load_strict_json(row))
            except (json.JSONDecodeError, ValueError) as error:
                raise StoryIndexError(
                    f"Invalid story-index record at {path}:{row_number}: {error}"
                ) from error
    return _parse_story_index_document(path, metadata, records)


def write_story_index_document(path, metadata, records):
    """Strictly validate and atomically publish a lossless story-index document."""
    path = Path(path).expanduser().resolve()
    if not isinstance(metadata, dict):
        raise StoryIndexError("Story-index metadata must be an object")
    raw_records = tuple(_record_mapping(record) for record in records)
    document_metadata = dict(metadata)
    document_metadata.setdefault("record_type", "metadata")
    document_metadata.setdefault("schema", STORY_INDEX_SCHEMA)
    document_metadata.setdefault("schema_version", STORY_INDEX_SCHEMA_VERSION)
    document_metadata["line_count"] = len(raw_records)
    _parse_story_index_document(path, document_metadata, raw_records)
    metadata_json = _dump_strict_json(document_metadata, "metadata")
    record_json = tuple(
        _dump_strict_json(record, f"record {index}")
        for index, record in enumerate(raw_records, start=2)
    )
    with atomic_output_path(path) as temporary:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(metadata_json + "\n")
            for record in record_json:
                stream.write(record + "\n")
    return load_story_index_document(path)


def write_story_index(path, metadata, records):
    """Publish producer records while enforcing the shared metadata envelope."""
    path = Path(path).expanduser().resolve()
    records = tuple(_record_mapping(record) for record in records)
    document_metadata = dict(metadata)
    document_metadata.setdefault("record_type", "metadata")
    document_metadata.setdefault("schema", STORY_INDEX_SCHEMA)
    document_metadata.setdefault("schema_version", STORY_INDEX_SCHEMA_VERSION)
    document_metadata["line_count"] = len(records)
    collection_ids = _validate_metadata(document_metadata)
    for record in records:
        if record.get("record_type") != "line":
            raise StoryIndexError("Story-index records must have record_type='line'")
        try:
            collection_id = _optional_text(record.get("collection_id"), "collection_id")
        except ValueError as error:
            raise StoryIndexError(f"Invalid story-index collection_id: {error}") from error
        if collection_id is not None and (
            collection_ids is None or collection_id not in collection_ids
        ):
            raise StoryIndexError(
                f"collection_id {collection_id!r} is not declared in metadata collections"
            )

    with atomic_output_path(path) as temporary:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(document_metadata, ensure_ascii=False, sort_keys=True) + "\n")
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _validate_metadata(metadata):
    if not isinstance(metadata, dict):
        raise StoryIndexError("Story-index metadata must be an object")
    if metadata.get("record_type") != "metadata":
        raise StoryIndexError("Story index must begin with a metadata record")
    if metadata.get("schema") != STORY_INDEX_SCHEMA:
        raise StoryIndexError(f"Unsupported story-index schema: {metadata.get('schema')!r}")
    if metadata.get("schema_version") != STORY_INDEX_SCHEMA_VERSION:
        raise StoryIndexError(
            f"Unsupported story-index schema version: {metadata.get('schema_version')!r}"
        )
    return _validate_collections(metadata.get("collections"))


def _record_mapping(record):
    if isinstance(record, StoryIndexRecord):
        return record.to_record()
    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    if isinstance(record, dict):
        return dict(record)
    raise StoryIndexError("Story-index records must be mappings or dataclass instances")


def _parse_story_index_document(path, metadata, records):
    collection_ids = _validate_metadata(metadata)
    game = _optional_metadata_text(metadata, "game")
    language = _optional_metadata_text(metadata, "language")
    generated_at = _optional_metadata_timestamp(metadata, "generated_at")
    declared_count = metadata.get("line_count")
    if isinstance(declared_count, bool) or not isinstance(declared_count, int):
        raise StoryIndexError("Story-index metadata requires an integer line_count")
    if declared_count != len(records):
        raise StoryIndexError(
            f"Story-index line count mismatch: metadata says {declared_count}, read {len(records)}"
        )
    collections = tuple(
        _parse_collection(record, index)
        for index, record in enumerate(metadata.get("collections") or ())
    )
    parsed_records = []
    line_ids = set()
    for index, record in enumerate(records, start=2):
        try:
            parsed = _parse_story_index_record(record, collection_ids)
        except (KeyError, TypeError, ValueError) as error:
            raise StoryIndexError(
                f"Invalid story-index record at {path}:{index}: {error}"
            ) from error
        if parsed.line_id in line_ids:
            raise StoryIndexError(f"Duplicate story-index line_id: {parsed.line_id!r}")
        line_ids.add(parsed.line_id)
        parsed_records.append(parsed)
    return StoryIndexDocument(
        path=Path(path),
        game=game,
        language=language,
        generated_at=generated_at,
        metadata=dict(metadata),
        producer_metadata={
            key: value for key, value in metadata.items() if key not in _STANDARD_METADATA_FIELDS
        },
        collections=collections,
        records=tuple(parsed_records),
    )


def _load_strict_json(value):
    return json.loads(value, parse_constant=_reject_json_constant)


def _reject_json_constant(value):
    raise ValueError(f"non-standard JSON constant {value!r}")


def _dump_strict_json(value, label):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise StoryIndexError(
            f"Story-index {label} must contain valid JSON values: {error}"
        ) from error


def _parse_collection(record, index):
    if not isinstance(record, dict):
        raise StoryIndexError(f"Story-index collection {index} must be an object")
    collection_id = _canonical_text(record.get("collection_id"), "collection_id")
    title = _canonical_text(record.get("title"), "title")
    kind = _canonical_text(record.get("kind"), "kind")
    order = record.get("order")
    if isinstance(order, bool) or not isinstance(order, int):
        raise StoryIndexError(f"Story-index collection {index} order must be an integer")
    return StoryIndexCollection(
        collection_id=collection_id,
        title=title,
        kind=kind,
        order=order,
        producer_fields={
            key: value for key, value in record.items() if key not in _STANDARD_COLLECTION_FIELDS
        },
        document=dict(record),
    )


def _parse_story_index_record(record, collection_ids):
    if not isinstance(record, dict) or record.get("record_type") != "line":
        raise ValueError("expected a line record")
    line_id = _canonical_text(record.get("line_id"), "line_id")
    chapter = _canonical_text(record.get("chapter"), "chapter")
    speaker = _canonical_text(record.get("speaker"), "speaker")
    text = _exact_text(record.get("text"), "text")
    sequence = record.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise ValueError("sequence must be an integer")
    kind = _canonical_text(record.get("kind", "dialogue"), "kind")
    calculated_text_hash = text_sha256(text)
    declared_text_hash = record.get("text_sha256")
    if declared_text_hash is not None:
        declared_text_hash = _canonical_text(declared_text_hash, "text_sha256")
        if declared_text_hash != calculated_text_hash:
            raise ValueError(f"text_sha256 does not match line {line_id!r}")
    source_audio_status = _strict_source_audio_status(record)
    source_audio_id = _coalesced_optional_text(record, "source_audio_id", "source_voice_id")
    collection_id = _optional_canonical_text(record.get("collection_id"), "collection_id")
    if collection_id is not None and (
        collection_ids is None or collection_id not in collection_ids
    ):
        raise ValueError(f"collection_id {collection_id!r} is not declared in metadata collections")
    voice_character = (
        _optional_canonical_text(record.get("voice_character"), "voice_character") or speaker
    )
    previous_text = _nullable_text(record.get("previous_text"), "previous_text")
    next_text = _nullable_text(record.get("next_text"), "next_text")
    context = record.get("context")
    if context is not None and not isinstance(context, dict):
        raise ValueError("context must be an object or null")
    source_audio_reason = _coalesced_optional_text(record, "source_audio_reason", "audio_reason")
    source_kind = _optional_canonical_text(record.get("source_kind"), "source_kind") or "story"
    speakable = record.get("speakable", True)
    if not isinstance(speakable, bool):
        raise ValueError("speakable must be a boolean")
    return StoryIndexRecord(
        line_id=line_id,
        chapter=chapter,
        sequence=sequence,
        speaker=speaker,
        text=text,
        kind=kind,
        text_sha256=calculated_text_hash,
        source_audio_status=source_audio_status,
        source_audio_id=source_audio_id,
        collection_id=collection_id,
        voice_character=voice_character,
        previous_text=previous_text,
        next_text=next_text,
        context=None if context is None else dict(context),
        source_audio_reason=source_audio_reason,
        source_kind=source_kind,
        speakable=speakable,
        producer_fields={
            key: value for key, value in record.items() if key not in _STANDARD_LINE_FIELDS
        },
        document=dict(record),
    )


def _strict_source_audio_status(record):
    canonical = record.get("source_audio_status")
    legacy = record.get("audio_status")
    if canonical is not None:
        canonical = _canonical_text(canonical, "source_audio_status")
        if canonical not in SOURCE_AUDIO_STATUSES:
            raise ValueError(
                "source_audio_status must be one of " + ", ".join(sorted(SOURCE_AUDIO_STATUSES))
            )
    if legacy is not None:
        legacy = _canonical_text(legacy, "audio_status")
        mapped = _LEGACY_SOURCE_AUDIO_STATUSES.get(legacy)
        if mapped is None:
            raise ValueError(f"unsupported legacy audio_status {legacy!r}")
        if canonical is not None and canonical != mapped:
            raise ValueError("source_audio_status conflicts with legacy audio_status")
        return mapped
    return canonical or "unknown"


def _coalesced_optional_text(record, canonical_field, legacy_field):
    canonical = _optional_canonical_text(record.get(canonical_field), canonical_field)
    legacy = _optional_canonical_text(record.get(legacy_field), legacy_field)
    if canonical is not None and legacy is not None and canonical != legacy:
        raise ValueError(f"{canonical_field} conflicts with legacy {legacy_field}")
    return canonical if canonical is not None else legacy


def _canonical_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    if value != value.strip():
        raise ValueError(f"{field} must not have surrounding whitespace")
    return value


def _optional_canonical_text(value, field):
    if value is None:
        return None
    return _canonical_text(value, field)


def _exact_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _nullable_text(value, field):
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{field} must be text or null")
    return value


def _optional_metadata_text(metadata, field):
    if field not in metadata:
        return None
    try:
        return _canonical_text(metadata[field], f"metadata {field}")
    except ValueError as error:
        raise StoryIndexError(str(error)) from error


def _optional_metadata_timestamp(metadata, field):
    value = _optional_metadata_text(metadata, field)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise StoryIndexError(f"metadata {field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StoryIndexError(f"metadata {field} must include a timezone offset")
    return value


def _required_text(record, name):
    value = record[name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()


def _optional_text(value, field="source_audio_id"):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text when present")
    return value.strip() or None


def _validate_collections(collections):
    if collections is None:
        return None
    if not isinstance(collections, list) or not collections:
        raise StoryIndexError("Story-index collections must be a non-empty list")
    collection_ids = set()
    for index, collection in enumerate(collections):
        if not isinstance(collection, dict):
            raise StoryIndexError(f"Story-index collection {index} must be an object")
        value = collection.get("collection_id")
        if not isinstance(value, str) or not value.strip():
            raise StoryIndexError(
                f"Story-index collection {index} requires a non-empty collection_id"
            )
        for field_name in ("title", "kind"):
            field_value = collection.get(field_name)
            if not isinstance(field_value, str) or not field_value.strip():
                raise StoryIndexError(
                    f"Story-index collection {index} requires a non-empty {field_name}"
                )
        order = collection.get("order")
        if isinstance(order, bool) or not isinstance(order, int):
            raise StoryIndexError(f"Story-index collection {index} order must be an integer")
        collection_id = value.strip()
        if collection_id in collection_ids:
            raise StoryIndexError(f"Duplicate story-index collection_id: {collection_id!r}")
        collection_ids.add(collection_id)
    return frozenset(collection_ids)


def _source_audio_status(record):
    value = record.get("source_audio_status")
    if value is None:
        legacy = str(record.get("audio_status") or "").strip()
        return _LEGACY_SOURCE_AUDIO_STATUSES.get(legacy, "unknown")
    if not isinstance(value, str) or value.strip() not in SOURCE_AUDIO_STATUSES:
        raise ValueError(
            "source_audio_status must be one of " + ", ".join(sorted(SOURCE_AUDIO_STATUSES))
        )
    return value.strip()
