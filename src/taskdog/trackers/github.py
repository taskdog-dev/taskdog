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
        api_token = api_token.strip()
        self._client = httpx.AsyncClient(
            base_url=endpoint,
            headers={
                "Authorization": f"token {api_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    async def fetch_candidates(
        self,
        active_states: list[str],
        label: str | None = None,
        exclude_labels: list[str] | None = None,
    ) -> list[NormalizedIssue]:
        params: dict[str, str] = {"state": "open", "per_page": "50"}
        if label:
            params["labels"] = label

        resp = await self._client.get(
            f"/repos/{self._owner}/{self._repo}/issues",
            params=params,
        )
        resp.raise_for_status()

        excluded = set(exclude_labels or [])
        issues = []
        for raw in resp.json():
            # Skip pull requests (GitHub returns them in /issues too)
            if "pull_request" in raw:
                continue
            issue = self._normalize(raw)
            if issue.state not in active_states:
                continue
            if excluded and excluded.intersection(issue.labels):
                continue
            issues.append(issue)
        return issues

    async def fetch_issue_by_id(self, issue_id: str) -> NormalizedIssue | None:
        url = f"/repos/{self._owner}/{self._repo}/issues/{issue_id}"
        resp = await self._client.get(url)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            import structlog
            structlog.get_logger().error(
                "github.api_error",
                status=resp.status_code,
                url=url,
                body=resp.text[:500],
            )
        resp.raise_for_status()
        return self._normalize(resp.json())

    async def set_label(self, issue_id: str, label: str) -> None:
        resp = await self._client.post(
            f"/repos/{self._owner}/{self._repo}/issues/{issue_id}/labels",
            json={"labels": [label]},
        )
        resp.raise_for_status()

    async def remove_label(self, issue_id: str, label: str) -> None:
        import urllib.parse
        encoded = urllib.parse.quote(label, safe="")
        resp = await self._client.delete(
            f"/repos/{self._owner}/{self._repo}/issues/{issue_id}/labels/{encoded}",
        )
        if resp.status_code == 404:
            return  # Label not present — no-op
        resp.raise_for_status()

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
        updated = raw.get("updated_at")
        return NormalizedIssue(
            id=str(raw["number"]),
            identifier=f"#{raw['number']}",
            title=raw["title"],
            description=raw.get("body") or "",
            state=raw["state"],
            labels=[label["name"] for label in raw.get("labels", [])],
            url=raw["html_url"],
            created_at=datetime.fromisoformat(created) if created else None,
            updated_at=datetime.fromisoformat(updated) if updated else None,
            extra={"raw": raw},
        )
