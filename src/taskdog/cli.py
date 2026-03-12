"""CLI entry point — taskdog commands."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Annotated, Optional

import structlog
import typer

from taskdog.config import parse_workflow_file, TaskdogConfig
from taskdog.events import LogEventBus
from taskdog.models import NormalizedIssue
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
def start(
    workflows: Annotated[
        list[Path],
        typer.Option("--workflow", "-w", help="Path(s) to WORKFLOW.yaml files"),
    ] = [Path("WORKFLOW.yaml")],
    log_level: Annotated[str, typer.Option("--log-level", "-l")] = "INFO",
) -> None:
    """Start the daemon — poll for issues and dispatch agents."""
    _configure_logging(level=log_level)
    configs = [parse_workflow_file(w) for w in workflows]
    asyncio.run(_start_all(configs))


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


# ---------------------------------------------------------------------------
# Shared dispatch logic
# ---------------------------------------------------------------------------

async def _dispatch_issue(
    config: TaskdogConfig,
    tracker: object,
    issue: NormalizedIssue,
) -> bool:
    """Run agent on a single issue. Returns True on success."""
    log = structlog.get_logger("taskdog.dispatch")
    events = LogEventBus()
    tc = config.tracker

    log.info(
        "issue.dispatching",
        identifier=issue.identifier,
        title=issue.title,
    )

    # Transition to in-progress: remove trigger label, add in-progress label
    try:
        await tracker.set_label(issue.id, tc.label_in_progress)
        await tracker.remove_label(issue.id, tc.label)
    except Exception:
        log.warning("label.transition_failed", issue_id=issue.id, state="in-progress")

    ws_mgr = WorkspaceManager(config)
    workspace = await ws_mgr.ensure_workspace(issue)
    log.info("workspace.ready", path=workspace.path, branch=workspace.git_branch)

    prompt = render_prompt(config.prompt_template, issue, branch=workspace.git_branch)

    runner = ClaudeCliRunner(
        model=config.agent.model,
        allowed_tools=config.agent.allowed_tools or None,
        stall_timeout_ms=config.agent.stall_timeout_ms,
        env={**config.service_git_env, **config.agent_env},
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
        pr_url = await ws_mgr.push_and_create_pr(workspace, issue)
        if pr_url:
            log.info("pr.created", url=pr_url)

        # Transition: in-progress → review (PR awaiting review) or done (no PR)
        target_label = tc.label_review if pr_url else tc.label_done
        try:
            await tracker.remove_label(issue.id, tc.label_in_progress)
            await tracker.set_label(issue.id, target_label)
        except Exception:
            log.warning("label.transition_failed", issue_id=issue.id, state=target_label)

        # Post summary comment
        duration_s = result.duration_ms / 1000.0
        cost_str = f"${result.cost_usd:.4f}" if result.cost_usd is not None else "n/a"
        status = "PR created, awaiting review." if pr_url else "completed (no PR created)."
        comment_lines = [
            f"**TaskDog** {status}",
            "",
            f"- Turns: {result.num_turns}",
            f"- Duration: {duration_s:.1f}s",
            f"- Cost: {cost_str}",
        ]
        if pr_url:
            comment_lines.append(f"- PR: {pr_url}")
        try:
            await tracker.add_comment(issue.id, "\n".join(comment_lines))
        except Exception:
            log.warning("comment.failed", issue_id=issue.id)

        return True
    else:
        log.error("run.failed", issue_id=issue.id, error=result.error_message)

        # Transition to failed
        try:
            await tracker.remove_label(issue.id, tc.label_in_progress)
            await tracker.set_label(issue.id, tc.label_failed)
        except Exception:
            log.warning("label.transition_failed", issue_id=issue.id, state="failed")

        return False


# ---------------------------------------------------------------------------
# One-shot mode
# ---------------------------------------------------------------------------

async def _run_single(
    config: TaskdogConfig,
    issue_id: str,
    *,
    dry_run: bool = False,
) -> None:
    log = structlog.get_logger("taskdog.run")

    tracker_kwargs = _tracker_kwargs(config)
    tracker = create_tracker(config.tracker.kind, **tracker_kwargs)

    try:
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

        if dry_run:
            prompt = render_prompt(config.prompt_template, issue)
            typer.echo("\n--- Rendered Prompt ---")
            typer.echo(prompt)
            typer.echo("--- End Prompt ---\n")
            return

        success = await _dispatch_issue(config, tracker, issue)
        if not success:
            raise typer.Exit(1)

    finally:
        await tracker.close()


# ---------------------------------------------------------------------------
# Poll loop (daemon mode)
# ---------------------------------------------------------------------------

async def _start_all(configs: list[TaskdogConfig]) -> None:
    """Run poll loops for all workflows concurrently."""
    log = structlog.get_logger("taskdog.daemon")
    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: (shutdown.set(), log.info("shutdown.requested")))

    tasks = [
        asyncio.create_task(_poll_loop(config, shutdown))
        for config in configs
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass


async def _cleanup_stale_in_progress(
    config: TaskdogConfig,
    tracker: object,
    log: object,
) -> None:
    """On daemon startup, mark any stale in-progress issues as failed.

    A stale issue is one that still has the in-progress label from a previous
    (crashed or killed) daemon process. Since we just started, no agent is
    actively working on them.
    """
    tc = config.tracker
    try:
        stale = await tracker.fetch_candidates(
            active_states=tc.active_states,
            label=tc.label_in_progress,
        )
    except Exception:
        log.warning("stale_cleanup.fetch_failed")
        return

    for issue in stale:
        log.warning(
            "stale.in_progress",
            issue_id=issue.id,
            identifier=issue.identifier,
        )
        try:
            await tracker.remove_label(issue.id, tc.label_in_progress)
            await tracker.set_label(issue.id, tc.label_failed)
            await tracker.add_comment(
                issue.id,
                "**TaskDog**: marked as failed — agent process was interrupted "
                "(stale in-progress label cleaned up on daemon restart).",
            )
        except Exception:
            log.warning("stale_cleanup.update_failed", issue_id=issue.id)


async def _poll_loop(config: TaskdogConfig, shutdown: asyncio.Event) -> None:
    repo_id = f"{config.tracker.model_extra.get('owner', '?')}/{config.tracker.model_extra.get('repo', '?')}"
    log = structlog.get_logger("taskdog.daemon").bind(repo=repo_id)
    active: set[str] = set()
    processed: set[str] = set()
    agent_tasks: set[asyncio.Task] = set()
    max_concurrent = config.agent.max_concurrent
    semaphore = asyncio.Semaphore(max_concurrent)

    tracker_kwargs = _tracker_kwargs(config)
    tracker = create_tracker(config.tracker.kind, **tracker_kwargs)
    interval = config.polling.interval_ms / 1000.0

    log.info(
        "daemon.started",
        tracker=config.tracker.kind,
        label=config.tracker.label,
        interval_s=interval,
        max_concurrent=max_concurrent,
    )

    # Clean up any stale in-progress labels left over from a previous run
    await _cleanup_stale_in_progress(config, tracker, log)

    async def _run_agent(issue: NormalizedIssue) -> None:
        async with semaphore:
            try:
                await _dispatch_issue(config, tracker, issue)
            except Exception:
                log.exception("dispatch.error", issue_id=issue.id)
            finally:
                active.discard(issue.id)
                processed.add(issue.id)

    try:
        while not shutdown.is_set():
            # Clean up finished tasks
            done = {t for t in agent_tasks if t.done()}
            agent_tasks -= done

            try:
                candidates = await tracker.fetch_candidates(
                    active_states=config.tracker.active_states,
                    label=config.tracker.label,
                )

                skip_labels = {
                    config.tracker.label_in_progress,
                    config.tracker.label_review,
                    config.tracker.label_done,
                    config.tracker.label_failed,
                }
                new = [
                    c for c in candidates
                    if c.id not in active
                    and c.id not in processed
                    and not skip_labels.intersection(c.labels)
                ]

                log.info(
                    "poll.tick",
                    candidates=len(candidates),
                    new=len(new),
                    active=len(active),
                    processed=len(processed),
                )

                for issue in new:
                    if shutdown.is_set():
                        break
                    active.add(issue.id)
                    task = asyncio.create_task(
                        _run_agent(issue),
                        name=f"agent-{issue.id}",
                    )
                    agent_tasks.add(task)

            except Exception:
                log.exception("poll.error")

            try:
                await asyncio.wait_for(shutdown.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass

    finally:
        # Wait for running agents to finish
        if agent_tasks:
            log.info("daemon.waiting_for_agents", count=len(agent_tasks))
            await asyncio.gather(*agent_tasks, return_exceptions=True)
        log.info("daemon.stopping", active=len(active))
        await tracker.close()
        log.info("daemon.stopped")


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
