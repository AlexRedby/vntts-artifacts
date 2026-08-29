"""Versioned, checksum-bound VNTTS game-pack documents."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from vntts_artifacts.atomic_io import atomic_write_json
from vntts_artifacts.file_integrity import sha256_file
from vntts_artifacts.generated_audio import GeneratedAudioIndex
from vntts_artifacts.live_sequence import (
    LiveSequencePlanError,
    load_live_sequence_plan,
)
from vntts_artifacts.story_index import load_story_index
from vntts_artifacts.voice_manifest import load_voice_manifest

GAME_PACK_SCHEMA = "vntts.game-pack"
GAME_PACK_SCHEMA_VERSION = 2
SUPPORTED_GAME_PACK_SCHEMA_VERSIONS = frozenset({1, GAME_PACK_SCHEMA_VERSION})

_ARTIFACT_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
_EXTENSION_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_CORE_FIELDS = frozenset(
    {"schema", "schema_version", "game", "producers", "created_at", "components"}
)
_COMPONENT_FIELDS_V1 = frozenset({"story_index", "voice_manifest", "voice_wavs", "generated_audio"})
_COMPONENT_FIELDS = _COMPONENT_FIELDS_V1 | {"live_sequence_plan"}


class GamePackError(RuntimeError):
    pass


@dataclass(frozen=True)
class GamePackArtifactBinding:
    name: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class GamePackProducer:
    name: str
    version: str


@dataclass(frozen=True)
class GamePack:
    """A fully validated game pack whose artifact paths are absolute and resolved."""

    manifest_path: Path
    game_id: str
    game_version: str
    producers: tuple[GamePackProducer, ...]
    created_at: str
    schema_version: int
    story_index: GamePackArtifactBinding
    voice_manifest: GamePackArtifactBinding
    voice_wavs: tuple[GamePackArtifactBinding, ...]
    generated_audio: GamePackArtifactBinding | None
    generated_wavs: tuple[GamePackArtifactBinding, ...]
    live_sequence_plan: GamePackArtifactBinding | None
    extensions: dict[str, object]

    @property
    def artifacts(self):
        generated_manifest = () if self.generated_audio is None else (self.generated_audio,)
        live_sequence_plan = () if self.live_sequence_plan is None else (self.live_sequence_plan,)
        return (
            self.story_index,
            self.voice_manifest,
            *self.voice_wavs,
            *generated_manifest,
            *self.generated_wavs,
            *live_sequence_plan,
        )


def write_game_pack(path, metadata, components):
    """Validate component manifests and atomically write a complete game-pack document.

    ``metadata`` supplies ``game``, ``producers``, ``created_at``, and optional
    namespaced extension fields. ``components`` supplies paths for required
    ``story_index`` and ``voice_manifest`` files and an optional
    ``generated_audio`` manifest and optional ``live_sequence_plan``. Referenced
    WAV bindings are derived rather than accepted from the caller.
    """
    path = Path(path).expanduser().resolve()
    root = path.parent
    if not isinstance(metadata, dict):
        raise GamePackError("Game-pack metadata must be an object")
    if not isinstance(components, dict):
        raise GamePackError("Game-pack components must be an object")
    unknown_components = set(components).difference(
        {"story_index", "voice_manifest", "generated_audio", "live_sequence_plan"}
    )
    if unknown_components:
        raise GamePackError(f"Unsupported game-pack component: {sorted(unknown_components)[0]!r}")
    missing = {"story_index", "voice_manifest"}.difference(components)
    if missing:
        raise GamePackError(f"Game pack is missing required component: {sorted(missing)[0]}")

    core_metadata, extensions = _validate_metadata(metadata)
    story_path = _source_component_path(root, components["story_index"], "story_index")
    voice_path = _source_component_path(root, components["voice_manifest"], "voice_manifest")
    _load_story_index(story_path)
    voice_wav_paths = _load_voice_wav_paths(root, voice_path)

    live_sequence_path = None
    if components.get("live_sequence_plan") is not None:
        live_sequence_path = _source_component_path(
            root, components["live_sequence_plan"], "live_sequence_plan"
        )
        live_sequence = _load_live_sequence(live_sequence_path, story_path)
        if live_sequence.game_id != core_metadata["game"]["id"]:
            raise GamePackError("Game-pack live sequence plan belongs to a different game")

    generated_path = None
    generated_wav_paths = ()
    if components.get("generated_audio") is not None:
        generated_path = _source_component_path(
            root, components["generated_audio"], "generated_audio"
        )
        generated_wav_paths = _load_generated_wav_paths(root, generated_path)

    named_paths = {
        "story_index": story_path,
        "voice_manifest": voice_path,
        **{f"voice_wav_{index:04d}": value for index, value in enumerate(voice_wav_paths)},
    }
    if generated_path is not None:
        named_paths["generated_audio"] = generated_path
        named_paths.update(
            {f"generated_wav_{index:04d}": value for index, value in enumerate(generated_wav_paths)}
        )
    if live_sequence_path is not None:
        named_paths["live_sequence_plan"] = live_sequence_path
    _reject_duplicate_paths(named_paths)
    bindings = create_game_pack_artifact_bindings(root, named_paths)

    document = {
        "schema": GAME_PACK_SCHEMA,
        "schema_version": GAME_PACK_SCHEMA_VERSION,
        **core_metadata,
        "components": {
            "story_index": bindings["story_index"],
            "voice_manifest": bindings["voice_manifest"],
            "voice_wavs": [
                bindings[f"voice_wav_{index:04d}"] for index in range(len(voice_wav_paths))
            ],
        },
        **extensions,
    }
    if generated_path is not None:
        document["components"]["generated_audio"] = {
            "manifest": bindings["generated_audio"],
            "wavs": [
                bindings[f"generated_wav_{index:04d}"] for index in range(len(generated_wav_paths))
            ],
        }
    if live_sequence_path is not None:
        document["components"]["live_sequence_plan"] = bindings["live_sequence_plan"]
    atomic_write_json(path, document)
    return load_game_pack(path)


def load_game_pack(path):
    """Read and fully validate a game pack before returning resolved paths."""
    path = Path(path).expanduser().resolve()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GamePackError(f"Unable to read game pack {path}: {error}") from error
    if not isinstance(document, dict):
        raise GamePackError("Game-pack document must be an object")
    if document.get("schema") != GAME_PACK_SCHEMA:
        raise GamePackError(f"Unsupported game-pack schema: {document.get('schema')!r}")
    schema_version = document.get("schema_version")
    if schema_version not in SUPPORTED_GAME_PACK_SCHEMA_VERSIONS:
        raise GamePackError(f"Unsupported game-pack schema version: {schema_version!r}")
    core_metadata, extensions = _validate_metadata(
        {
            key: value
            for key, value in document.items()
            if key not in {"schema", "schema_version", "components"}
        }
    )
    unknown_fields = set(document).difference(_CORE_FIELDS).difference(extensions)
    if unknown_fields:
        raise GamePackError(f"Unsupported game-pack field: {sorted(unknown_fields)[0]!r}")

    components = document.get("components")
    if not isinstance(components, dict):
        raise GamePackError("Game-pack components must be an object")
    supported_components = _COMPONENT_FIELDS_V1 if schema_version == 1 else _COMPONENT_FIELDS
    unknown_components = set(components).difference(supported_components)
    if unknown_components:
        raise GamePackError(f"Unsupported game-pack component: {sorted(unknown_components)[0]!r}")
    missing = {"story_index", "voice_manifest", "voice_wavs"}.difference(components)
    if missing:
        raise GamePackError(f"Game pack is missing required component: {sorted(missing)[0]}")

    root = path.parent
    story = _validate_binding(root, "story_index", components["story_index"])
    voice = _validate_binding(root, "voice_manifest", components["voice_manifest"])
    voice_wavs = _validate_binding_list(root, "voice_wav", components["voice_wavs"])
    _load_story_index(story.path)
    expected_voice_paths = _load_voice_wav_paths(root, voice.path)
    _require_exact_declared_paths("voice WAV", expected_voice_paths, voice_wavs)

    generated = None
    generated_wavs = ()
    raw_generated = components.get("generated_audio")
    if raw_generated is not None:
        if not isinstance(raw_generated, dict) or set(raw_generated) != {"manifest", "wavs"}:
            raise GamePackError("Game-pack generated_audio must contain exactly manifest and wavs")
        generated = _validate_binding(root, "generated_audio", raw_generated["manifest"])
        generated_wavs = _validate_binding_list(root, "generated_wav", raw_generated["wavs"])
        expected_generated_paths = _load_generated_wav_paths(root, generated.path)
        _require_exact_declared_paths("generated WAV", expected_generated_paths, generated_wavs)

    live_sequence = None
    raw_live_sequence = components.get("live_sequence_plan")
    if raw_live_sequence is not None:
        live_sequence = _validate_binding(root, "live_sequence_plan", raw_live_sequence)
        sequence_plan = _load_live_sequence(live_sequence.path, story.path)
        if sequence_plan.game_id != core_metadata["game"]["id"]:
            raise GamePackError("Game-pack live sequence plan belongs to a different game")

    all_bindings = (story, voice, *voice_wavs)
    if generated is not None:
        all_bindings += (generated, *generated_wavs)
    if live_sequence is not None:
        all_bindings += (live_sequence,)
    _reject_duplicate_paths({binding.name: binding.path for binding in all_bindings})

    game = core_metadata["game"]
    return GamePack(
        manifest_path=path,
        game_id=game["id"],
        game_version=game["version"],
        producers=tuple(
            GamePackProducer(producer["name"], producer["version"])
            for producer in core_metadata["producers"]
        ),
        created_at=core_metadata["created_at"],
        schema_version=schema_version,
        story_index=story,
        voice_manifest=voice,
        voice_wavs=voice_wavs,
        generated_audio=generated,
        generated_wavs=generated_wavs,
        live_sequence_plan=live_sequence,
        extensions=extensions,
    )


def create_game_pack_artifact_bindings(root, artifacts):
    """Return deterministic portable paths and SHA-256 digests for pack files."""
    root = Path(root).expanduser().resolve()
    if not isinstance(artifacts, dict) or not artifacts:
        raise GamePackError("Game-pack artifacts must be a non-empty mapping")

    for name in artifacts:
        _validate_artifact_name(name)
    bindings = {}
    for name in sorted(artifacts):
        path = _resolve_source_path(root, artifacts[name], name)
        try:
            digest = sha256_file(path)
        except OSError as error:
            raise GamePackError(f"Unable to checksum game-pack artifact {path}: {error}") from error
        bindings[name] = {"path": path.relative_to(root).as_posix(), "sha256": digest}
    return bindings


def validate_game_pack_artifact_bindings(root, bindings, *, required=()):
    """Resolve and verify every declared game-pack artifact checksum."""
    root = Path(root).expanduser().resolve()
    if not isinstance(bindings, dict) or not bindings:
        raise GamePackError("Game-pack artifact bindings must be a non-empty mapping")
    for name in bindings:
        _validate_artifact_name(name)
    required_names = set(required)
    for name in required_names:
        _validate_artifact_name(name)
    missing = required_names.difference(bindings)
    if missing:
        raise GamePackError(f"Game pack is missing required artifact binding: {sorted(missing)[0]}")
    return tuple(
        _validate_binding(root, name, bindings[name], exact_fields=False)
        for name in sorted(bindings)
    )


def _validate_metadata(metadata):
    if not isinstance(metadata, dict):
        raise GamePackError("Game-pack metadata must be an object")
    unknown_core = {
        key
        for key in metadata
        if key not in {"game", "producers", "created_at"}
        and not (isinstance(key, str) and _EXTENSION_NAME_PATTERN.fullmatch(key))
    }
    if unknown_core:
        raise GamePackError(f"Unsupported game-pack field: {sorted(unknown_core, key=str)[0]!r}")
    extensions = {
        key: value
        for key, value in metadata.items()
        if isinstance(key, str) and _EXTENSION_NAME_PATTERN.fullmatch(key)
    }
    game = metadata.get("game")
    if not isinstance(game, dict) or set(game) != {"id", "version"}:
        raise GamePackError("Game-pack game must contain exactly id and version")
    game_id = _required_text(game.get("id"), "game id")
    game_version = _required_text(game.get("version"), "game version")
    producers = metadata.get("producers")
    if not isinstance(producers, list) or not producers:
        raise GamePackError("Game-pack producers must be a non-empty list")
    parsed_producers = []
    for index, producer in enumerate(producers):
        if not isinstance(producer, dict) or set(producer) != {"name", "version"}:
            raise GamePackError(f"Game-pack producer {index} must contain exactly name and version")
        parsed_producers.append(
            {
                "name": _required_text(producer.get("name"), f"producer {index} name"),
                "version": _required_text(producer.get("version"), f"producer {index} version"),
            }
        )
    created_at = metadata.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        raise GamePackError("Game-pack created_at must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed_created_at = datetime.fromisoformat(created_at.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise GamePackError(
            "Game-pack created_at must be a timezone-aware ISO-8601 timestamp"
        ) from error
    if parsed_created_at.tzinfo is None or parsed_created_at.utcoffset() is None:
        raise GamePackError("Game-pack created_at must include a timezone offset")
    return (
        {
            "game": {"id": game_id, "version": game_version},
            "producers": parsed_producers,
            "created_at": created_at.strip(),
        },
        extensions,
    )


def _validate_binding(root, name, record, *, exact_fields=True):
    _validate_artifact_name(name)
    if not isinstance(record, dict):
        raise GamePackError(f"Game-pack artifact {name!r} must be an object")
    if exact_fields and set(record) != {"path", "sha256"}:
        raise GamePackError(f"Game-pack artifact {name!r} must contain exactly path and sha256")
    path = _resolve_bound_path(root, record.get("path"), name)
    digest = record.get("sha256")
    if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
        raise GamePackError(f"Game-pack artifact {name!r} sha256 must be lowercase SHA-256")
    if not path.is_file():
        raise GamePackError(f"Game-pack artifact does not exist: {path}")
    try:
        actual_digest = sha256_file(path)
    except OSError as error:
        raise GamePackError(f"Unable to checksum game-pack artifact {path}: {error}") from error
    if actual_digest != digest:
        raise GamePackError(f"Game-pack artifact checksum does not match: {path}")
    return GamePackArtifactBinding(name, path, digest)


def _validate_binding_list(root, prefix, records):
    if not isinstance(records, list):
        raise GamePackError(f"Game-pack {prefix}s must be a list")
    return tuple(
        _validate_binding(root, f"{prefix}_{index:04d}", record)
        for index, record in enumerate(records)
    )


def _load_story_index(path):
    try:
        return load_story_index(path)
    except Exception as error:
        raise GamePackError(f"Invalid game-pack story index {path}: {error}") from error


def _load_live_sequence(path, story_index_path):
    try:
        return load_live_sequence_plan(path, story_index_path)
    except LiveSequencePlanError as error:
        raise GamePackError(f"Invalid game-pack live sequence plan {path}: {error}") from error


def _load_voice_wav_paths(root, manifest_path):
    try:
        _document, entries = load_voice_manifest(manifest_path, allow_legacy=False)
    except Exception as error:
        raise GamePackError(f"Invalid game-pack voice manifest {manifest_path}: {error}") from error
    paths = []
    for entry in entries:
        for reference in entry.references:
            resolved = _resolve_manifest_reference(root, manifest_path, reference, "voice WAV")
            if resolved.suffix.casefold() != ".wav":
                raise GamePackError(f"Voice reference is not a WAV file: {resolved}")
            if not resolved.is_file():
                raise GamePackError(f"Voice WAV does not exist: {resolved}")
            paths.append(resolved)
    return tuple(sorted(set(paths), key=lambda value: value.relative_to(root).as_posix()))


def _load_generated_wav_paths(root, manifest_path):
    try:
        index = GeneratedAudioIndex.load(manifest_path)
    except Exception as error:
        raise GamePackError(
            f"Invalid game-pack generated-audio manifest {manifest_path}: {error}"
        ) from error
    paths = []
    for entry in index.entries:
        path = entry.audio.resolve()
        _ensure_within_root(root, path, "generated WAV")
        if path.suffix.casefold() != ".wav":
            raise GamePackError(f"Generated audio is not a WAV file: {path}")
        if not path.is_file():
            raise GamePackError(f"Generated WAV does not exist: {path}")
        try:
            digest = sha256_file(path)
        except OSError as error:
            raise GamePackError(f"Unable to checksum generated WAV {path}: {error}") from error
        if digest != entry.audio_sha256:
            raise GamePackError(f"Generated WAV checksum does not match manifest: {path}")
        paths.append(path)
    return tuple(sorted(set(paths), key=lambda value: value.relative_to(root).as_posix()))


def _resolve_manifest_reference(root, manifest_path, value, label):
    if not isinstance(value, str) or not value.strip() or "\\" in value:
        raise GamePackError(f"{label} path must be a safe POSIX-relative path")
    relative = PurePosixPath(value.strip())
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise GamePackError(f"{label} path must be a safe POSIX-relative path")
    path = (manifest_path.parent / Path(*relative.parts)).resolve()
    _ensure_within_root(root, path, label)
    return path


def _require_exact_declared_paths(label, expected_paths, bindings):
    expected = set(expected_paths)
    declared = {binding.path for binding in bindings}
    if expected != declared or len(declared) != len(bindings):
        missing = expected.difference(declared)
        extra = declared.difference(expected)
        if missing:
            raise GamePackError(f"Referenced {label} is not declared: {sorted(missing)[0]}")
        if extra:
            raise GamePackError(f"Declared {label} is not referenced: {sorted(extra)[0]}")
        raise GamePackError(f"Duplicate declared {label} binding")


def _reject_duplicate_paths(named_paths):
    seen = {}
    for name, path in named_paths.items():
        previous = seen.get(path)
        if previous is not None:
            raise GamePackError(f"Game-pack artifacts {previous!r} and {name!r} use the same path")
        seen[path] = name


def _required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise GamePackError(f"Game-pack {label} must be non-empty text")
    return value.strip()


def _source_component_path(root, value, name):
    return _resolve_source_path(root, value, name)


def _validate_artifact_name(name):
    if not isinstance(name, str) or _ARTIFACT_NAME_PATTERN.fullmatch(name) is None:
        raise GamePackError(
            "Game-pack artifact names must use lowercase letters, digits, and underscores"
        )


def _resolve_source_path(root, value, name):
    try:
        path = Path(value).expanduser()
    except TypeError as error:
        raise GamePackError(f"Game-pack artifact {name!r} path is invalid") from error
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    _ensure_within_root(root, path, name)
    if not path.is_file():
        raise GamePackError(f"Game-pack artifact does not exist: {path}")
    return path


def _resolve_bound_path(root, value, name):
    if not isinstance(value, str) or not value.strip():
        raise GamePackError(f"Game-pack artifact {name!r} requires a path")
    value = value.strip()
    if "\\" in value:
        raise GamePackError(f"Game-pack artifact {name!r} path must use POSIX separators")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise GamePackError(f"Game-pack artifact {name!r} path must be a safe relative path")
    path = (root / Path(*relative.parts)).resolve()
    _ensure_within_root(root, path, name)
    return path


def _ensure_within_root(root, path, name):
    if path != root and root not in path.parents:
        raise GamePackError(f"Game-pack artifact {name!r} leaves the pack directory")
