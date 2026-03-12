"""Workspace manager — per-issue directory isolation."""

from __future__ import annotations

import asyncio
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import structlog

from taskdog.config import TaskdogConfig
from taskdog.models import NormalizedIssue, WorkspaceInfo

logger = structlog.get_logger(__name__)


def _sanitize(text: str) -> str:
    """Replace non-alphanumeric chars with hyphens, collapse, strip."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text)
    return s.strip("-").lower()


def _slugify(title: str, max_len: int = 40) -> str:
    """Turn an issue title into a short URL-safe slug."""
    slug = _sanitize(title)
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    return slug


def _branch_name(prefix: str, pattern: str, issue: NormalizedIssue) -> str:
    """Build branch name from prefix, pattern, and issue."""
    name = pattern.format(
        issue_id=issue.id,
        identifier=_sanitize(issue.identifier),
        slug=_slugify(issue.title),
    )
    if prefix:
        return f"{prefix}/{name}"
    return name


class WorkspaceManager:
    def __init__(self, config: TaskdogConfig):
        self._config = config
        self._root = Path(config.workspace.root).expanduser().resolve()

    async def ensure_workspace(self, issue: NormalizedIssue) -> WorkspaceInfo:
        """Create or reuse a workspace for the given issue."""
        ws_dir = f"issue-{issue.id}"
        ws_path = (self._root / ws_dir).resolve()

        # Path safety — must be under root
        if not str(ws_path).startswith(str(self._root)):
            raise ValueError(f"Workspace path escapes root: {ws_path}")

        # Always start fresh — remove stale workspace from previous runs
        if ws_path.exists():
            shutil.rmtree(str(ws_path), ignore_errors=True)
            logger.info("workspace.cleaned", path=str(ws_path))

        ws_path.mkdir(parents=True, exist_ok=True)
        logger.info("workspace.created", path=str(ws_path))

        if self._config.workspace.git_clone_url:
            await self._git_clone(ws_path)

        await self._run_hook(self._config.hooks.after_create, ws_path)

        branch = _branch_name(
            self._config.workspace.branch_prefix,
            self._config.workspace.branch_pattern,
            issue,
        )

        # Ensure authenticated remote
        if (ws_path / ".git").exists():
            await self._ensure_auth_remote(ws_path)
            await self._run_cmd(
                ["git", "checkout", "-b", branch],
                cwd=ws_path,
            )

        return WorkspaceInfo(
            issue_id=issue.id,
            issue_identifier=issue.identifier,
            path=str(ws_path),
            created_at=datetime.now(timezone.utc),
            git_branch=branch,
        )

    async def _current_branch(self, ws_path: Path) -> str | None:
        """Get the current git branch name."""
        try:
            out = await self._run_cmd(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=ws_path,
            )
            branch = out.strip()
            return branch if branch and branch != "HEAD" else None
        except RuntimeError:
            return None

    async def has_new_commits(self, workspace: WorkspaceInfo) -> bool:
        """Check if workspace branch has commits ahead of the default branch."""
        ws_path = Path(workspace.path)
        if not (ws_path / ".git").exists():
            return False
        base = self._config.workspace.git_default_branch
        try:
            out = await self._run_cmd(
                ["git", "rev-list", "--count", f"{base}..HEAD"],
                cwd=ws_path,
            )
            return int(out.strip()) > 0
        except RuntimeError:
            return False

    async def push_and_create_pr(
        self,
        workspace: WorkspaceInfo,
        issue: NormalizedIssue,
    ) -> str | None:
        """Push branch and create a PR. Returns PR URL or None."""
        ws_path = Path(workspace.path)
        base = self._config.workspace.git_default_branch

        # Detect current branch; fall back to expected branch
        branch = await self._current_branch(ws_path)
        if not branch or branch == base:
            # Agent may have switched branches — switch back to expected
            if workspace.git_branch:
                try:
                    await self._run_cmd(
                        ["git", "checkout", workspace.git_branch],
                        cwd=ws_path,
                    )
                    branch = workspace.git_branch
                except RuntimeError:
                    logger.warning("post_run.no_branch", workspace=workspace.path)
                    return None
            else:
                logger.warning("post_run.no_branch", workspace=workspace.path)
                return None

        if not await self.has_new_commits(workspace):
            logger.info("post_run.no_commits", workspace=workspace.path)
            return None

        # Push branch
        logger.info("post_run.pushing", branch=branch)
        await self._run_cmd(
            ["git", "push", "-u", "origin", branch],
            cwd=ws_path,
            timeout=120,
        )

        # Create PR via GitHub API
        import os
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            logger.warning("post_run.no_token", msg="Cannot create PR without GITHUB_TOKEN")
            return None

        clone_url = self._config.workspace.git_clone_url or ""
        # Extract owner/repo from URL
        # https://github.com/owner/repo.git or git@github.com:owner/repo.git
        import re
        match = re.search(r"github\.com[/:]([^/]+)/([^/.]+)", clone_url)
        if not match:
            logger.warning("post_run.cannot_parse_repo", url=clone_url)
            return None

        owner, repo = match.group(1), match.group(2)

        import httpx
        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30.0,
        ) as client:
            resp = await client.post(
                f"/repos/{owner}/{repo}/pulls",
                json={
                    "title": f"{issue.identifier}: {issue.title}",
                    "head": branch,
                    "base": base,
                    "body": (
                        f"Resolves {issue.identifier}\n\n"
                        f"Automated by [TaskDog](https://taskdog.dev)"
                    ),
                },
            )
            if resp.status_code == 201:
                pr_url = resp.json()["html_url"]
                logger.info("post_run.pr_created", url=pr_url)
                return pr_url
            else:
                logger.error(
                    "post_run.pr_failed",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                return None

    async def remove_workspace(self, workspace: WorkspaceInfo) -> None:
        """Remove a workspace directory."""
        ws_path = Path(workspace.path)
        if not ws_path.exists():
            return
        shutil.rmtree(str(ws_path), ignore_errors=True)
        logger.info("workspace.removed", path=str(ws_path))

    def _auth_url(self) -> str | None:
        """Build authenticated clone URL if GITHUB_TOKEN is available."""
        import os

        url = self._config.workspace.git_clone_url
        if not url:
            return None
        token = os.environ.get("GITHUB_TOKEN")
        if token and url.startswith("https://github.com/"):
            return url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
        return url

    async def _ensure_auth_remote(self, ws_path: Path) -> None:
        """Set the remote URL with auth token. Adds remote if missing."""
        url = self._auth_url()
        if not url:
            return
        try:
            await self._run_cmd(
                ["git", "remote", "set-url", "origin", url],
                cwd=ws_path,
            )
        except RuntimeError:
            # Remote doesn't exist — add it
            await self._run_cmd(
                ["git", "remote", "add", "origin", url],
                cwd=ws_path,
            )

    async def _git_clone(self, ws_path: Path) -> None:
        url = self._auth_url()
        branch = self._config.workspace.git_default_branch
        if not url:
            return

        # Clone into a temp dir then move contents, since ws_path already exists
        tmp = ws_path.parent / f".{ws_path.name}_clone"
        try:
            await self._run_cmd(
                ["git", "clone", "--branch", branch, "--single-branch", url, str(tmp)],
                timeout=300,
            )
            for item in tmp.iterdir():
                dest = ws_path / item.name
                shutil.move(str(item), str(dest))
        finally:
            if tmp.exists():
                shutil.rmtree(str(tmp), ignore_errors=True)

        logger.info("workspace.git_cloned", path=str(ws_path), url=self._config.workspace.git_clone_url)

    async def _run_hook(self, script: str | None, cwd: Path) -> None:
        if not script:
            return
        timeout = self._config.hooks.timeout_ms / 1000.0
        proc = await asyncio.create_subprocess_shell(
            script,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Hook timed out after {timeout}s")
        if proc.returncode != 0:
            raise RuntimeError(f"Hook failed (exit {proc.returncode}): {stderr.decode()}")

    @staticmethod
    def _mask_secrets(text: str) -> str:
        """Mask tokens and credentials in log output."""
        import re
        # Mask GitHub tokens (ghp_, gho_, ghs_, ghu_, github_pat_)
        text = re.sub(r'(ghp_|gho_|ghs_|ghu_|github_pat_)[A-Za-z0-9_]+', r'\1***', text)
        # Mask x-access-token in URLs
        text = re.sub(r'x-access-token:[^@]+@', 'x-access-token:***@', text)
        return text

    async def _run_cmd(
        self,
        cmd: list[str],
        cwd: Path | None = None,
        timeout: float = 60,
    ) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            safe_cmd = [self._mask_secrets(c) for c in cmd]
            safe_err = self._mask_secrets(stderr.decode())
            raise RuntimeError(
                f"Command {safe_cmd} failed (exit {proc.returncode}): {safe_err}"
            )
        return stdout.decode()
