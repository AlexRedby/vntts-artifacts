"""Versioned manifest and exact lookup for ahead-of-time generated audio."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from vntts_artifacts.atomic_io import atomic_write_json
from vntts_artifacts.audio import PCM16_MONO_WAV_FORMAT
from vntts_artifacts.file_integrity import sha256_file
from vntts_artifacts.hashing import text_sha256 as _text_sha256

GENERATED_AUDIO_SCHEMA = "vntts.generated-audio"
GENERATED_AUDIO_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class GeneratedAudioManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedAudioEntry:
    line_id: str
    text_sha256: str
    audio: Path
    audio_format: str
    audio_sha256: str
    sample_rate: int
    sample_count: int


@dataclass(frozen=True)
class GeneratedAudioRecord(GeneratedAudioEntry):
    """A validated generated-audio entry with lossless producer provenance."""

    queue_id: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_sha256: str | None = None
    seed: int | None = None
    review_status: str | None = None
    generation_profile: str | None = None
    prompt_applied: bool | None = None
    queue_annotations_sha256: str | None = None
    synthesis_provenance_sha256: str | None = None
    voice_character: str | None = None
    producer_fields: dict[str, object] = field(default_factory=dict)
    document: dict[str, object] = field(default_factory=dict, repr=False, compare=False)

    def to_record(self):
        """Return the complete wire record, including producer extensions."""
        return dict(self.document)


@dataclass(frozen=True)
class GeneratedAudioDocument:
    """A strict, lossless generated-audio document for authoring consumers."""

    path: Path
    game: str | None
    language: str | None
    generated_at: str | None
    source_queue_sha256: str | None
    metadata: dict[str, object]
    producer_metadata: dict[str, object]
    records: tuple[GeneratedAudioRecord, ...]

    @classmethod
    def load(cls, path):
        return load_generated_audio_document(path)

    @property
    def entries(self):
        """Alias matching the legacy index terminology."""
        return self.records

    def find(self, line_id, text_hash, *, verify_file=True):
        """Return one exact record, or ``None`` when identity or bytes differ."""
        if not isinstance(line_id, str) or not isinstance(text_hash, str):
            return None
        identity = line_id.strip(), text_hash.strip()
        record = next(
            (
                candidate
                for candidate in self.records
                if (candidate.line_id, candidate.text_sha256) == identity
            ),
            None,
        )
        if record is None or not verify_file:
            return record
        try:
            if not record.audio.is_file() or sha256_file(record.audio) != record.audio_sha256:
                return None
        except OSError:
            return None
        return record


class GeneratedAudioIndex:
    """Validated generated files addressable only by line ID and text hash."""

    def __init__(self, manifest_path, metadata, entries):
        self.manifest_path = Path(manifest_path).expanduser().resolve()
        self.metadata = dict(metadata)
        self.entries = tuple(entries)
        self._entries_by_identity = {
            (entry.line_id, entry.text_sha256): entry for entry in self.entries
        }

    @classmethod
    def load(cls, path):
        path = Path(path).expanduser().resolve()
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise GeneratedAudioManifestError(
                f"Unable to read generated-audio manifest {path}: {error}"
            ) from error
        metadata, entries = _validate_document(document, path)
        return cls(path, metadata, entries)

    def find(self, line_id, text_hash, *, verify_file=True):
        """Return one exact, current, intact generation or ``None``."""
        if not isinstance(line_id, str) or not isinstance(text_hash, str):
            return None
        entry = self._entries_by_identity.get((line_id.strip(), text_hash.strip()))
        if entry is None or not verify_file:
            return entry
        try:
            if not entry.audio.is_file():
                return None
            if sha256_file(entry.audio) != entry.audio_sha256:
                return None
        except OSError:
            return None
        return entry


def text_sha256(text):
    """Backward-compatible import path for the shared artifact text hash."""
    return _text_sha256(text)


def load_generated_audio_manifest(path):
    index = GeneratedAudioIndex.load(path)
    return index.metadata, index.entries


def load_generated_audio_document(path):
    """Load schema v1 without discarding metadata or per-entry extensions."""
    path = Path(path).expanduser().resolve()
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise GeneratedAudioManifestError(
            f"Unable to read generated-audio manifest {path}: {error}"
        ) from error
    return _parse_generated_audio_document(path, document)


def write_generated_audio_manifest(path, metadata, records):
    """Atomically publish a manifest after validating every referenced file."""
    path = Path(path).expanduser().resolve()
    entries = [_record_mapping(record) for record in records]
    document = dict(metadata)
    document.setdefault("schema", GENERATED_AUDIO_SCHEMA)
    document.setdefault("schema_version", GENERATED_AUDIO_SCHEMA_VERSION)
    document["entry_count"] = len(entries)
    document["entries"] = entries
    _metadata, parsed_entries = _validate_document(document, path)
    _verify_entries(parsed_entries)
    return atomic_write_json(path, document)


def write_generated_audio_document(path, metadata, records):
    """Strictly validate and atomically publish a lossless schema-v1 document."""
    path = Path(path).expanduser().resolve()
    if not isinstance(metadata, dict):
        raise GeneratedAudioManifestError("Generated-audio metadata must be an object")
    raw_records = tuple(_record_mapping(record) for record in records)
    document = dict(metadata)
    document.setdefault("schema", GENERATED_AUDIO_SCHEMA)
    document.setdefault("schema_version", GENERATED_AUDIO_SCHEMA_VERSION)
    document["entry_count"] = len(raw_records)
    document["entries"] = list(raw_records)
    _dump_strict_json(document, "document")
    parsed = _parse_generated_audio_document(path, document)
    _verify_entries(parsed.records)
    atomic_write_json(path, document)
    return load_generated_audio_document(path)


_STANDARD_ENTRY_FIELDS = frozenset(
    {
        "line_id",
        "text_sha256",
        "audio",
        "audio_format",
        "audio_sha256",
        "sample_rate",
        "sample_count",
        "queue_id",
        "provider",
        "model",
        "prompt_sha256",
        "seed",
        "review_status",
        "generation_profile",
        "prompt_applied",
        "queue_annotations_sha256",
        "synthesis_provenance_sha256",
        "voice_character",
    }
)
_STANDARD_METADATA_FIELDS = frozenset(
    {
        "schema",
        "schema_version",
        "entry_count",
        "entries",
        "game",
        "language",
        "generated_at",
        "source_queue_sha256",
    }
)


def _validate_document(document, manifest_path):
    if not isinstance(document, dict):
        raise GeneratedAudioManifestError("Generated-audio manifest must be an object")
    if document.get("schema") != GENERATED_AUDIO_SCHEMA:
        raise GeneratedAudioManifestError(
            f"Unsupported generated-audio schema: {document.get('schema')!r}"
        )
    if document.get("schema_version") != GENERATED_AUDIO_SCHEMA_VERSION:
        raise GeneratedAudioManifestError(
            f"Unsupported generated-audio schema version: {document.get('schema_version')!r}"
        )
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list):
        raise GeneratedAudioManifestError("Generated-audio manifest must contain an entries list")
    declared_count = document.get("entry_count")
    if not isinstance(declared_count, int) or isinstance(declared_count, bool):
        raise GeneratedAudioManifestError(
            "Generated-audio manifest requires an integer entry_count"
        )
    if declared_count != len(raw_entries):
        raise GeneratedAudioManifestError(
            "Generated-audio entry count mismatch: "
            f"metadata says {declared_count}, read {len(raw_entries)}"
        )

    entries = []
    identities = set()
    for index, record in enumerate(raw_entries):
        if not isinstance(record, dict):
            raise GeneratedAudioManifestError(f"Generated-audio entry {index} must be an object")
        line_id = _required_text(record, "line_id", index)
        text_hash = _required_hash(record, "text_sha256", index)
        audio_hash = _required_hash(record, "audio_sha256", index)
        audio = _audio_path(manifest_path, record.get("audio"), index)
        audio_format = _required_text(record, "audio_format", index)
        if audio_format != PCM16_MONO_WAV_FORMAT:
            raise GeneratedAudioManifestError(
                f"Generated-audio entry {index} has unsupported audio_format {audio_format!r}"
            )
        sample_rate = _positive_integer(record, "sample_rate", index)
        sample_count = _positive_integer(record, "sample_count", index)
        identity = line_id, text_hash
        if identity in identities:
            raise GeneratedAudioManifestError(
                f"Duplicate generated-audio identity for line {line_id!r}"
            )
        identities.add(identity)
        entries.append(
            GeneratedAudioEntry(
                line_id=line_id,
                text_sha256=text_hash,
                audio=audio,
                audio_format=audio_format,
                audio_sha256=audio_hash,
                sample_rate=sample_rate,
                sample_count=sample_count,
            )
        )
    metadata = {key: value for key, value in document.items() if key != "entries"}
    return metadata, tuple(entries)


def _parse_generated_audio_document(path, document):
    metadata, entries = _validate_document(document, path)
    manifest_root = Path(path).parent.resolve()
    for index, entry in enumerate(entries, start=1):
        try:
            entry.audio.relative_to(manifest_root)
        except ValueError as error:
            raise GeneratedAudioManifestError(
                f"Generated-audio entry {index} audio must stay within the manifest directory"
            ) from error
    game = _optional_metadata_text(document, "game")
    language = _optional_metadata_text(document, "language")
    generated_at = _optional_metadata_timestamp(document, "generated_at")
    source_queue_sha256 = _optional_metadata_hash(document, "source_queue_sha256")
    records = tuple(
        _parse_generated_audio_record(entry, raw, index)
        for index, (entry, raw) in enumerate(
            zip(entries, document["entries"], strict=True), start=1
        )
    )
    return GeneratedAudioDocument(
        path=Path(path),
        game=game,
        language=language,
        generated_at=generated_at,
        source_queue_sha256=source_queue_sha256,
        metadata=dict(metadata),
        producer_metadata={
            key: value for key, value in document.items() if key not in _STANDARD_METADATA_FIELDS
        },
        records=records,
    )


def _parse_generated_audio_record(entry, record, index):
    queue_id = _optional_record_text(record, "queue_id", index)
    provider = _optional_record_text(record, "provider", index)
    model = _optional_record_text(record, "model", index)
    prompt_sha256 = _optional_record_hash(record, "prompt_sha256", index)
    seed = _optional_integer(record, "seed", index)
    review_status = _optional_record_text(record, "review_status", index)
    generation_profile = _optional_record_text(record, "generation_profile", index)
    prompt_applied = _optional_boolean(record, "prompt_applied", index)
    queue_annotations_sha256 = _optional_record_hash(
        record, "queue_annotations_sha256", index
    )
    synthesis_provenance_sha256 = _optional_record_hash(
        record, "synthesis_provenance_sha256", index
    )
    voice_character = _optional_record_text(record, "voice_character", index)
    return GeneratedAudioRecord(
        line_id=entry.line_id,
        text_sha256=entry.text_sha256,
        audio=entry.audio,
        audio_format=entry.audio_format,
        audio_sha256=entry.audio_sha256,
        sample_rate=entry.sample_rate,
        sample_count=entry.sample_count,
        queue_id=queue_id,
        provider=provider,
        model=model,
        prompt_sha256=prompt_sha256,
        seed=seed,
        review_status=review_status,
        generation_profile=generation_profile,
        prompt_applied=prompt_applied,
        queue_annotations_sha256=queue_annotations_sha256,
        synthesis_provenance_sha256=synthesis_provenance_sha256,
        voice_character=voice_character,
        producer_fields={
            key: value for key, value in record.items() if key not in _STANDARD_ENTRY_FIELDS
        },
        document=dict(record),
    )


def _verify_entries(entries):
    for entry in entries:
        if not entry.audio.is_file():
            raise GeneratedAudioManifestError(f"Generated audio does not exist: {entry.audio}")
        try:
            digest = sha256_file(entry.audio)
        except OSError as error:
            raise GeneratedAudioManifestError(
                f"Unable to read generated audio {entry.audio}: {error}"
            ) from error
        if digest != entry.audio_sha256:
            raise GeneratedAudioManifestError(
                f"Generated audio hash does not match: {entry.audio}"
            )


def _audio_path(manifest_path, value, index):
    if not isinstance(value, str) or not value.strip():
        raise GeneratedAudioManifestError(f"Generated-audio entry {index} requires audio")
    value = value.strip()
    if "\\" in value:
        raise GeneratedAudioManifestError(
            f"Generated-audio entry {index} audio must use POSIX separators"
        )
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise GeneratedAudioManifestError(
            f"Generated-audio entry {index} audio must be a safe relative path"
        )
    return (Path(manifest_path).parent / Path(*relative.parts)).resolve()


def _required_text(record, field, index):
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise GeneratedAudioManifestError(f"Generated-audio entry {index} requires {field}")
    return value.strip()


def _required_hash(record, field, index):
    value = _required_text(record, field, index)
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise GeneratedAudioManifestError(
            f"Generated-audio entry {index} {field} must be lowercase SHA-256"
        )
    return value


def _positive_integer(record, field, index):
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GeneratedAudioManifestError(
            f"Generated-audio entry {index} {field} must be a positive integer"
        )
    return value


def _optional_metadata_text(metadata, field):
    if field not in metadata:
        return None
    value = metadata[field]
    if not isinstance(value, str) or not value.strip():
        raise GeneratedAudioManifestError(
            f"Generated-audio metadata {field} must be non-empty text"
        )
    return value.strip()


def _optional_metadata_timestamp(metadata, field):
    value = _optional_metadata_text(metadata, field)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GeneratedAudioManifestError(
            f"Generated-audio metadata {field} must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GeneratedAudioManifestError(
            f"Generated-audio metadata {field} must include a timezone offset"
        )
    return value


def _optional_metadata_hash(metadata, field):
    if field not in metadata:
        return None
    return _validate_optional_hash(metadata[field], f"metadata {field}")


def _optional_record_text(record, field, index):
    if field not in record:
        return None
    value = record[field]
    if not isinstance(value, str) or not value.strip():
        raise GeneratedAudioManifestError(
            f"Generated-audio entry {index} {field} must be non-empty text"
        )
    return value.strip()


def _optional_record_hash(record, field, index):
    if field not in record:
        return None
    return _validate_optional_hash(record[field], f"entry {index} {field}")


def _validate_optional_hash(value, label):
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value.strip()) is None:
        raise GeneratedAudioManifestError(
            f"Generated-audio {label} must be lowercase SHA-256"
        )
    return value.strip()


def _optional_integer(record, field, index):
    if field not in record:
        return None
    value = record[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise GeneratedAudioManifestError(
            f"Generated-audio entry {index} {field} must be an integer"
        )
    return value


def _optional_boolean(record, field, index):
    if field not in record:
        return None
    value = record[field]
    if not isinstance(value, bool):
        raise GeneratedAudioManifestError(
            f"Generated-audio entry {index} {field} must be a boolean"
        )
    return value


def _reject_json_constant(value):
    raise ValueError(f"non-standard JSON constant {value!r}")


def _dump_strict_json(value, label):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise GeneratedAudioManifestError(
            f"Generated-audio {label} must contain valid JSON values: {error}"
        ) from error


def _record_mapping(record):
    if isinstance(record, GeneratedAudioRecord):
        return record.to_record()
    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    if isinstance(record, dict):
        return dict(record)
    raise GeneratedAudioManifestError(
        "Generated-audio entries must be mappings or dataclass instances"
    )
