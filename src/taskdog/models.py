"""Core domain models — tracker-agnostic, shared across all components."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NormalizedIssue(BaseModel):
    """Tracker-agnostic issue representation.

    Every tracker plugin maps its native issue type to this model.
    """

    id: str
    identifier: str  # Human-readable key, e.g. "PROJ-123" or "#42"
    title: str
    description: str = ""
    state: str
    labels: list[str] = Field(default_factory=list)
    url: str = ""
    created_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class WorkspaceInfo(BaseModel):
    """Tracks a workspace directory and its lifecycle metadata."""

    issue_id: str
    issue_identifier: str
    path: str
    created_at: datetime
    git_branch: str | None = None


class AgentResult(BaseModel):
    """Outcome of a single agent run."""

    issue_id: str
    success: bool
    session_id: str | None = None
    error_message: str | None = None
    num_turns: int = 0
    duration_ms: int = 0
    cost_usd: float | None = None
    result_text: str | None = None
