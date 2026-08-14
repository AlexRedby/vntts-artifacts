"""Compatibility imports for the shared durable-file dependency."""

from durable_file import (
    atomic_output_path,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    create_new_output_group,
)

atomic_output_group = create_new_output_group

__all__ = [
    "atomic_output_group",
    "atomic_output_path",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
]
