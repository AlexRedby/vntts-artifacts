# Authoring exchange lifecycle

The shared contracts preserve one identity across extraction, offline voice
generation, publication, and playback:

```text
story line (line_id, exact text)
  -> voice-generation queue (line_id, text_sha256, queue_id)
  -> generated-audio entry (line_id, text_sha256, WAV sha256)
  -> game pack (manifest and every referenced file sha256)
  -> consumer exact lookup (line_id, text_sha256)
```

For queue schema version 1, `queue_id` is the line ID followed by the first 16
hex characters of the exact UTF-8 text SHA-256. It identifies an authoring job;
the generated-audio contract deliberately keeps the complete line ID and text
hash as its playback identity.

The game pack is the trust boundary. Its writer derives voice-reference and
generated-WAV bindings from their manifests. Its reader validates every outer
binding, every nested manifest, and the exact set of referenced files before
returning resolved paths. A consumer then performs generated-audio lookup with
the current story line ID and text hash. Changed text, a missing declaration,
or a modified file cannot silently reuse stale audio.

`tests/test_compatibility_flow.py` is the synthetic cross-contract fixture. It
starts with extractor-shaped story output, publishes a shared generation queue
and generated-audio manifest, assembles a complete game pack, consumes it only
through public readers, and proves that modifying the generated WAV invalidates
the pack.
