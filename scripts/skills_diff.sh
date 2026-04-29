#!/usr/bin/env bash
set -euo pipefail

if command -v scholar-vault >/dev/null 2>&1; then
  exec scholar-vault skills diff "$@"
fi

exec /Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault skills diff "$@"
