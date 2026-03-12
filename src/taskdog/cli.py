"""CLI entry point — taskdog commands."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Annotated, Optional

import structlog
import typer

from taskdog.config import parse_workflow_file, TaskdogConfig
from taskdog.events import LogEventBus
from taskdog.prompt import render_prompt
from taskdog.runner import ClaudeCliRunner
from taskdog.workspace import WorkspaceManager

# Import tracker modules to trigger @register_tracker decorators
import taskdog.trackers.github  # noqa: F401
import taskdog.trackers.memory  # noqa: F401

from taskdog.trackers.registry import available_trackers, create_tracker

app = typer.Typer(
    name="taskdog",
    help="Autonomous coding agent orchestrator powered by Claude.",
)


def _configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    processors: list[structlog.types.Processor] = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
    ]
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        cache_logger_on_first_use=False,
    )


@app.command()
def run(
    issue_id: Annotated[
        str,
        typer.Option("--issue", "-i", help="Issue ID to work on"),
    ],
    workflow: Annotated[
        Path,
        typer.Option("--workflow", "-w", help="Path to WORKFLOW.yaml"),
    ] = Path("WORKFLOW.yaml"),
    log_level: Annotated[str, typer.Option("--log-level", "-l")] = "INFO",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show rendered prompt without running agent"),
    ] = False,
) -> None:
    """Run a single agent session for one issue, then exit."""
    _configure_logging(level=log_level)
    config = parse_workflow_file(workflow)
    asyncio.run(_run_single(config, issue_id, dry_run=dry_run))


@app.command()
def validate(
    workflow: Annotated[
        Path,
        typer.Option("--workflow", "-w", help="Path to WORKFLOW.yaml"),
    ] = Path("WORKFLOW.yaml"),
) -> None:
    """Validate a WORKFLOW.yaml configuration file."""
    try:
        config = parse_workflow_file(workflow)
        typer.echo(f"Tracker:         {config.tracker.kind}")
        typer.echo(f"Label filter:    {config.tracker.label}")
        typer.echo(f"Active states:   {config.tracker.active_states}")
        typer.echo(f"Terminal states:  {config.tracker.terminal_states}")
        typer.echo(f"Polling:         {config.polling.interval_ms}ms")
        typer.echo(f"Workspace root:  {config.workspace.root}")
        typer.echo(f"Max concurrent:  {config.agent.max_concurrent}")
        typer.echo(f"Model:           {config.agent.model}")
        typer.echo(f"\nPrompt template: {len(config.prompt_template)} chars")
        typer.echo("\nConfiguration is valid.")
    except Exception as exc:
        typer.echo(f"Validation failed: {exc}", err=True)
        raise typer.Exit(1)


@app.command(name="trackers")
def list_trackers() -> None:
    """List available tracker plugins."""
    for name in available_trackers():
        typer.echo(f"  - {name}")


async def _run_single(
    config: TaskdogConfig,
    issue_id: str,
    *,
    dry_run: bool = False,
) -> None:
    log = structlog.get_logger("taskdog.run")
    events = LogEventBus()

    # Create tracker
    tracker_kwargs = _tracker_kwargs(config)
    tracker = create_tracker(config.tracker.kind, **tracker_kwargs)

    try:
        # Fetch issue
        issue = await tracker.fetch_issue_by_id(issue_id)
        if issue is None:
            log.error("Issue not found", issue_id=issue_id)
            raise typer.Exit(1)

        log.info(
            "issue.found",
            identifier=issue.identifier,
            title=issue.title,
            state=issue.state,
        )

        # Render prompt
        prompt = render_prompt(config.prompt_template, issue)

        if dry_run:
            typer.echo("\n--- Rendered Prompt ---")
            typer.echo(prompt)
            typer.echo("--- End Prompt ---\n")
            return

        # Ensure workspace
        ws_mgr = WorkspaceManager(config)
        workspace = await ws_mgr.ensure_workspace(issue)
        log.info("workspace.ready", path=workspace.path)

        # Run agent
        runner = ClaudeCliRunner(
            model=config.agent.model,
            allowed_tools=config.agent.allowed_tools or None,
            stall_timeout_ms=config.agent.stall_timeout_ms,
            env=config.agent_env,
        )

        result = await runner.run(
            issue=issue,
            workspace=workspace,
            prompt=prompt,
            max_turns=config.agent.max_turns,
        )

        await events.emit("agent.finished", {
            "issue_id": issue.id,
            "identifier": issue.identifier,
            "success": result.success,
            "session_id": result.session_id,
            "num_turns": result.num_turns,
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
        })

        if result.success:
            log.info("run.success", issue_id=issue.id)
            if result.result_text:
                typer.echo(f"\n{result.result_text}")
        else:
            log.error("run.failed", error=result.error_message)
            raise typer.Exit(1)

    finally:
        await tracker.close()


def _tracker_kwargs(config: TaskdogConfig) -> dict:
    """Extract tracker constructor kwargs from config."""
    # Get all extra fields from tracker config
    kwargs = {}
    for key, value in config.tracker.model_extra.items():
        kwargs[key] = value

    # Map api_key to api_token (most plugins expect api_token)
    if config.tracker.api_key:
        kwargs["api_token"] = config.tracker.api_key

    return kwargs
