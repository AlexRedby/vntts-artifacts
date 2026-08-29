"""Versioned, checksum-bound live story sequence plans."""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from vntts_artifacts.atomic_io import atomic_write_json
from vntts_artifacts.file_integrity import sha256_file
from vntts_artifacts.story_index import StoryIndexError, load_story_index

LIVE_SEQUENCE_SCHEMA = "vntts.live-sequence-plan"
LIVE_SEQUENCE_SCHEMA_VERSION = 1

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_EVENT_KINDS = frozenset({"speech", "silent", "transition", "choice", "wait"})
_CONTROLS = frozenset({"automatic", "passive", "manual", "terminal"})


class LiveSequencePlanError(RuntimeError):
    """Raised when a sequence plan is unsafe or belongs to other source data."""


@dataclass(frozen=True)
class LiveSequenceEvent:
    event_id: str
    chapter: str
    sequence: int
    kind: str
    control: str
    successors: tuple[str, ...]
    line_id: str | None = None

    @property
    def is_speech(self):
        return self.kind == "speech"


@dataclass(frozen=True)
class LiveSequenceChapter:
    chapter: str
    entry_event_ids: tuple[str, ...]
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class LiveSequencePlan:
    path: Path
    game_id: str
    producer_name: str
    producer_version: str
    story_index_path: Path
    story_index_sha256: str
    source_extract_sha256: str
    chapters: tuple[LiveSequenceChapter, ...]
    events: dict[str, LiveSequenceEvent]
    event_id_by_line_id: dict[str, str]

    @classmethod
    def load(cls, path, story_index_path):
        return load_live_sequence_plan(path, story_index_path)

    def event_for_line(self, line_id):
        event_id = self.event_id_by_line_id.get(str(line_id))
        return self.events.get(event_id) if event_id is not None else None

    def chapter(self, chapter):
        chapter = str(chapter)
        return next((item for item in self.chapters if item.chapter == chapter), None)


def load_live_sequence_plan(path, story_index_path):
    """Load and fully validate a plan against the exact story-index bytes."""
    path = Path(path).expanduser().resolve()
    story_index_path = Path(story_index_path).expanduser().resolve()
    document = _read_document(path)
    _require_exact_keys(
        document,
        {
            "schema",
            "schema_version",
            "game_id",
            "producer",
            "story_index_sha256",
            "source_extract_sha256",
            "chapters",
        },
        "Live sequence plan",
    )
    if document["schema"] != LIVE_SEQUENCE_SCHEMA:
        raise LiveSequencePlanError(f"Unsupported live sequence schema: {document['schema']!r}")
    if document["schema_version"] != LIVE_SEQUENCE_SCHEMA_VERSION:
        raise LiveSequencePlanError(
            f"Unsupported live sequence schema version: {document['schema_version']!r}"
        )
    game_id = _required_text(document["game_id"], "game id")
    producer_name, producer_version = _parse_producer(document["producer"])
    story_digest = _required_sha256(document["story_index_sha256"], "story index SHA-256")
    source_digest = _required_sha256(document["source_extract_sha256"], "source extract SHA-256")
    try:
        actual_story_digest = sha256_file(story_index_path)
    except OSError as error:
        raise LiveSequencePlanError(
            f"Unable to checksum story index {story_index_path}: {error}"
        ) from error
    if actual_story_digest != story_digest:
        raise LiveSequencePlanError("Live sequence plan belongs to different story-index bytes")
    story_lines = _load_story_lines(story_index_path)
    chapters, events, event_id_by_line_id = _parse_chapters(document["chapters"], story_lines)
    _validate_graph(chapters, events)
    return LiveSequencePlan(
        path=path,
        game_id=game_id,
        producer_name=producer_name,
        producer_version=producer_version,
        story_index_path=story_index_path,
        story_index_sha256=story_digest,
        source_extract_sha256=source_digest,
        chapters=chapters,
        events=events,
        event_id_by_line_id=event_id_by_line_id,
    )


