#!/bin/zsh

set -euo pipefail

NAME=${1:-}

if [ -z "$NAME" ]; then
  echo "Usage: create_job.sh job-name"
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
JOBS_ROOT=$(python3 -c "import sys; from pathlib import Path; sys.path.insert(0, '$SCRIPT_DIR'); from _repo_paths import resolve_jobs_root; print(resolve_jobs_root(repo_root=Path('$SCRIPT_DIR').resolve().parents[0]))")
TEMPLATE_DIR=$(cd "$SCRIPT_DIR/../templates/job-template" && pwd)

mkdir -p "$JOBS_ROOT"
cp -R "$TEMPLATE_DIR" "$JOBS_ROOT/$NAME"
cd "$JOBS_ROOT/$NAME"
git init

echo "Created job: $NAME"
