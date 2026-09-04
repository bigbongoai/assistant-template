#!/usr/bin/env python3
"""Write credentials into .env without them passing through the assistant.

The setup flow used to have Claude read `storage.credentials` from the org
overlay, or the keys someone pasted into the form, and write them into `.env`
itself. That put live secrets into the model's context by design, and no
"never echo a key" rule can undo that - the leak has already happened by the
time the rule applies.

So the model never touches values. It runs this script; the script reads the
overlay and `answers.json` directly and edits `.env`. Everything it prints is
key names and counts, never a value.

    python3 setup/apply-secrets.py            # apply
    python3 setup/apply-secrets.py --check    # report only, change nothing

Exit codes: 0 applied or nothing to do, 1 something was wrong.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ENV = ROOT / ".env"
ANSWERS = HERE / "answers.json"

# Form field -> .env key. The form is the only other place a secret can come
# from, and it reaches us through a file, not through a conversation.
FROM_ANSWERS = {
    "r2_user_email": "R2_USER_EMAIL",
    "r2_access_key_id": "R2_ACCESS_KEY_ID",
    "r2_secret_key": "R2_SECRET_KEY",
    "r2_endpoint": "R2_ENDPOINT",
    "r2_bucket": "R2_BUCKET_PRIVATE",
    "r2_public_base": "R2_PUBLIC_BASE",
}


def load_config() -> dict:
    """assistant.config.json overlaid with assistant.config.local.json."""
    cfg: dict = {}
    for name in ("assistant.config.json", "assistant.config.local.json"):
        path = ROOT / name
        if not path.exists():
            continue
        try:
            cfg.update(json.loads(path.read_text()))
        except ValueError:
            print(f"apply-secrets: {name} is not valid JSON", file=sys.stderr)
            return {}
    return cfg


def gather() -> dict[str, str]:
    """Every key/value we intend to write. Values are never printed."""
    out: dict[str, str] = {}

    storage = (load_config().get("storage") or {})
    for key, value in (storage.get("credentials") or {}).items():
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    if storage.get("bucket"):
        out.setdefault("R2_BUCKET_PRIVATE", str(storage["bucket"]))
        out.setdefault("R2_BUCKET_PUBLIC", str(storage["bucket"]))
    if storage.get("share_ttl_seconds"):
        out.setdefault("R2_SHARE_TTL", str(storage["share_ttl_seconds"]))

    # Anything the person typed into the form wins over the org defaults: they
    # chose "my own storage" precisely to not use ours.
    if ANSWERS.exists():
        try:
            answers = json.loads(ANSWERS.read_text())
        except ValueError:
            print("apply-secrets: answers.json is not valid JSON", file=sys.stderr)
            answers = {}
        for field, env_key in FROM_ANSWERS.items():
            value = (answers.get(field) or "").strip()
            if value:
                out[env_key] = value
        if out.get("R2_BUCKET_PRIVATE") and not answers.get("r2_public_base"):
            out.setdefault("R2_BUCKET_PUBLIC", out["R2_BUCKET_PRIVATE"])

    return out


def apply(values: dict[str, str]) -> None:
    """Replace each key in place, or append it. Comments and order survive."""
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    remaining = dict(values)

    for i, line in enumerate(lines):
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f'{key}="{remaining.pop(key)}"'

    for key, value in remaining.items():
        lines.append(f'{key}="{value}"')

    ENV.write_text("\n".join(lines).rstrip() + "\n")
    ENV.chmod(0o600)


def main() -> int:
    check_only = "--check" in sys.argv
    values = gather()

    if not values:
        print("apply-secrets: nothing to write - no org credentials and no keys in the form")
        return 0

    print(f"apply-secrets: {len(values)} key(s) {'would be' if check_only else ''} written to .env")
    for key in sorted(values):
        print(f"  {key}")

    if check_only:
        return 0

    apply(values)
    print("apply-secrets: done, .env is chmod 600. No value was printed or logged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