def write_live_sequence_plan(path, document, story_index_path):
    """Validate, atomically write and re-read one canonical sequence plan."""
    if not isinstance(document, dict):
        raise LiveSequencePlanError("Live sequence plan input must be an object")
    story_index_path = Path(story_index_path).expanduser().resolve()
    payload = dict(document)
    payload["schema"] = LIVE_SEQUENCE_SCHEMA
    payload["schema_version"] = LIVE_SEQUENCE_SCHEMA_VERSION
    try:
        payload["story_index_sha256"] = sha256_file(story_index_path)
    except OSError as error:
        raise LiveSequencePlanError(
            f"Unable to checksum story index {story_index_path}: {error}"
        ) from error
    path = Path(path).expanduser().resolve()
    with TemporaryDirectory(prefix="vntts-live-sequence-") as directory:
        candidate = Path(directory) / path.name
        atomic_write_json(candidate, payload)
        load_live_sequence_plan(candidate, story_index_path)
    atomic_write_json(path, payload)
    return load_live_sequence_plan(path, story_index_path)


def _read_document(path):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LiveSequencePlanError(f"Unable to read live sequence plan {path}: {error}") from error
    if not isinstance(document, dict):
        raise LiveSequencePlanError("Live sequence plan must be an object")
    return document


def _load_story_lines(path):
    try:
        _metadata, lines = load_story_index(path)
    except StoryIndexError as error:
        raise LiveSequencePlanError(f"Invalid story index {path}: {error}") from error
    by_id = {}
    for line in lines:
        if line.line_id in by_id:
            raise LiveSequencePlanError(f"Story index repeats line ID {line.line_id!r}")
        by_id[line.line_id] = line
    return by_id


def _parse_producer(value):
    _require_exact_keys(value, {"name", "version"}, "Live sequence producer")
    return (
        _required_text(value["name"], "producer name"),
        _required_text(value["version"], "producer version"),
    )


def _parse_chapters(raw_chapters, story_lines):
    if not isinstance(raw_chapters, list) or not raw_chapters:
        raise LiveSequencePlanError("Live sequence chapters must be a non-empty list")
    chapters = []
    events = {}
    event_id_by_line_id = {}
    chapter_names = set()
    for chapter_index, raw_chapter in enumerate(raw_chapters):
        label = f"Live sequence chapter {chapter_index}"
        _require_exact_keys(
            raw_chapter,
            {"chapter", "entry_event_ids", "events"},
            label,
        )
        chapter = _required_text(raw_chapter["chapter"], f"{label} name")
        if chapter in chapter_names:
            raise LiveSequencePlanError(f"Live sequence repeats chapter {chapter!r}")
        chapter_names.add(chapter)
        entry_event_ids = _text_list(
            raw_chapter["entry_event_ids"], f"{label} entry_event_ids", nonempty=True
        )
        raw_events = raw_chapter["events"]
        if not isinstance(raw_events, list) or not raw_events:
            raise LiveSequencePlanError(f"{label} events must be a non-empty list")
        chapter_event_ids = []
        for event_index, raw_event in enumerate(raw_events):
            event = _parse_event(
                raw_event,
                chapter,
                f"{label} event {event_index}",
                story_lines,
            )
            if event.event_id in events:
                raise LiveSequencePlanError(f"Live sequence repeats event ID {event.event_id!r}")
            if event.line_id is not None:
                previous = event_id_by_line_id.get(event.line_id)
                if previous is not None:
                    raise LiveSequencePlanError(
                        f"Story line {event.line_id!r} is bound by both "
                        f"{previous!r} and {event.event_id!r}"
                    )
                event_id_by_line_id[event.line_id] = event.event_id
            events[event.event_id] = event
            chapter_event_ids.append(event.event_id)
        chapters.append(LiveSequenceChapter(chapter, entry_event_ids, tuple(chapter_event_ids)))
    return tuple(chapters), events, event_id_by_line_id


