# VNTTS Artifacts

Small, dependency-free Python contracts shared by applications that produce or
consume VNTTS data.

The package owns versioned artifact formats and the durability primitives needed
to publish them. It intentionally excludes OCR, TTS engines, user interfaces,
provider integrations, and game-specific extraction.

## Contracts

- `vntts.story-index` JSONL, schema version 1
- VNTTS voice manifest JSON, version 2, with read compatibility for legacy
  unversioned manifests
- atomic file publication, streaming SHA-256, and stable artifact slugs

Generated-audio lookup will be added as a separate versioned contract once its
producer and consumer fields are implemented and tested together.

## Development

```bash
python -m unittest discover -s tests
```

Releases use matching package versions and immutable Git tags such as `v0.1.0`.
