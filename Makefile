WORKFLOW ?= WORKFLOW.taskdog.yaml
ISSUE    ?= 1
LOG      ?= INFO

export GITHUB_TOKEN ?= $(shell gh auth token)

DC = docker compose
RUN = $(DC) run --rm taskdog

.PHONY: build run run-issue dry-run validate trackers shell logs clean

build:
	$(DC) build

run:
	$(RUN) python -m taskdog start -w /app/WORKFLOW.taskdog.yaml -w /app/WORKFLOW.landing.yaml --log-level $(LOG)

run-issue:
	$(RUN) python -m taskdog run --issue $(ISSUE) -w /app/$(WORKFLOW) --log-level $(LOG)

dry-run:
	$(RUN) python -m taskdog run --issue $(ISSUE) -w /app/$(WORKFLOW) --dry-run --log-level $(LOG)

validate:
	$(RUN) python -m taskdog validate -w /app/$(WORKFLOW)

trackers:
	$(RUN) python -m taskdog trackers

shell:
	$(RUN) bash

logs:
	$(DC) logs -f

clean:
	$(DC) down -v
	rm -rf ~/.taskdog/workspaces
