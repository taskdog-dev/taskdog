"""Event bus — decoupled event emission for observability.

Today: logs via structlog. Future: webhooks, gRPC stream to control plane.
"""

from __future__ import annotations

from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)


class EventBus(Protocol):
    """Protocol for event emission. Implementations decide where events go."""

    async def emit(self, event_type: str, data: dict[str, Any]) -> None: ...


class LogEventBus:
    """Emits events as structured log entries."""

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        logger.info(event_type, **data)
