#!/usr/bin/env bash
#
# Mechanical setup after cloning your own assistant repo.
# Safe to re-run — it never overwrites anything you've filled in.
# The rest of setup is conversational: open Claude Code and say "set me up".

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Where system updates come from. Usually the `upstream` remote already exists
# (renamed when you cloned), so this stays empty and we leave it alone. An org
# overlay can set template_repo to point somewhere else.
UPSTREAM_URL=$(python3 - <<'PY' 2>/dev/null || true
import json, pathlib
cfg = {}
for name in ("assistant.config.json", "assistant.config.local.json"):
    p = pathlib.Path(name)
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text()))
        except ValueError:
            pass
print(cfg.get("template_repo") or "")
PY
)

echo "Setting up your assistant workspace:"

if [ -e .env ]; then
  printf '  = %-10s already exists, left alone\n' ".env"
else
  cp .env.example .env
  printf '  + %-10s created\n' ".env"
fi

mkdir -p tasks
chmod +x bin/r2 2>/dev/null || true

# The upstream remote is how you receive system updates from the template.
# Skipped for people outside the org (they may not be able to read the template)
# and for local-only workspaces. Set NO_UPSTREAM=1 for those.
if git remote get-url upstream >/dev/null 2>&1; then
  printf '  = %-10s already configured\n' "upstream"
elif [ "${NO_UPSTREAM:-0}" = "1" ] || [ -z "$UPSTREAM_URL" ]; then
  printf '  - %-10s none set (system updates will be handed over manually)\n' "upstream"
else
  git remote add upstream "$UPSTREAM_URL" 2>/dev/null \
    && printf '  + %-10s added → %s\n' "upstream" "$UPSTREAM_URL" \
    || printf '  ! %-10s could not add (not a git repo?)\n' "upstream"
fi

# Your history and the template's diverge by design — you commit tasks, the
# template doesn't. Without this, `git pull upstream main` aborts asking how to
# reconcile. Merge (not rebase) keeps your task commits intact.
git config pull.rebase false 2>/dev/null || true

# A friendly name for the Ask AI proxy, so deliverables live at pa.lcl:1111
# instead of a bare loopback address. The server binds to 127.0.0.1, so this is
# purely a name lookup - nothing is exposed to the network. Needs sudo, so we
# tell the user rather than doing it for them.
if grep -qE '^[^#]*[[:space:]]pa\.lcl([[:space:]]|$)' /etc/hosts 2>/dev/null; then
  printf '  = %-10s pa.lcl already maps to localhost\n' "hosts"
else
  printf '  - %-10s pa.lcl not in /etc/hosts. To reach your pages at http://pa.lcl:1111 run:\n' "hosts"
  printf '                 echo "127.0.0.1 pa.lcl" | sudo tee -a /etc/hosts\n'
fi

echo
if grep -q 'SETUP-REQUIRED' _personal.md 2>/dev/null; then
  cat <<'EOF'
Next step — open Claude Code in this folder and say:

    set me up

It will ask a few questions (who you are, whether you want to see the technical
side or have it handled for you), then finish configuring everything including
your R2 keys.
EOF
else
  cat <<'EOF'
Already configured. Day to day:

    git push                 back up your tasks to your own repo
    git pull upstream main   pick up system updates from the template
EOF
fi
