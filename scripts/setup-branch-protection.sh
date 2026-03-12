#!/usr/bin/env bash
# Set up branch protection rules for taskdog-dev repos.
# Requires: gh CLI authenticated with a token that has `repo` scope.
# The repos must be public or the account must have GitHub Pro/Team/Enterprise
# for branch protection to be available.
#
# Usage: ./scripts/setup-branch-protection.sh

set -euo pipefail

protect() {
  local owner="$1"
  local repo="$2"
  local branch="$3"

  echo "Configuring branch protection: ${owner}/${repo}@${branch}"

  gh api \
    --method PUT \
    "repos/${owner}/${repo}/branches/${branch}/protection" \
    --header "Accept: application/vnd.github+json" \
    --input - <<EOF
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "dismissal_restrictions": {},
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": false
}
EOF

  echo "  done."
}

protect taskdog-dev taskdog master
protect taskdog-dev landing main

echo "Branch protection rules applied."
