"""Versioned artifact contracts shared by VNTTS producers and consumers."""

from vntts_artifacts.audio import PCM16_MONO_WAV_FORMAT
from vntts_artifacts.game_pack import (
    GamePackArtifactBinding,
    GamePackError,
    create_game_pack_artifact_bindings,
    validate_game_pack_artifact_bindings,
)
from vntts_artifacts.generated_audio import (
    GENERATED_AUDIO_SCHEMA,
    GENERATED_AUDIO_SCHEMA_VERSION,
)
from vntts_artifacts.hashing import text_sha256
from vntts_artifacts.story_index import (
    STORY_INDEX_SCHEMA,
    STORY_INDEX_SCHEMA_VERSION,
)
from vntts_artifacts.voice_manifest import VOICE_MANIFEST_VERSION

__all__ = [
    "GENERATED_AUDIO_SCHEMA",
    "GENERATED_AUDIO_SCHEMA_VERSION",
    "GamePackArtifactBinding",
    "GamePackError",
    "PCM16_MONO_WAV_FORMAT",
    "STORY_INDEX_SCHEMA",
    "STORY_INDEX_SCHEMA_VERSION",
    "VOICE_MANIFEST_VERSION",
    "create_game_pack_artifact_bindings",
    "text_sha256",
    "validate_game_pack_artifact_bindings",
]
