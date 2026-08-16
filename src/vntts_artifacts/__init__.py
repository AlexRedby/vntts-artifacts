"""Versioned artifact contracts shared by VNTTS producers and consumers."""

from vntts_artifacts.audio import PCM16_MONO_WAV_FORMAT
from vntts_artifacts.game_pack import (
    GAME_PACK_SCHEMA,
    GAME_PACK_SCHEMA_VERSION,
    GamePack,
    GamePackArtifactBinding,
    GamePackError,
    GamePackProducer,
    create_game_pack_artifact_bindings,
    load_game_pack,
    validate_game_pack_artifact_bindings,
    write_game_pack,
)
from vntts_artifacts.generated_audio import (
    GENERATED_AUDIO_SCHEMA,
    GENERATED_AUDIO_SCHEMA_VERSION,
)
from vntts_artifacts.hashing import text_sha256
from vntts_artifacts.story_index import (
    SOURCE_AUDIO_STATUSES,
    STORY_INDEX_SCHEMA,
    STORY_INDEX_SCHEMA_VERSION,
)
from vntts_artifacts.voice_generation_queue import (
    VOICE_GENERATION_ACTION_BY_SOURCE_AUDIO_STATUS,
    VOICE_GENERATION_ACTIONS,
    VOICE_GENERATION_QUEUE_SCHEMA,
    VOICE_GENERATION_QUEUE_SCHEMA_VERSION,
    VoiceGenerationQueue,
    VoiceGenerationQueueError,
    VoiceGenerationQueueItem,
    expected_voice_generation_queue_id,
    load_voice_generation_queue,
    voice_generation_action,
    write_voice_generation_queue,
)
from vntts_artifacts.voice_manifest import VOICE_MANIFEST_VERSION

__all__ = [
    "GENERATED_AUDIO_SCHEMA",
    "GENERATED_AUDIO_SCHEMA_VERSION",
    "GAME_PACK_SCHEMA",
    "GAME_PACK_SCHEMA_VERSION",
    "GamePack",
    "GamePackArtifactBinding",
    "GamePackError",
    "GamePackProducer",
    "PCM16_MONO_WAV_FORMAT",
    "SOURCE_AUDIO_STATUSES",
    "STORY_INDEX_SCHEMA",
    "STORY_INDEX_SCHEMA_VERSION",
    "VOICE_MANIFEST_VERSION",
    "VOICE_GENERATION_ACTION_BY_SOURCE_AUDIO_STATUS",
    "VOICE_GENERATION_ACTIONS",
    "VOICE_GENERATION_QUEUE_SCHEMA",
    "VOICE_GENERATION_QUEUE_SCHEMA_VERSION",
    "VoiceGenerationQueue",
    "VoiceGenerationQueueError",
    "VoiceGenerationQueueItem",
    "create_game_pack_artifact_bindings",
    "load_game_pack",
    "load_voice_generation_queue",
    "expected_voice_generation_queue_id",
    "text_sha256",
    "validate_game_pack_artifact_bindings",
    "voice_generation_action",
    "write_voice_generation_queue",
    "write_game_pack",
]
