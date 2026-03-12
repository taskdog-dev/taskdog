"""Agent runner — executes Claude against an issue in a workspace.

Uses Claude Code CLI (`claude -p`) as the execution backend.
Implements an AgentRunner protocol so we can swap to Agent SDK later.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

import structlog

from taskdog.models import AgentResult, NormalizedIssue, WorkspaceInfo

logger = structlog.get_logger(__name__)


class AgentRunner(Protocol):
    """Protocol for agent execution backends."""

    async def run(
        self,
        *,
        issue: NormalizedIssue,
        workspace: WorkspaceInfo,
        prompt: str,
        max_turns: int = 20,
        session_id: str | None = None,
    ) -> AgentResult: ...


class ClaudeCliRunner:
    """Runs Claude Code CLI as a subprocess."""

    def __init__(
        self,
        *,
        model: str = "sonnet",
        allowed_tools: list[str] | None = None,
        stall_timeout_ms: int = 600_000,
        env: dict[str, str] | None = None,
    ):
        self._model = model
        self._allowed_tools = allowed_tools or []
        self._stall_timeout = stall_timeout_ms / 1000.0
        self._env = env

    async def run(
        self,
        *,
        issue: NormalizedIssue,
        workspace: WorkspaceInfo,
        prompt: str,
        max_turns: int = 20,
        session_id: str | None = None,
    ) -> AgentResult:
        cmd = self._build_command(
            prompt=prompt,
            max_turns=max_turns,
            session_id=session_id,
        )

        log = logger.bind(
            issue_id=issue.id,
            identifier=issue.identifier,
            workspace=workspace.path,
        )
        log.info("agent.starting", model=self._model)

        try:
            import os

            env = {**os.environ, **(self._env or {})}
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=workspace.path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._stall_timeout,
            )

            output = stdout.decode()
            result = self._parse_output(output, issue.id)

            if proc.returncode != 0 and not result.success:
                result.error_message = result.error_message or stderr.decode()

            log.info(
                "agent.completed",
                success=result.success,
                session_id=result.session_id,
            )
            return result

        except asyncio.TimeoutError:
            log.error("agent.timeout", timeout_s=self._stall_timeout)
            proc.kill()  # type: ignore[possibly-undefined]
            return AgentResult(
                issue_id=issue.id,
                success=False,
                error_message=f"Agent timed out after {self._stall_timeout}s",
            )
        except Exception as exc:
            log.exception("agent.error")
            return AgentResult(
                issue_id=issue.id,
                success=False,
                error_message=str(exc),
            )

    def _build_command(
        self,
        *,
        prompt: str,
        max_turns: int,
        session_id: str | None,
    ) -> list[str]:
        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "json",
            "--model", self._model,
            "--max-turns", str(max_turns),
        ]

        if session_id:
            cmd.extend(["--resume", session_id])

        if self._allowed_tools:
            for tool in self._allowed_tools:
                cmd.extend(["--allowedTools", tool])

        return cmd

    def _parse_output(self, output: str, issue_id: str) -> AgentResult:
        """Parse Claude CLI JSON output into AgentResult."""
        if not output.strip():
            return AgentResult(
                issue_id=issue_id,
                success=False,
                error_message="Empty output from Claude CLI",
            )

        try:
            data = json.loads(output)
            return AgentResult(
                issue_id=issue_id,
                success=not data.get("is_error", False),
                session_id=data.get("session_id"),
                error_message=data.get("result") if data.get("is_error") else None,
                num_turns=data.get("num_turns", 0),
                duration_ms=data.get("duration_ms", 0),
                cost_usd=data.get("cost_usd"),
                result_text=data.get("result"),
            )
        except json.JSONDecodeError:
            # If not JSON, treat the raw text as the result
            return AgentResult(
                issue_id=issue_id,
                success=True,
                result_text=output.strip(),
            )
