#!/usr/bin/env bash
# 频繁提交小工具：scripts/commit.sh "feat: xxx" [path ...]
# 没有指定 path 时 git add -A。无改动则跳过。
set -euo pipefail

cd "$(dirname "$0")/.."

msg="${1:-}"
if [[ -z "$msg" ]]; then
  echo "usage: scripts/commit.sh <message> [path ...]" >&2
  exit 2
fi
shift || true

if [[ "$#" -gt 0 ]]; then
  git add -- "$@"
else
  git add -A
fi

if git diff --cached --quiet; then
  echo "nothing to commit"
  exit 0
fi

git commit -q -m "$msg"
echo "committed (total=$(git rev-list --count HEAD))"