def _parse_event(value, chapter, label, story_lines):
    if not isinstance(value, dict):
        raise LiveSequencePlanError(f"{label} must be an object")
    allowed = {"event_id", "sequence", "kind", "control", "successors", "line_id"}
    unknown = set(value).difference(allowed)
    missing = allowed.difference({"line_id"}).difference(value)
    if unknown or missing:
        detail = sorted(unknown or missing)[0]
        word = "unsupported field" if unknown else "missing field"
        raise LiveSequencePlanError(f"{label} has {word} {detail!r}")
    event_id = _required_text(value["event_id"], f"{label} event_id")
    sequence = value["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise LiveSequencePlanError(f"{label} sequence must be a non-negative integer")
    kind = _required_text(value["kind"], f"{label} kind")
    if kind not in _EVENT_KINDS:
        raise LiveSequencePlanError(f"{label} has unsupported kind {kind!r}")
    control = _required_text(value["control"], f"{label} control")
    if control not in _CONTROLS:
        raise LiveSequencePlanError(f"{label} has unsupported control {control!r}")
    successors = _text_list(value["successors"], f"{label} successors")
    if control in {"automatic", "passive"} and len(successors) != 1:
        raise LiveSequencePlanError(f"{label} {control} control requires exactly one successor")
    if control == "terminal" and successors:
        raise LiveSequencePlanError(f"{label} terminal control cannot have successors")
    if kind == "choice" and control != "manual":
        raise LiveSequencePlanError(f"{label} choice requires manual control")
    if kind == "wait" and control != "manual":
        raise LiveSequencePlanError(f"{label} wait requires manual control")
    if kind == "transition" and control not in {"passive", "terminal"}:
        raise LiveSequencePlanError(f"{label} transition requires passive or terminal control")
    line_id = value.get("line_id")
    if kind == "speech":
        line_id = _required_text(line_id, f"{label} line_id")
        story_line = story_lines.get(line_id)
        if story_line is None:
            raise LiveSequencePlanError(f"{label} references unknown story line {line_id!r}")
        if str(story_line.chapter) != chapter:
            raise LiveSequencePlanError(
                f"{label} line {line_id!r} belongs to chapter {story_line.chapter!r}"
            )
    elif line_id is not None:
        raise LiveSequencePlanError(f"{label} non-speech event cannot bind a line_id")
    return LiveSequenceEvent(
        event_id=event_id,
        chapter=chapter,
        sequence=sequence,
        kind=kind,
        control=control,
        successors=successors,
        line_id=line_id,
    )


def _validate_graph(chapters, events):
    for event in events.values():
        for successor_id in event.successors:
            successor = events.get(successor_id)
            if successor is None:
                raise LiveSequencePlanError(
                    f"Event {event.event_id!r} has missing successor {successor_id!r}"
                )
            if successor.chapter != event.chapter:
                raise LiveSequencePlanError(
                    f"Event {event.event_id!r} crosses chapter without an explicit boundary"
                )
    for chapter in chapters:
        chapter_ids = set(chapter.event_ids)
        unknown_entries = set(chapter.entry_event_ids).difference(chapter_ids)
        if unknown_entries:
            raise LiveSequencePlanError(
                f"Chapter {chapter.chapter!r} has unknown entry event "
                f"{sorted(unknown_entries)[0]!r}"
            )
        reachable = set(chapter.entry_event_ids)
        pending = deque(chapter.entry_event_ids)
        while pending:
            event = events[pending.popleft()]
            for successor_id in event.successors:
                if successor_id not in reachable:
                    reachable.add(successor_id)
                    pending.append(successor_id)
        unreachable = chapter_ids.difference(reachable)
        if unreachable:
            raise LiveSequencePlanError(
                f"Chapter {chapter.chapter!r} has unreachable event {sorted(unreachable)[0]!r}"
            )
        _reject_unguarded_automatic_cycles(chapter, events)


def _reject_unguarded_automatic_cycles(chapter, events):
    visiting = set()
    visited = set()

    def visit(event_id):
        if event_id in visiting:
            raise LiveSequencePlanError(
                f"Chapter {chapter.chapter!r} has an unguarded automatic cycle at {event_id!r}"
            )
        if event_id in visited:
            return
        event = events[event_id]
        if event.control not in {"automatic", "passive"}:
            visited.add(event_id)
            return
        visiting.add(event_id)
        for successor_id in event.successors:
            visit(successor_id)
        visiting.remove(event_id)
        visited.add(event_id)

    for event_id in chapter.event_ids:
        visit(event_id)


def _text_list(value, label, *, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        qualifier = "non-empty " if nonempty else ""
        raise LiveSequencePlanError(f"{label} must be a {qualifier}list")
    parsed = tuple(_required_text(item, label) for item in value)
    if len(set(parsed)) != len(parsed):
        raise LiveSequencePlanError(f"{label} cannot contain duplicates")
    return parsed


def _require_exact_keys(value, expected, label):
    if not isinstance(value, dict):
        raise LiveSequencePlanError(f"{label} must be an object")
    unknown = set(value).difference(expected)
    missing = expected.difference(value)
    if unknown:
        raise LiveSequencePlanError(f"{label} has unsupported field {sorted(unknown)[0]!r}")
    if missing:
        raise LiveSequencePlanError(f"{label} is missing field {sorted(missing)[0]!r}")


def _required_sha256(value, label):
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise LiveSequencePlanError(f"{label} must be lowercase SHA-256")
    return value


def _required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise LiveSequencePlanError(f"{label} must be non-empty text")
    return value.strip()
