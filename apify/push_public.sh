#!/usr/bin/env bash
# Push apify/ as the public Store Actor, without the owner's secrets.
#
# The private demo Actor (vladb/domovoy) is pushed with plain `apify push` and keeps the secret environment
# variables from .actor/actor.json. The public Actor must not have them: every run of a public Actor gets its
# environment variables, so other users would spend our Featherless and OpenAI keys and carry our Notion token.
# This script pushes a temporary copy whose only environment variable is DOMOVOY_STORE_SUFFIX (not a secret),
# with a different name and title. The suffix gives the public Actor its own named stores: a limited-permission
# Actor may not open the stores the demo Actor created in the same account.
#
# Usage, from anywhere: apify/push_public.sh   (needs `apify login`; PUBLIC_NAME overrides the Actor name)
set -euo pipefail

PUBLIC_NAME="${PUBLIC_NAME:-prague-flat-rentals}"
PUBLIC_TITLE="${PUBLIC_TITLE:-DOMOVOY Prague Flat Rentals}"

here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

rsync -a \
  --exclude .venv --exclude storage --exclude tests --exclude e2e --exclude research \
  --exclude __pycache__ --exclude .pytest_cache --exclude push_public.sh \
  "$here/" "$tmp/"

python3 - "$tmp/.actor/actor.json" "$PUBLIC_NAME" "$PUBLIC_TITLE" <<'EOF'
import json
import sys

path, name, title = sys.argv[1:4]
with open(path) as f:
    actor = json.load(f)
actor["environmentVariables"] = {"DOMOVOY_STORE_SUFFIX": "-public"}
actor["name"] = name
actor["title"] = title
with open(path, "w") as f:
    json.dump(actor, f, indent=2)
    f.write("\n")
EOF

if grep -q '"@' "$tmp/.actor/actor.json"; then
  echo "refusing to push: the copy still references an Apify secret" >&2
  exit 1
fi

cd "$tmp"
apify push
