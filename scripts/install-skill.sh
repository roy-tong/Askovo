#!/usr/bin/env bash
# Install the askovo skill into a local agent skills directory.
#
#   bash scripts/install-skill.sh                 # ~/.agents/skills
#   bash scripts/install-skill.sh ~/.codex/skills
#
# Symlinks the bundled skill; it never copies, so updates follow the checkout.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO_ROOT/skills/askovo"
TARGET_ROOT="${1:-$HOME/.agents/skills}"
TARGET="$TARGET_ROOT/askovo"

if [[ ! -f "$SOURCE/SKILL.md" ]]; then
  echo "error: skill not found at $SOURCE" >&2
  exit 2
fi

mkdir -p "$TARGET_ROOT"

if [[ -L "$TARGET" ]]; then
  current="$(readlink "$TARGET")"
  if [[ "$current" == "$SOURCE" ]]; then
    echo "already installed: $TARGET -> $SOURCE"
    exit 0
  fi
  echo "replacing symlink: $TARGET -> $current"
  rm "$TARGET"
elif [[ -e "$TARGET" ]]; then
  echo "error: $TARGET exists and is not a symlink; move it away first" >&2
  exit 2
fi

ln -s "$SOURCE" "$TARGET"
echo "installed: $TARGET -> $SOURCE"
echo
echo "next:"
echo "  askovo --version"
echo "  askovo demo"
echo "  ask your agent: 使用 \$askovo，先跑 askovo \"<需求>\" 路由"
