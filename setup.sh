#!/usr/bin/env bash
#
# One-time setup after cloning. Safe to re-run — it never overwrites your files.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

copy_if_missing() {
  if [ -e "$2" ]; then
    printf '  = %-18s already exists, left alone\n' "$2"
  else
    cp "$1" "$2"
    printf '  + %-18s created from %s\n' "$2" "$1"
  fi
}

echo "Setting up your assistant workspace:"
copy_if_missing _personal.md.example _personal.md
copy_if_missing _tasks.md.example    _tasks.md
copy_if_missing .env.example         .env
mkdir -p tasks
chmod +x bin/r2 2>/dev/null || true

cat <<'EOF'

Next:
  1. Fill in _personal.md  — who you are, how you like to work
  2. Fill in .env          — R2_USER_EMAIL is your folder; ask Petar for the keys
  3. npm install           — only if a task needs Playwright helper scripts
  4. Open Claude Code here and start a session

Your tasks/, _personal.md, _tasks.md and .env are gitignored — they stay on
your machine. `git pull` brings system updates without touching them.
EOF
