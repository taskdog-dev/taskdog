"""In-memory tracker — for testing without external API keys."""

from __future__ import annotations

from datetime import datetime, timezone

from taskdog.models import NormalizedIssue
from taskdog.trackers.registry import register_tracker


@register_tracker("memory")
class MemoryTracker:
    kind = "memory"

    def __init__(self, **_kwargs: object):
        self._issues: dict[str, NormalizedIssue] = {}
        self._comments: dict[str, list[str]] = {}

    def add_issue(
        self,
        *,
        id: str,
        title: str,
        description: str = "",
        state: str = "open",
        labels: list[str] | None = None,
    ) -> NormalizedIssue:
        """Add an issue to the in-memory store."""
        issue = NormalizedIssue(
            id=id,
            identifier=f"MEM-{id}",
            title=title,
            description=description,
            state=state,
            labels=labels or [],
            url=f"memory://issues/{id}",
            created_at=datetime.now(timezone.utc),
        )
        self._issues[id] = issue
        return issue

    async def fetch_candidates(
        self,
        active_states: list[str],
        label: str | None = None,
        exclude_labels: list[str] | None = None,
    ) -> list[NormalizedIssue]:
        excluded = set(exclude_labels or [])
        results = []
        for issue in self._issues.values():
            if issue.state not in active_states:
                continue
            if label and label not in issue.labels:
                continue
            if excluded and excluded.intersection(issue.labels):
                continue
            results.append(issue)
        return results

    async def fetch_issue_by_id(self, issue_id: str) -> NormalizedIssue | None:
        return self._issues.get(issue_id)

    async def set_label(self, issue_id: str, label: str) -> None:
        issue = self._issues.get(issue_id)
        if issue and label not in issue.labels:
            self._issues[issue_id] = issue.model_copy(
                update={"labels": issue.labels + [label]}
            )

    async def remove_label(self, issue_id: str, label: str) -> None:
        issue = self._issues.get(issue_id)
        if issue:
            self._issues[issue_id] = issue.model_copy(
                update={"labels": [lbl for lbl in issue.labels if lbl != label]}
            )

    async def add_comment(self, issue_id: str, body: str) -> None:
        self._comments.setdefault(issue_id, []).append(body)

    async def close(self) -> None:
        pass
