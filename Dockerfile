FROM python:3.13-slim

# System deps for git operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Claude Code CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Install watchfiles for live reload
RUN pip install --no-cache-dir watchfiles

# Working directory
WORKDIR /app

# Install Python deps (cached layer — only rebuilds when pyproject.toml changes)
COPY pyproject.toml .
RUN pip install --no-cache-dir typer httpx pydantic jinja2 structlog pyyaml

# Source code is mounted as volume at /app/src
ENV PYTHONPATH=/app/src

CMD ["watchfiles", "--filter", "python", "python -m taskdog start -w /app/WORKFLOW.yaml", "/app/src"]
