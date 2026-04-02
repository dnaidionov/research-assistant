#!/bin/zsh

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
JOBS_ROOT=$(python3 -c "import sys; from pathlib import Path; sys.path.insert(0, '$SCRIPT_DIR'); from _repo_paths import resolve_jobs_root; print(resolve_jobs_root(repo_root=Path('$SCRIPT_DIR').resolve().parents[0]))")

ls "$JOBS_ROOT"
