"""One converter per provider: raw bundle in, canonical records out."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from normalization.bundle import Bundle
    from normalization.output import Output

# Provider keys, as bundles name them (session.json "provider") -> converter package.
PROVIDERS = {"prismhr": "prismhr", "isolved": "isolved", "ukg-ready": "ukg_ready"}


def converter(provider: str) -> Callable[..., Output]:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; expected one of: {', '.join(PROVIDERS)}")
    return import_module(f"{__name__}.{PROVIDERS[provider]}").normalize


def normalize(bundle: Bundle, as_of: date | None = None, mapping_files: list[Path] | None = None) -> Output:
    """Normalize a bundle with its own provider's converter, resolving UNMAPPED values from mapping files (A-65)."""
    from normalization.mappings import Mappings, active, annotate

    mappings = Mappings.load(mapping_files or [], bundle.provider)
    with active(mappings):
        output = converter(bundle.provider)(bundle, as_of)
    annotate(output, mappings)
    return output
