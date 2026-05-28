"""Factory helpers for selecting TTS backends.

The render pipeline depends on the provider-neutral ``TTSBackend`` protocol.
This module is the only place that should translate configuration names into
concrete provider implementations.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from .base import BulkDownloadVoiceCatalogBackend, TTSBackend, VoiceCatalogBackend

if TYPE_CHECKING:
    from .cache import CachedTTSBackend

DEFAULT_BACKEND = "piper"
IMPLEMENTED_BACKENDS = (DEFAULT_BACKEND,)
RESERVED_BACKENDS = ("kokoro-onnx",)
KNOWN_BACKENDS = IMPLEMENTED_BACKENDS + RESERVED_BACKENDS


class BackendNotImplementedError(RuntimeError):
    """Raised when a configured backend is known but not implemented yet."""


def normalize_backend_name(name: str | None) -> str:
    """Normalize a backend name from config or CLI input."""
    if not isinstance(name, str):
        return DEFAULT_BACKEND
    return (name or DEFAULT_BACKEND).strip().lower()


def create_tts_backend(
    backend_name: str | None = None,
    *,
    voices_dir: Path | None = None,
    max_text_length: int = 500,
) -> TTSBackend:
    """Create an uncached TTS backend for the requested provider."""
    backend = normalize_backend_name(backend_name)
    if backend == "piper":
        from drinkingfountain import tts as tts_package

        return tts_package.PiperTTSBackend(
            voices_dir=voices_dir, max_text_length=max_text_length
        )
    if backend in RESERVED_BACKENDS:
        raise BackendNotImplementedError(
            f"TTS backend '{backend}' is recognized but not implemented yet."
        )
    raise ValueError(f"Unknown TTS backend '{backend}'.")


def create_cached_tts_backend(
    backend_name: str | None = None,
    *,
    voices_dir: Path | None = None,
    cache_dir: Path | None = None,
    max_text_length: int = 500,
) -> CachedTTSBackend:
    """Create a cached TTS backend for render/test paths."""
    from drinkingfountain import tts as tts_package

    backend = create_tts_backend(
        backend_name, voices_dir=voices_dir, max_text_length=max_text_length
    )
    return tts_package.CachedTTSBackend(backend, cache_dir=cache_dir)


def create_voice_catalog_backend(
    backend_name: str | None = None,
    *,
    voices_dir: Path | None = None,
    max_text_length: int = 500,
) -> VoiceCatalogBackend:
    """Create a backend that supports downloadable voice catalog operations."""
    backend = create_tts_backend(
        backend_name, voices_dir=voices_dir, max_text_length=max_text_length
    )
    if not hasattr(backend, "list_available_voices"):
        raise RuntimeError(
            f"TTS backend '{normalize_backend_name(backend_name)}' does not support "
            "downloadable voice catalog operations."
        )
    return cast(VoiceCatalogBackend, backend)


def create_bulk_voice_catalog_backend(
    backend_name: str | None = None,
    *,
    voices_dir: Path | None = None,
    max_text_length: int = 500,
) -> BulkDownloadVoiceCatalogBackend:
    """Create a backend that supports bulk downloadable voice operations."""
    backend = create_tts_backend(
        backend_name, voices_dir=voices_dir, max_text_length=max_text_length
    )
    if not (
        hasattr(backend, "list_available_voices")
        and hasattr(backend, "download_voices_by_language")
    ):
        raise RuntimeError(
            f"TTS backend '{normalize_backend_name(backend_name)}' does not support "
            "bulk voice downloads."
        )
    return cast(BulkDownloadVoiceCatalogBackend, backend)
