"""GitHub Issues tracker plugin."""

from __future__ import annotations

from datetime import datetime

import httpx

from taskdog.models import NormalizedIssue
from taskdog.trackers.registry import register_tracker


@register_tracker("github")
class GitHubTracker:
    kind = "github"

    def __init__(
        self,
        *,
        api_token: str,
        owner: str,
        repo: str,
        endpoint: str = "https://api.github.com",
        **_kwargs: object,
    ):
        self._owner = owner
        self._repo = repo
        self._client = httpx.AsyncClient(
            base_url=endpoint,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    async def fetch_candidates(
        self,
        active_states: list[str],
        label: str | None = None,
    ) -> list[NormalizedIssue]:
        params: dict[str, str] = {"state": "open", "per_page": "50"}
        if label:
            params["labels"] = label

        resp = await self._client.get(
            f"/repos/{self._owner}/{self._repo}/issues",
            params=params,
        )
        resp.raise_for_status()

        issues = []
        for raw in resp.json():
            # Skip pull requests (GitHub returns them in /issues too)
            if "pull_request" in raw:
                continue
            issue = self._normalize(raw)
            if issue.state in active_states:
                issues.append(issue)
        return issues

    async def fetch_issue_by_id(self, issue_id: str) -> NormalizedIssue | None:
        resp = await self._client.get(
            f"/repos/{self._owner}/{self._repo}/issues/{issue_id}"
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._normalize(resp.json())

    async def add_comment(self, issue_id: str, body: str) -> None:
        resp = await self._client.post(
            f"/repos/{self._owner}/{self._repo}/issues/{issue_id}/comments",
            json={"body": body},
        )
        resp.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()

    def _normalize(self, raw: dict) -> NormalizedIssue:
        created = raw.get("created_at")
        return NormalizedIssue(
            id=str(raw["number"]),
            identifier=f"#{raw['number']}",
            title=raw["title"],
            description=raw.get("body") or "",
            state=raw["state"],
            labels=[label["name"] for label in raw.get("labels", [])],
            url=raw["html_url"],
            created_at=datetime.fromisoformat(created) if created else None,
            extra={"raw": raw},
        )
