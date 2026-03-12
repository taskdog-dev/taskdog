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

# Install Claude Code CLI + GitHub CLI (for PR creation by agent)
RUN npm install -g @anthropic-ai/claude-code
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

# Install watchfiles for live reload
RUN pip install --no-cache-dir watchfiles

# Working directory
WORKDIR /app

# Python deps (cached — only rebuilds when deps change)
RUN pip install --no-cache-dir typer httpx pydantic jinja2 structlog pyyaml

# Source code is mounted as volume at runtime
ENV PYTHONPATH=/app/src


CMD ["watchfiles", "--filter", "python", "python -m taskdog start -w /app/WORKFLOW.yaml", "/app/src"]
