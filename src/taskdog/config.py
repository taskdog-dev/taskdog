"""Configuration — WORKFLOW.yaml parser with Pydantic models."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def _resolve_env_vars(value: Any) -> Any:
    """Recursively resolve $VAR references in config values."""
    if isinstance(value, str) and value.startswith("$"):
        var_name = value[1:]
        resolved = os.environ.get(var_name)
        if resolved is None:
            raise ValueError(
                f"Environment variable '{var_name}' not set "
                f"(referenced as '${var_name}' in config)"
            )
        return resolved
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


class TrackerConfig(BaseModel):
    kind: str
    api_key: str = ""
    label: str = "taskdog"  # Only pick up issues with this label
    label_in_progress: str = "taskdog:in-progress"
    label_review: str = "taskdog:review"
    label_done: str = "taskdog:done"
    label_failed: str = "taskdog:failed"
    stale_timeout_ms: int = 3_600_000  # 1 hour — in-progress labels older than this are cleaned up on startup
    active_states: list[str] = Field(default_factory=lambda: ["open"])
    terminal_states: list[str] = Field(default_factory=lambda: ["closed"])

    model_config = {"extra": "allow"}


class PollingConfig(BaseModel):
    interval_ms: int = 30_000


class WorkspaceConfig(BaseModel):
    root: str = "~/.taskdog/workspaces"
    git_clone_url: str | None = None
    git_default_branch: str = "main"
    branch_pattern: str = "{issue_id}-{slug}"  # {issue_id}, {slug}, {identifier}
    branch_prefix: str = "taskdog"  # prepended as prefix/
    service_name: str | None = None   # git user.name for service identity commits
    service_email: str | None = None  # git user.email for service identity commits


class HooksConfig(BaseModel):
    after_create: str | None = None
    before_run: str | None = None
    after_run: str | None = None
    timeout_ms: int = 60_000


class AgentConfig(BaseModel):
    max_concurrent: int = 1
    max_turns: int = 20
    stall_timeout_ms: int = 600_000  # 10 minutes
    allowed_tools: list[str] = Field(default_factory=list)
    model: str = "sonnet"
    env: dict[str, str] = Field(default_factory=dict)


class TaskdogConfig(BaseModel):
    """Root configuration parsed from WORKFLOW.yaml front matter."""

    tracker: TrackerConfig
    polling: PollingConfig = Field(default_factory=PollingConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    prompt_template: str = ""

    @property
    def agent_env(self) -> dict[str, str]:
        return {k: _resolve_env_vars(v) for k, v in self.agent.env.items()}

    @property
    def service_git_env(self) -> dict[str, str]:
        """Git author/committer env vars for the service identity, if configured."""
        env: dict[str, str] = {}
        name = self.workspace.service_name
        email = self.workspace.service_email
        if name:
            env["GIT_AUTHOR_NAME"] = name
            env["GIT_COMMITTER_NAME"] = name
        if email:
            env["GIT_AUTHOR_EMAIL"] = email
            env["GIT_COMMITTER_EMAIL"] = email
        return env


_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def parse_workflow_file(path: str | Path) -> TaskdogConfig:
    """Parse a WORKFLOW.yaml file: YAML front matter + Jinja2 prompt body."""
    text = Path(path).read_text(encoding="utf-8")

    front_matter: dict[str, Any] = {}
    prompt_body = text

    match = _FRONT_MATTER_RE.match(text)
    if match:
        yaml_str = match.group(1)
        prompt_body = match.group(2).strip()
        raw = yaml.safe_load(yaml_str) or {}
        front_matter = _resolve_env_vars(raw)

    return TaskdogConfig(prompt_template=prompt_body, **front_matter)
