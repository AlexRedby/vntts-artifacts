"""Stable content identity helpers used by VNTTS artifact contracts."""

import hashlib


def text_sha256(text):
    if not isinstance(text, str):
        raise TypeError("Artifact text must be a string")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
