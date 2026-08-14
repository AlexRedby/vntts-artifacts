"""Versioned manifest and exact lookup for ahead-of-time generated audio."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path, PurePosixPath

from vntts_artifacts.atomic_io import atomic_write_json
from vntts_artifacts.file_integrity import sha256_file

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

    def find(self, line_id, text_sha256, *, verify_file=True):
        """Return one exact, current, intact generation or ``None``."""
        if not isinstance(line_id, str) or not isinstance(text_sha256, str):
            return None
        entry = self._entries_by_identity.get((line_id.strip(), text_sha256.strip()))
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
    if not isinstance(text, str):
        raise TypeError("Generated-audio text must be a string")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_generated_audio_manifest(path):
    index = GeneratedAudioIndex.load(path)
    return index.metadata, index.entries


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
    for entry in parsed_entries:
        if not entry.audio.is_file():
            raise GeneratedAudioManifestError(f"Generated audio does not exist: {entry.audio}")
        try:
            digest = sha256_file(entry.audio)
        except OSError as error:
            raise GeneratedAudioManifestError(
                f"Unable to read generated audio {entry.audio}: {error}"
            ) from error
        if digest != entry.audio_sha256:
            raise GeneratedAudioManifestError(f"Generated audio hash does not match: {entry.audio}")
    return atomic_write_json(path, document)


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
        if audio_format != "wav-pcm16-mono":
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


def _record_mapping(record):
    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    if isinstance(record, dict):
        return dict(record)
    raise GeneratedAudioManifestError(
        "Generated-audio entries must be mappings or dataclass instances"
    )
