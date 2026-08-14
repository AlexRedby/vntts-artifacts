# Durable File

Dependency-free Python helpers for publishing local files without exposing
partial content. The API keeps materially different policies explicit:

- `atomic_output_path` and `atomic_write_*` replace one destination.
- `replace_file_group` replaces an ordered group and restores every previous
  destination if publication fails.
- `create_new_output_group` publishes a group only when every destination is
  new and removes partial publication on failure.
- `staged_bytes` creates a durable sibling file without publishing it.
- `sha256_file` calculates a streaming checksum.

Callers can pass `directory_mode=0o700` when newly created application-data
directories require private permissions. Existing directory permissions are
never changed.

```bash
PYTHONPATH=src python -m unittest discover -s tests
```
