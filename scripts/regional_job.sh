#!/usr/bin/env bash
# Regional check job for a self-hosted runner that lives in a separate PRIVATE repository.
#
# Why a private repository: a runner registered on this public repository could be targeted by workflows
# added in pull requests from forks. The private helper repository's workflow clones this repository with
# a fine-grained token (Contents: read and write on this repository only), re-checks the region-restricted
# channels from the runner's location, and pushes only state/regional/<label>.json back to main.
#
#   bash scripts/regional_job.sh <label>          # run from the root of a fresh clone of this repository
#
# Needs git and Python 3.12 or newer (set PYTHON to a specific interpreter if needed). See docs/REGIONAL_CHECKS.md.
set -euo pipefail

label="${1:-${REGIONAL_LABEL:-}}"
selectors="${REGIONAL_SELECTORS:-GEO_RESTRICTED,UNKNOWN,TIMEOUT,restricted}"
python="${PYTHON:-python3}"
if ! printf '%s' "$label" | grep -Eq '^[a-z0-9][a-z0-9-]{1,31}$'; then
  echo "usage: bash scripts/regional_job.sh <label>   (label: a-z, 0-9, '-', e.g. asia-pk)" >&2
  exit 2
fi

cd "$(git rev-parse --show-toplevel)"
if ! "$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "Python 3.12 or newer is required (found: $("$python" --version 2>&1)). Set PYTHON=/path/to/python3.12." >&2
  exit 1
fi

if [ ! -x .venv-regional/bin/python ]; then
  "$python" -m venv .venv-regional
fi
.venv-regional/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt

.venv-regional/bin/python scripts/verify.py --no-community --location-label "$label" --only "$selectors"

file="state/regional/${label}.json"
if [ ! -f "$file" ] || [ -z "$(git status --porcelain -- "$file")" ]; then
  echo "No new regional results to publish."
  exit 0
fi

git config user.name "${GIT_AUTHOR_NAME:-Shahrukh Khalid}"
git config user.email "${GIT_AUTHOR_EMAIL:-90670731+Shahrukhalid@users.noreply.github.com}"
cp "$file" "/tmp/regional-${label}.json"

# The daily workflows also commit to main, so retry on a moving branch: reset to the latest main, re-apply
# our single file and push again.
for attempt in 1 2 3 4 5; do
  git fetch --quiet origin main
  git reset --quiet --hard origin/main
  mkdir -p state/regional
  cp "/tmp/regional-${label}.json" "$file"
  git add -- "$file"
  if git diff --cached --quiet; then
    echo "Results already up to date on main."
    exit 0
  fi
  git commit --quiet -m "Regional verification results (${label})"
  if git push --quiet origin HEAD:main; then
    echo "Published ${file} (attempt ${attempt})."
    exit 0
  fi
  sleep $((attempt * 15))
done
echo "Could not push the regional results after 5 attempts." >&2
exit 1
