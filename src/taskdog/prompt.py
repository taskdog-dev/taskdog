"""Prompt template rendering with Jinja2."""

from __future__ import annotations

import jinja2

from taskdog.models import NormalizedIssue

_ENV = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)


def render_prompt(
    template_str: str,
    issue: NormalizedIssue,
    attempt: int | None = None,
) -> str:
    """Render the WORKFLOW.yaml prompt template with issue context."""
    template = _ENV.from_string(template_str)
    return template.render(
        issue=issue,
        attempt=attempt,
    )
