"""Checksum bindings for files carried by a VNTTS game pack."""

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from vntts_artifacts.file_integrity import sha256_file

_ARTIFACT_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class GamePackError(RuntimeError):
    pass


@dataclass(frozen=True)
class GamePackArtifactBinding:
    name: str
    path: Path
    sha256: str


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
        bindings[name] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": digest,
        }
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

    parsed = []
    for name in sorted(bindings):
        record = bindings[name]
        if not isinstance(record, dict):
            raise GamePackError(f"Game-pack artifact {name!r} must be an object")
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
        parsed.append(GamePackArtifactBinding(name, path, digest))
    return tuple(parsed)


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
