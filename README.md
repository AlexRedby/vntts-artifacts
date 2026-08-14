# VNTTS Artifacts

Small Python contracts shared by applications that produce or consume VNTTS
data. The core is dependency-free; PCM WAV publication has an optional NumPy
extra.

The package owns versioned artifact formats and delegates generic publication
and checksum primitives to the separately released `durable-file` package. It
intentionally excludes OCR, TTS engines, user interfaces, provider integrations,
and game-specific extraction.

## Contracts

- `vntts.story-index` JSONL, schema version 1
- `vntts.generated-audio` JSON, schema version 1, with exact lookup by stable
  story line ID and SHA-256 of the current story text
- VNTTS voice manifest JSON, version 2, with read compatibility for legacy
  unversioned manifests
- atomic file publication, streaming SHA-256, stable text hashes and artifact
  slugs
- the `wav-pcm16-mono` format constant plus shared PCM WAV probing, reading and
  atomic publication helpers

Generated-audio entries use portable POSIX-relative paths, mono 16-bit PCM WAV,
and include the audio SHA-256, sample rate, and sample count. Consumers reject
missing or modified files and must fall back to live synthesis when an exact
identity is not available.

```json
{
  "schema": "vntts.generated-audio",
  "schema_version": 1,
  "entry_count": 1,
  "entries": [
    {
      "line_id": "game:chapter:line",
      "text_sha256": "<lowercase SHA-256 of exact UTF-8 story text>",
      "audio": "audio/game-chapter-line.wav",
      "audio_format": "wav-pcm16-mono",
      "audio_sha256": "<lowercase SHA-256 of the WAV file>",
      "sample_rate": 24000,
      "sample_count": 48000
    }
  ]
}
```

Top-level and entry-level producer provenance fields are preserved as contract
extensions.

## Development

```bash
python -m unittest discover -s tests
```

Install `vntts-artifacts[audio]` when using `write_pcm16_wav`.

Releases use matching package versions and immutable Git tags such as `v0.1.0`.
