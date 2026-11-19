#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -d .git ]]; then
  echo "already a git repo"
  exit 0
fi
git init -b main
git add -A
git -c user.email=agent@local -c user.name=agent commit -m "Initial smoke fixture"
echo "bootstrapped $(pwd)"
