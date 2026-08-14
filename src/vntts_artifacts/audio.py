"""Shared helpers for the PCM WAV format used by generated VNTTS audio."""

from __future__ import annotations

import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from vntts_artifacts.atomic_io import atomic_output_path

PCM16_MONO_WAV_FORMAT = "wav-pcm16-mono"


class Pcm16MonoWavError(ValueError):
    """Raised when a WAV file does not satisfy the generated-audio contract."""


@dataclass(frozen=True)
class Pcm16MonoWavInfo:
    sample_rate: int
    sample_count: int
    duration_seconds: float
    peak: float


def read_pcm16_mono_wav(path):
    """Read an uncompressed mono 16-bit WAV and return samples plus metadata."""
    path = Path(path)
    try:
        with wave.open(str(path), "rb") as source:
            if source.getcomptype() != "NONE":
                raise Pcm16MonoWavError("compressed WAV is not supported")
            if source.getnchannels() != 1 or source.getsampwidth() != 2:
                raise Pcm16MonoWavError("expected mono 16-bit PCM WAV")
            sample_rate = source.getframerate()
            sample_count = source.getnframes()
            content = source.readframes(sample_count)
    except Pcm16MonoWavError:
        raise
    except (OSError, EOFError, wave.Error) as error:
        raise Pcm16MonoWavError(f"unreadable WAV: {error}") from error

    samples = array("h")
    samples.frombytes(content)
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) != sample_count:
        raise Pcm16MonoWavError("WAV sample data is incomplete")
    if sample_rate < 1:
        raise Pcm16MonoWavError("WAV sample rate must be positive")

    peak = max((abs(value) for value in samples), default=0) / 32768
    info = Pcm16MonoWavInfo(
        sample_rate=sample_rate,
        sample_count=sample_count,
        duration_seconds=sample_count / sample_rate,
        peak=peak,
    )
    return samples, info


def probe_pcm16_mono_wav(path):
    """Validate a generated-audio WAV and return its technical metadata."""
    _samples, info = read_pcm16_mono_wav(path)
    return info


def write_pcm16_wav(path, samples, sample_rate):
    """Atomically publish float samples as an uncompressed mono 16-bit WAV."""
    try:
        import numpy as np
    except ImportError as error:
        raise RuntimeError(
            "write_pcm16_wav requires the vntts-artifacts[audio] extra"
        ) from error

    destination = Path(path)
    values = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = np.round(values * 32767.0).astype("<i2")
    with atomic_output_path(destination) as temporary:
        with wave.open(str(temporary), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(int(sample_rate))
            output.writeframes(pcm.tobytes())
    return destination
