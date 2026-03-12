# 🐕 TaskDog

### The sheepdog for your engineering backlog.

TaskDog is an autonomous AI engineer that turns backlog tasks into pull requests.

```
  🐑 fix login bug        ━━▶              ━━▶  🐾 PR ✅
  🐑 update dependencies  ━━▶  🐕 TaskDog  ━━▶  🐾 PR ✅
  🐑 add input validation ━━▶              ━━▶  🐾 PR ✅
```

Label an issue, TaskDog picks it up, analyzes the repo, writes the code, and opens a PR for review. The sheepdog for your engineering ~~herd~~ backlog.

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
cp .env.example .env
# Edit .env with your tokens

docker compose up        # daemon with live reload
docker compose run taskdog taskdog run --issue 42   # one-shot
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

agent:
  model: "sonnet"
  max_turns: 20
---

You are working on issue **{{ issue.identifier }}**: "{{ issue.title }}".

{{ issue.description }}

Implement the changes and create a clean commit.
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

## License

Proprietary. All rights reserved.
