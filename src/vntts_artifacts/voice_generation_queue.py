"""Reader and writer for the VNTTS voice-generation queue contract."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from vntts_artifacts.atomic_io import atomic_output_path
from vntts_artifacts.hashing import text_sha256

VOICE_GENERATION_QUEUE_SCHEMA = "vntts.voice-generation-queue"
VOICE_GENERATION_QUEUE_SCHEMA_VERSION = 1
CANONICAL_VOICE_GENERATION_ACTION_BY_SOURCE_AUDIO_STATUS = MappingProxyType(
    {
        "absent": "generate",
        "unavailable": "prefer_source_audio",
    }
)
VOICE_GENERATION_EXCLUDED_SOURCE_AUDIO_STATUSES = frozenset({"available"})
VOICE_GENERATION_UNKNOWN_SOURCE_AUDIO_ACTIONS = frozenset({"manual_review", "resolve_audio"})
VOICE_GENERATION_ACTION_BY_SOURCE_AUDIO_STATUS = MappingProxyType(
    {
        "no_audio": "generate",
        "configured_unavailable": "prefer_source_audio",
        "unresolved": "manual_review",
        "unchecked": "resolve_audio",
        **CANONICAL_VOICE_GENERATION_ACTION_BY_SOURCE_AUDIO_STATUS,
    }
)
VOICE_GENERATION_ACTIONS = frozenset(VOICE_GENERATION_ACTION_BY_SOURCE_AUDIO_STATUS.values())

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class VoiceGenerationQueueError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceGenerationQueueItem:
    queue_id: str
    line_id: str
    text_sha256: str
    text: str
    action: str
    speaker: str | None
    voice_character: str | None
    source_audio_status: str | None
    source_audio_reason: str | None
    state: str | None
    document: dict[str, object]

    def to_record(self):
        """Return a copy of the original producer record, including extensions."""
        return dict(self.document)


@dataclass(frozen=True)
class VoiceGenerationQueue:
    path: Path
    metadata: dict[str, object]
    items: tuple[VoiceGenerationQueueItem, ...]

    @classmethod
    def load(cls, path):
        path = Path(path).expanduser().resolve()
        try:
            with path.open(encoding="utf-8") as stream:
                metadata = json.loads(next(stream))
                records = [json.loads(row) for row in stream]
        except (OSError, StopIteration, json.JSONDecodeError) as error:
            raise VoiceGenerationQueueError(
                f"Unable to read voice-generation queue {path}: {error}"
            ) from error
        parsed_metadata, items = _validate_document(metadata, records)
        return cls(path, parsed_metadata, items)


def load_voice_generation_queue(path):
    """Return validated metadata and typed queue items."""
    queue = VoiceGenerationQueue.load(path)
    return queue.metadata, queue.items


def write_voice_generation_queue(path, metadata, items):
    """Atomically publish a validated queue while preserving producer fields."""
    path = Path(path).expanduser().resolve()
    if not isinstance(metadata, dict):
        raise VoiceGenerationQueueError("Voice-generation queue metadata must be an object")
    records = [_record_mapping(item) for item in items]
    document_metadata = dict(metadata)
    document_metadata.setdefault("record_type", "metadata")
    document_metadata.setdefault("schema", VOICE_GENERATION_QUEUE_SCHEMA)
    document_metadata.setdefault("schema_version", VOICE_GENERATION_QUEUE_SCHEMA_VERSION)
    document_metadata["item_count"] = len(records)
    _validate_document(document_metadata, records)

    with atomic_output_path(path) as temporary:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(document_metadata, ensure_ascii=False, sort_keys=True) + "\n")
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def expected_voice_generation_queue_id(line_id, text_hash):
    """Return the stable v1 queue identity for an exact story line revision."""
    line_id = _required_text(line_id, "line_id")
    text_hash = _required_hash(text_hash, "text_sha256")
    return f"{line_id}:{text_hash[:16]}"


def voice_generation_action(source_audio_status, *, unknown_action=None):
    """Return the v1 action, ``None`` for available audio, or require unknown policy."""
    try:
        return VOICE_GENERATION_ACTION_BY_SOURCE_AUDIO_STATUS[source_audio_status]
    except (KeyError, TypeError) as error:
        if (
            isinstance(source_audio_status, str)
            and source_audio_status in VOICE_GENERATION_EXCLUDED_SOURCE_AUDIO_STATUSES
        ):
            return None
        if source_audio_status == "unknown":
            if unknown_action not in VOICE_GENERATION_UNKNOWN_SOURCE_AUDIO_ACTIONS:
                allowed = ", ".join(sorted(VOICE_GENERATION_UNKNOWN_SOURCE_AUDIO_ACTIONS))
                raise VoiceGenerationQueueError(
                    "Canonical source_audio_status 'unknown' requires an explicit "
                    f"unknown_action: {allowed}"
                ) from error
            return unknown_action
        raise VoiceGenerationQueueError(
            f"Unsupported source_audio_status: {source_audio_status!r}"
        ) from error


def _validate_document(metadata, records):
    parsed_metadata = _validate_metadata(metadata)
    if not isinstance(records, list):
        raise VoiceGenerationQueueError("Voice-generation queue items must be a list")
    if parsed_metadata["item_count"] != len(records):
        raise VoiceGenerationQueueError("Voice-generation queue item count does not match metadata")

    items = []
    queue_ids = set()
    line_ids = set()
    for index, record in enumerate(records):
        item = _validate_item(record, index)
        if item.queue_id in queue_ids:
            raise VoiceGenerationQueueError(
                f"Duplicate voice-generation queue_id: {item.queue_id!r}"
            )
        if item.line_id in line_ids:
            raise VoiceGenerationQueueError(f"Duplicate voice-generation line_id: {item.line_id!r}")
        queue_ids.add(item.queue_id)
        line_ids.add(item.line_id)
        items.append(item)

    _validate_optional_summary_counts(parsed_metadata, items)
    return parsed_metadata, tuple(items)


def _validate_metadata(metadata):
    if not isinstance(metadata, dict):
        raise VoiceGenerationQueueError("Voice-generation queue metadata must be an object")
    if metadata.get("record_type") != "metadata":
        raise VoiceGenerationQueueError("Voice-generation queue must begin with a metadata record")
    if metadata.get("schema") != VOICE_GENERATION_QUEUE_SCHEMA:
        raise VoiceGenerationQueueError(
            f"Unsupported voice-generation queue schema: {metadata.get('schema')!r}"
        )
    if metadata.get("schema_version") != VOICE_GENERATION_QUEUE_SCHEMA_VERSION:
        raise VoiceGenerationQueueError(
            f"Unsupported voice-generation queue schema version: {metadata.get('schema_version')!r}"
        )
    _non_negative_integer(metadata.get("item_count"), "metadata item_count")

    for field in ("game", "language"):
        if field in metadata:
            _required_text(metadata[field], f"metadata {field}")
    if "generated_at" in metadata:
        _timezone_aware_timestamp(metadata["generated_at"], "metadata generated_at")

    source_path = metadata.get("source_story_index")
    source_hash = metadata.get("source_story_index_sha256")
    if source_path is not None or source_hash is not None:
        _required_text(source_path, "metadata source_story_index")
        _required_hash(source_hash, "metadata source_story_index_sha256")

    for field in ("character_count",):
        if field in metadata:
            _non_negative_integer(metadata[field], f"metadata {field}")
    for field in ("source_audio_status_counts", "action_counts", "source_kind_counts"):
        if field in metadata:
            _count_mapping(metadata[field], f"metadata {field}")
    if "filters" in metadata and not isinstance(metadata["filters"], dict):
        raise VoiceGenerationQueueError("Voice-generation queue metadata filters must be an object")
    return dict(metadata)


def _validate_item(record, index):
    if not isinstance(record, dict):
        raise VoiceGenerationQueueError(f"Voice-generation item {index} must be an object")
    if record.get("record_type") != "generation_item":
        raise VoiceGenerationQueueError(
            f"Voice-generation item {index} must have record_type='generation_item'"
        )
    line_id = _required_text(record.get("line_id"), f"item {index} line_id")
    text = _required_exact_text(record.get("text"), f"item {index} text")
    text_hash = _required_hash(record.get("text_sha256"), f"item {index} text_sha256")
    if text_sha256(text) != text_hash:
        raise VoiceGenerationQueueError(
            f"Voice-generation item {index} text_sha256 does not match exact text"
        )
    queue_id = _required_text(record.get("queue_id"), f"item {index} queue_id")
    expected_queue_id = expected_voice_generation_queue_id(line_id, text_hash)
    if queue_id != expected_queue_id:
        raise VoiceGenerationQueueError(
            f"Voice-generation item {index} queue_id must be {expected_queue_id!r}"
        )
    action = _required_text(record.get("action"), f"item {index} action")
    if action not in VOICE_GENERATION_ACTIONS:
        raise VoiceGenerationQueueError(
            f"Voice-generation item {index} has unsupported action {action!r}"
        )

    source_status = _optional_text(record.get("source_audio_status"), "source_audio_status")
    source_reason = _optional_text(record.get("source_audio_reason"), "source_audio_reason")
    if source_status is None and source_reason is not None:
        raise VoiceGenerationQueueError(
            f"Voice-generation item {index} source_audio_reason requires source_audio_status"
        )
    if source_status is not None:
        if source_status in VOICE_GENERATION_EXCLUDED_SOURCE_AUDIO_STATUSES:
            raise VoiceGenerationQueueError(
                f"Voice-generation item {index} source_audio_status {source_status!r} "
                "must be excluded from the queue"
            )
        expected_action = voice_generation_action(
            source_status,
            unknown_action=action if source_status == "unknown" else None,
        )
        if action != expected_action:
            raise VoiceGenerationQueueError(
                f"Voice-generation item {index} action {action!r} does not match "
                f"source_audio_status {source_status!r}"
            )
        if source_reason is None:
            raise VoiceGenerationQueueError(
                f"Voice-generation item {index} requires source_audio_reason"
            )

    speaker = _optional_text(record.get("speaker"), "speaker")
    voice_character = _optional_text(record.get("voice_character"), "voice_character")
    if "source_kind" in record:
        _required_text(record["source_kind"], f"item {index} source_kind")
    state = _optional_text(record.get("state"), "state")
    if state is not None and state != "pending":
        raise VoiceGenerationQueueError(f"Voice-generation item {index} state must be 'pending'")
    for field in ("previous_text", "next_text"):
        value = record.get(field)
        if value is not None and not isinstance(value, str):
            raise VoiceGenerationQueueError(
                f"Voice-generation item {index} {field} must be text or null"
            )
    for field in ("sequence", "story_order"):
        value = record.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise VoiceGenerationQueueError(
                f"Voice-generation item {index} {field} must be an integer or null"
            )
    return VoiceGenerationQueueItem(
        queue_id=queue_id,
        line_id=line_id,
        text_sha256=text_hash,
        text=text,
        action=action,
        speaker=speaker,
        voice_character=voice_character,
        source_audio_status=source_status,
        source_audio_reason=source_reason,
        state=state,
        document=dict(record),
    )


def _validate_optional_summary_counts(metadata, items):
    summaries = {
        "source_audio_status_counts": Counter(
            item.source_audio_status for item in items if item.source_audio_status is not None
        ),
        "action_counts": Counter(item.action for item in items),
        "source_kind_counts": Counter(
            str(item.document["source_kind"])
            for item in items
            if item.document.get("source_kind") is not None
        ),
    }
    for field, counts in summaries.items():
        if field in metadata and metadata[field] != dict(sorted(counts.items())):
            raise VoiceGenerationQueueError(
                f"Voice-generation queue {field} does not match its items"
            )
    if "character_count" in metadata:
        characters = {item.voice_character for item in items if item.voice_character is not None}
        if metadata["character_count"] != len(characters):
            raise VoiceGenerationQueueError(
                "Voice-generation queue character_count does not match its items"
            )


def _required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise VoiceGenerationQueueError(f"Voice-generation queue {label} must be non-empty text")
    return value.strip()


def _required_exact_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise VoiceGenerationQueueError(f"Voice-generation queue {label} must be non-empty text")
    return value


def _optional_text(value, label):
    if value is None:
        return None
    if not isinstance(value, str):
        raise VoiceGenerationQueueError(f"Voice-generation queue {label} must be text when present")
    return value.strip() or None


def _required_hash(value, label):
    value = _required_text(value, label)
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise VoiceGenerationQueueError(f"Voice-generation queue {label} must be lowercase SHA-256")
    return value


def _non_negative_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VoiceGenerationQueueError(
            f"Voice-generation queue {label} must be a non-negative integer"
        )
    return value


def _count_mapping(value, label):
    if not isinstance(value, dict):
        raise VoiceGenerationQueueError(f"Voice-generation queue {label} must be an object")
    for key, count in value.items():
        _required_text(key, f"{label} key")
        _non_negative_integer(count, f"{label} count")


def _timezone_aware_timestamp(value, label):
    value = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise VoiceGenerationQueueError(
            f"Voice-generation queue {label} must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VoiceGenerationQueueError(
            f"Voice-generation queue {label} must include a timezone offset"
        )


def _record_mapping(item):
    if isinstance(item, VoiceGenerationQueueItem):
        return item.to_record()
    if isinstance(item, dict):
        return dict(item)
    raise VoiceGenerationQueueError(
        "Voice-generation queue items must be mappings or VoiceGenerationQueueItem instances"
    )
