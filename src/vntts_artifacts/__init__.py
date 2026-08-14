"""Versioned artifact contracts shared by VNTTS producers and consumers."""

from vntts_artifacts.generated_audio import (
    GENERATED_AUDIO_SCHEMA,
    GENERATED_AUDIO_SCHEMA_VERSION,
)
from vntts_artifacts.story_index import (
    STORY_INDEX_SCHEMA,
    STORY_INDEX_SCHEMA_VERSION,
)
from vntts_artifacts.voice_manifest import VOICE_MANIFEST_VERSION

__all__ = [
    "GENERATED_AUDIO_SCHEMA",
    "GENERATED_AUDIO_SCHEMA_VERSION",
    "STORY_INDEX_SCHEMA",
    "STORY_INDEX_SCHEMA_VERSION",
    "VOICE_MANIFEST_VERSION",
]
