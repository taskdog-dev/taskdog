#!/usr/bin/env python3
"""Set up branch protection rules for taskdog-dev repos.

Requires a GitHub token with admin access to the repositories.
For private repos, GitHub Pro or higher is required.

Usage:
    GITHUB_TOKEN=ghp_xxx python scripts/setup_branch_protection.py
"""

from __future__ import annotations

import os
import sys

import httpx


REPOS = [
    {"owner": "taskdog-dev", "repo": "taskdog", "branch": "master"},
    {"owner": "taskdog-dev", "repo": "landing", "branch": "main"},
]

PROTECTION_RULES = {
    # Require PR reviews before merging
    "required_pull_request_reviews": {
        "dismiss_stale_reviews": True,
        "require_code_owner_reviews": False,
        "required_approving_review_count": 1,
    },
    # No required status checks yet (enable once CI is set up)
    "required_status_checks": None,
    # Do not enforce rules on admins
    "enforce_admins": False,
    # No branch restrictions (any user can push via PR)
    "restrictions": None,
    # Prevent force pushes
    "allow_force_pushes": False,
    # Prevent branch deletion
    "allow_deletions": False,
}


def apply_branch_protection(
    client: httpx.Client,
    owner: str,
    repo: str,
    branch: str,
) -> None:
    url = f"/repos/{owner}/{repo}/branches/{branch}/protection"
    resp = client.put(url, json=PROTECTION_RULES)
    if resp.status_code == 403:
        print(
            f"  ERROR: 403 Forbidden — branch protection requires GitHub Pro "
            f"for private repos. Upgrade the plan or make the repo public.",
            file=sys.stderr,
        )
        sys.exit(1)
    resp.raise_for_status()
    print(f"  OK — branch protection applied to {owner}/{repo}:{branch}")


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    client = httpx.Client(
        base_url="https://api.github.com",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )

    print("Applying branch protection rules...")
    with client:
        for entry in REPOS:
            print(f"  {entry['owner']}/{entry['repo']} ({entry['branch']})...")
            apply_branch_protection(
                client,
                owner=entry["owner"],
                repo=entry["repo"],
                branch=entry["branch"],
            )

    print("\nDone. Branch protection rules applied:")
    print("  - Require pull request before merging")
    print("  - Require 1 approval")
    print("  - Dismiss stale reviews on new pushes")
    print("  - No force pushes")
    print("  - No branch deletions")


if __name__ == "__main__":
    main()
