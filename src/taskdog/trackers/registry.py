"""Plugin registry — maps tracker kind strings to factory callables."""

from __future__ import annotations

from typing import Any

from taskdog.trackers.base import TrackerPlugin

_REGISTRY: dict[str, type] = {}


def register_tracker(kind: str):
    """Class decorator to register a tracker plugin."""

    def decorator(cls: type) -> type:
        _REGISTRY[kind] = cls
        return cls

    return decorator


def create_tracker(kind: str, **kwargs: Any) -> TrackerPlugin:
    """Instantiate a registered tracker plugin by kind."""
    if kind not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(f"Unknown tracker kind '{kind}'. Available: {available}")
    return _REGISTRY[kind](**kwargs)


def available_trackers() -> list[str]:
    return sorted(_REGISTRY.keys())
