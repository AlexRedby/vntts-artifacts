"""Durable publication primitives with deliberately distinct group policies."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path


def _ensure_parent(path: Path, directory_mode: int | None) -> None:
    if directory_mode is None:
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True, mode=directory_mode)


@contextmanager
def atomic_output_path(path, *, directory_mode=None):
    """Yield a sibling temporary path and replace one destination on success."""
    destination = Path(path)
    _ensure_parent(destination, directory_mode)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.stem}.",
        suffix=f".tmp{destination.suffix}",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        yield temporary
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def staged_bytes(path, content, *, directory_mode=None):
    """Yield a durable sibling file without publishing it."""
    destination = Path(path)
    _ensure_parent(destination, directory_mode)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.stem}.",
        suffix=f".tmp{destination.suffix}",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def staged_json(path, value, *, ensure_ascii=False, indent=2, sort_keys=False, directory_mode=None):
    rendered = json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        indent=indent,
        sort_keys=sort_keys,
    )
    with staged_bytes(
        path,
        (rendered + "\n").encode("utf-8"),
        directory_mode=directory_mode,
    ) as temporary:
        yield temporary


def atomic_write_bytes(path, content, *, directory_mode=None):
    with staged_bytes(path, content, directory_mode=directory_mode) as temporary:
        os.replace(temporary, path)
    return Path(path)


def atomic_write_text(path, content, *, encoding="utf-8", directory_mode=None):
    return atomic_write_bytes(
        path,
        content.encode(encoding),
        directory_mode=directory_mode,
    )


def atomic_write_json(
    path,
    value,
    *,
    ensure_ascii=False,
    indent=2,
    sort_keys=False,
    directory_mode=None,
):
    rendered = json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        indent=indent,
        sort_keys=sort_keys,
    )
    return atomic_write_text(
        path,
        rendered + "\n",
        directory_mode=directory_mode,
    )


def replace_file_group(files: Mapping[Path, bytes], *, directory_mode=None):
    """Replace an ordered file group and restore every prior file on failure."""
    destinations = tuple(Path(path) for path in files)
    if not destinations:
        raise ValueError("at least one file is required")
    if len(set(destinations)) != len(destinations):
        raise ValueError("file destinations must be unique")

    staged = {}
    backups = {}
    published = []
    try:
        for destination, content in zip(destinations, files.values(), strict=True):
            with staged_bytes(
                destination,
                content,
                directory_mode=directory_mode,
            ) as temporary:
                persisted = temporary.with_name(temporary.name + ".staged")
                os.replace(temporary, persisted)
                staged[destination] = persisted

        for destination in destinations:
            if destination.exists():
                descriptor, backup_name = tempfile.mkstemp(
                    dir=destination.parent,
                    prefix=f".{destination.name}.backup.",
                    suffix=".tmp",
                )
                os.close(descriptor)
                backup = Path(backup_name)
                backup.unlink()
                os.replace(destination, backup)
                backups[destination] = backup
            os.replace(staged[destination], destination)
            published.append(destination)
    except BaseException:
        for destination in reversed(destinations):
            backup = backups.get(destination)
            if destination in published:
                destination.unlink(missing_ok=True)
            if backup is not None and backup.exists():
                os.replace(backup, destination)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        for backup in backups.values():
            backup.unlink(missing_ok=True)
    return destinations


@contextmanager
def create_new_output_group(*paths, directory_mode=None):
    """Stage and publish a group only when all destinations are new."""
    destinations = tuple(Path(path) for path in paths)
    if not destinations or len(set(destinations)) != len(destinations):
        raise ValueError("output destinations must be unique and non-empty")
    if any(destination.exists() for destination in destinations):
        raise FileExistsError("create-new output group requires new destinations")

    temporaries = []
    published = []
    try:
        for destination in destinations:
            _ensure_parent(destination, directory_mode)
            descriptor, temporary_name = tempfile.mkstemp(
                dir=destination.parent,
                prefix=f".{destination.stem}.",
                suffix=f".tmp{destination.suffix}",
            )
            os.close(descriptor)
            temporaries.append(Path(temporary_name))
        yield tuple(temporaries)
        for temporary, destination in zip(temporaries, destinations, strict=True):
            os.replace(temporary, destination)
            published.append(destination)
    except BaseException:
        for destination in published:
            destination.unlink(missing_ok=True)
        raise
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
