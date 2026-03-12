# 🐕 TaskDog

### The sheepdog for your engineering backlog.
### Give it a task. Get a PR.

TaskDog is an autonomous AI engineer that turns backlog tasks into pull requests.

```
  🐑 fix login bug        ━━▶              ━━▶  🐾 PR ✅
  🐑 update dependencies  ━━▶  🐕 TaskDog  ━━▶  🐾 PR ✅
  🐑 add input validation ━━▶              ━━▶  🐾 PR ✅
```

Label an issue, TaskDog picks it up, analyzes the repo, writes the code, and opens a PR for review.

## How it works

```
Label issue "taskdog"  →  TaskDog clones repo  →  AI writes the fix  →  PR opened for review
```

1. Connect your issue tracker (GitHub Issues, Jira, Linear, Todoist)
2. Label an issue (e.g. `taskdog`)
3. TaskDog creates an isolated workspace, clones the repo
4. AI agent analyzes the codebase and implements the change
5. A pull request appears in your repo

Engineers stay in control. TaskDog just does the work.

## Issue lifecycle

TaskDog tracks issue state via labels:

```
  taskdog                →  issue picked up by TaskDog
  taskdog:in-progress    →  agent is working on it
  taskdog:review         →  PR created, awaiting review
  taskdog:done           →  PR merged, issue closed
  taskdog:failed         →  agent failed or PR closed without merge
```

To retry a failed issue, remove `taskdog:failed` and add `taskdog`.

## Quick start

```bash
pip install -e .

# Configure your workflow
cp WORKFLOW.yaml.example WORKFLOW.yaml
# Edit WORKFLOW.yaml with your tracker and repo settings

# Validate config
taskdog validate

# Run on a single issue
taskdog run --issue 42

# Run as a daemon (polls for new issues)
taskdog start
```

## Docker

```bash
# Build once
make build

# Run daemon (polls all configured repos)
make run

# Run on a single issue
make run-issue ISSUE=42

# Preview rendered prompt
make dry-run ISSUE=42

# Other commands
make validate
make shell
make clean
```

## Configuration

TaskDog is configured via `WORKFLOW.yaml` — YAML front matter for settings, Jinja2 template for the agent prompt:

```yaml
---
tracker:
  kind: "github"
  api_key: $GITHUB_TOKEN
  owner: "myorg"
  repo: "myrepo"
  label: "taskdog"

workspace:
  root: "~/.taskdog/workspaces"
  git_clone_url: "https://github.com/myorg/myrepo.git"
  git_default_branch: "main"
  branch_prefix: "taskdog"        # branch: taskdog/1-fix-login-bug
  branch_pattern: "{issue_id}-{slug}"

agent:
  model: "sonnet"
  max_turns: 20
  max_concurrent: 3
  allowed_tools:
    - "Read"
    - "Write"
    - "Edit"
    - "Bash"
    - "Glob"
    - "Grep"
---

You are working on issue **{{ issue.identifier }}**: "{{ issue.title }}".

{{ issue.description }}

You are on branch `{{ branch }}`. Commit your changes to this branch.
```

### Multi-repo support

Poll multiple repos concurrently with multiple `-w` flags:

```bash
taskdog start -w WORKFLOW.backend.yaml -w WORKFLOW.frontend.yaml
```

## Tracker plugins

```bash
taskdog trackers   # list available plugins
```

- **github** — GitHub Issues (REST API)
- **memory** — In-memory store for testing

Coming soon: Jira, Linear, Todoist.

## Architecture

TaskDog is designed as a **data plane engine** — it receives config, polls trackers, dispatches agents, and reports events. No user management, no auth, no UI. This makes it deployable anywhere:

```
Config (WORKFLOW.yaml or API)
        │
  ┌─────▼─────────────────────────┐
  │  Tracker  │ Workspace │ Agent │
  │  Plugins  │ Manager   │ Runner│
  │           │           │       │
  │  Orchestrator (poll + dispatch)│
  │                               │
  │  Event Bus (logs / webhooks)  │
  └───────────────────────────────┘
```

- **Locally** as a CLI daemon
- **In Docker** with mounted credentials
- **In a customer's VPC** with customer-managed encryption keys
- **As a SaaS data plane** receiving config from a control plane

## Secure by design

- Agent runs in your environment — code never leaves your infrastructure
- Per-issue workspace isolation
- All changes come as PRs for human review
- No data sent to any control plane (local mode)
- Tokens masked in all log output

## License

Proprietary. All rights reserved.
