"""Validation and update helpers for VNTTS voice manifests."""

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from vntts_artifacts.atomic_io import atomic_write_json

VOICE_MANIFEST_VERSION = 2


class VoiceManifestError(ValueError):
    pass


@dataclass(frozen=True)
class VoiceManifestEntry:
    character: str
    speaker: str
    aliases: tuple[str, ...]
    references: tuple[str, ...]


def load_voice_manifest(path, *, allow_legacy=True):
    path = Path(path).expanduser().resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VoiceManifestError(f"Unable to read voice manifest {path}: {error}") from error
    return manifest, validate_voice_manifest(manifest, allow_legacy=allow_legacy)


def validate_voice_manifest(manifest, *, allow_legacy=True):
    if not isinstance(manifest, dict):
        raise VoiceManifestError("Voice manifest must be a JSON object")
    version = manifest.get("version")
    if version is None:
        if not allow_legacy:
            raise VoiceManifestError("Voice manifest requires version 2")
    elif version != VOICE_MANIFEST_VERSION:
        raise VoiceManifestError(f"Unsupported voice manifest version: {version!r}")
    entries = manifest.get("voices")
    if not isinstance(entries, list):
        raise VoiceManifestError("Voice manifest must contain a voices list")

    parsed = []
    names = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise VoiceManifestError(f"Voice entry {index} must be an object")
        character = _required_entry_text(entry, "character", index, "character name")
        speaker = _required_entry_text(entry, "speaker", index, "speaker ID")
        legacy_reference = entry.get("reference")
        references = entry.get("references")
        if legacy_reference is not None and references is not None:
            raise VoiceManifestError(
                f"Voice entry {index} cannot contain reference and references"
            )
        if references is None:
            references = [] if legacy_reference is None else [legacy_reference]
        if not isinstance(references, list) or not all(
            isinstance(reference, str) and reference.strip() for reference in references
        ):
            raise VoiceManifestError(
                f"Voice entry {index} references must be non-empty strings"
            )
        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) and alias.strip() for alias in aliases
        ):
            raise VoiceManifestError(f"Voice entry {index} aliases must be non-empty strings")
        for name in (character, *aliases):
            normalized = normalize_character_name(name)
            existing_index = names.get(normalized)
            if existing_index is not None and existing_index != index:
                raise VoiceManifestError(f"Duplicate voice name or alias: {name!r}")
            names[normalized] = index
        parsed.append(
            VoiceManifestEntry(
                character=character,
                speaker=speaker,
                aliases=tuple(alias.strip() for alias in aliases),
                references=tuple(reference.strip() for reference in references),
            )
        )
    return tuple(parsed)


def upsert_voice_manifest_entry(manifest, entry):
    """Return a validated v2 manifest with one character entry replaced."""
    if not isinstance(entry, dict):
        raise VoiceManifestError("Voice entry must be an object")
    character = entry.get("character")
    if not isinstance(character, str) or not character.strip():
        raise VoiceManifestError("Voice entry requires a character name")
    current = dict(manifest)
    voices = current.get("voices", [])
    if not isinstance(voices, list):
        raise VoiceManifestError("Voice manifest must contain a voices list")
    target = normalize_character_name(character)
    current["version"] = VOICE_MANIFEST_VERSION
    current["voices"] = [
        dict(voice)
        for voice in voices
        if isinstance(voice, dict)
        and normalize_character_name(str(voice.get("character", ""))) != target
    ]
    current["voices"].append(dict(entry))
    current["voices"].sort(key=lambda voice: str(voice["character"]).casefold())
    validate_voice_manifest(current, allow_legacy=False)
    return current


def write_voice_manifest(path, manifest):
    validate_voice_manifest(manifest, allow_legacy=False)
    return atomic_write_json(path, manifest)


def normalize_character_name(character):
    normalized = unicodedata.normalize("NFKC", character or "").casefold()
    return "".join(value for value in normalized if value.isalnum())


def _required_entry_text(entry, field, index, label):
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise VoiceManifestError(f"Voice entry {index} requires a {label}")
    return value.strip()
