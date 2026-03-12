"""TrackerPlugin protocol — the interface all tracker plugins must satisfy."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from taskdog.models import NormalizedIssue


@runtime_checkable
class TrackerPlugin(Protocol):
    """Structural subtyping protocol for issue tracker plugins."""

    @property
    def kind(self) -> str:
        """Unique tracker identifier, e.g. 'github', 'jira'."""
        ...

    async def fetch_candidates(
        self,
        active_states: list[str],
        label: str | None = None,
    ) -> list[NormalizedIssue]:
        """Return issues in active states, optionally filtered by label."""
        ...

    async def fetch_issue_by_id(self, issue_id: str) -> NormalizedIssue | None:
        """Fetch a single issue by its tracker-native ID."""
        ...

    async def add_comment(self, issue_id: str, body: str) -> None:
        """Post a comment on the issue."""
        ...

    async def close(self) -> None:
        """Cleanup: close HTTP clients, connections, etc."""
        ...
