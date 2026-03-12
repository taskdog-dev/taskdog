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


def _sanitize(identifier: str) -> str:
    """Replace non-alphanumeric chars with underscores."""
    return re.sub(r"[^a-zA-Z0-9]", "_", identifier)


class WorkspaceManager:
    def __init__(self, config: TaskdogConfig):
        self._config = config
        self._root = Path(config.workspace.root).expanduser().resolve()

    async def ensure_workspace(self, issue: NormalizedIssue) -> WorkspaceInfo:
        """Create or reuse a workspace for the given issue."""
        ws_name = _sanitize(issue.identifier)
        ws_path = (self._root / ws_name).resolve()

        # Path safety — must be under root
        if not str(ws_path).startswith(str(self._root)):
            raise ValueError(f"Workspace path escapes root: {ws_path}")

        is_new = not ws_path.exists()
        if is_new:
            ws_path.mkdir(parents=True, exist_ok=True)
            logger.info("workspace.created", path=str(ws_path))

            if self._config.workspace.git_clone_url:
                await self._git_clone(ws_path)

            await self._run_hook(self._config.hooks.after_create, ws_path)

        branch_name = f"taskdog/{ws_name}"

        info = WorkspaceInfo(
            issue_id=issue.id,
            issue_identifier=issue.identifier,
            path=str(ws_path),
            created_at=datetime.now(timezone.utc),
            git_branch=branch_name,
        )

        # Create git branch if this is a git repo
        if is_new and (ws_path / ".git").exists():
            await self._run_cmd(
                ["git", "checkout", "-b", branch_name],
                cwd=ws_path,
            )

        return info

    async def remove_workspace(self, workspace: WorkspaceInfo) -> None:
        """Remove a workspace directory."""
        ws_path = Path(workspace.path)
        if not ws_path.exists():
            return
        shutil.rmtree(str(ws_path), ignore_errors=True)
        logger.info("workspace.removed", path=str(ws_path))

    async def _git_clone(self, ws_path: Path) -> None:
        url = self._config.workspace.git_clone_url
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
            # Move contents from tmp into ws_path
            for item in tmp.iterdir():
                dest = ws_path / item.name
                shutil.move(str(item), str(dest))
        finally:
            if tmp.exists():
                shutil.rmtree(str(tmp), ignore_errors=True)

        logger.info("workspace.git_cloned", path=str(ws_path), url=url)

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
            raise RuntimeError(
                f"Command {cmd} failed (exit {proc.returncode}): {stderr.decode()}"
            )
        return stdout.decode()
