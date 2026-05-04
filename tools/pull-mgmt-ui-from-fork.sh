#!/usr/bin/env bash
#
# Pull changes from the spnettec fork's yofc/main branch into the monorepo's
# kura-management-ui/ subtree.
#
# Use case: someone else pushed a commit to the fork that you want here.
# Squashed merge — keeps monorepo history flat.
#
# Conflicts are surfaced normally; you resolve and `git commit` to finish.
#
set -euo pipefail

REMOTE="yofc-mgmt-ui"
BRANCH="yofc/main"
PREFIX="kura-management-ui"

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
    echo "Remote '$REMOTE' not found."
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "Working tree dirty. Commit or stash first."
    exit 1
fi

git fetch "$REMOTE" "$BRANCH"
git subtree pull --prefix="$PREFIX" "$REMOTE" "$BRANCH" --squash
