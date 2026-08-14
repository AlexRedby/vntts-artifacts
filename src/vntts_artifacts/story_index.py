"""Reader and writer for the versioned VNTTS story-index JSONL contract."""

import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path

from vntts_artifacts.atomic_io import atomic_output_path
from vntts_artifacts.hashing import text_sha256

STORY_INDEX_SCHEMA = "vntts.story-index"
STORY_INDEX_SCHEMA_VERSION = 1


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
        _validate_metadata(metadata)

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
                )
            )

    declared_count = metadata.get("line_count")
    if isinstance(declared_count, int) and declared_count != len(lines):
        raise StoryIndexError(
            f"Story-index line count mismatch: metadata says {declared_count}, read {len(lines)}"
        )
    return metadata, tuple(lines)


def write_story_index(path, metadata, records):
    """Publish producer records while enforcing the shared metadata envelope."""
    path = Path(path).expanduser().resolve()
    records = tuple(_record_mapping(record) for record in records)
    document_metadata = dict(metadata)
    document_metadata.setdefault("record_type", "metadata")
    document_metadata.setdefault("schema", STORY_INDEX_SCHEMA)
    document_metadata.setdefault("schema_version", STORY_INDEX_SCHEMA_VERSION)
    document_metadata["line_count"] = len(records)
    _validate_metadata(document_metadata)
    for record in records:
        if record.get("record_type") != "line":
            raise StoryIndexError("Story-index records must have record_type='line'")

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


def _record_mapping(record):
    if is_dataclass(record) and not isinstance(record, type):
        return asdict(record)
    if isinstance(record, dict):
        return dict(record)
    raise StoryIndexError("Story-index records must be mappings or dataclass instances")


def _required_text(record, name):
    value = record[name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()
