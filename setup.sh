#!/usr/bin/env bash
#
# One-time setup after cloning your own assistant repo.
# Safe to re-run — it never overwrites anything you've filled in.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

UPSTREAM_URL="git@github.com:bigbongoai/assistant-template.git"

echo "Setting up your assistant workspace:"

if [ -e .env ]; then
  printf '  = %-10s already exists, left alone\n' ".env"
else
  cp .env.example .env
  printf '  + %-10s created — fill in R2_USER_EMAIL and the keys\n' ".env"
fi

mkdir -p tasks
chmod +x bin/r2 2>/dev/null || true

# The upstream remote is how you receive system updates from the template.
if git remote get-url upstream >/dev/null 2>&1; then
  printf '  = %-10s already configured\n' "upstream"
else
  git remote add upstream "$UPSTREAM_URL"
  printf '  + %-10s added → %s\n' "upstream" "$UPSTREAM_URL"
fi

cat <<'EOF'

Next:
  1. Fill in _personal.md  — who you are, how you like to work
  2. Fill in .env          — R2_USER_EMAIL is your R2 folder; ask Petar for keys
  3. npm install           — only if a task needs Playwright helper scripts
  4. Open Claude Code here and start a session

Day to day:
  git push               back up YOUR tasks to YOUR repo (nobody else sees them)
  git pull upstream main pick up system updates from the template
EOF
