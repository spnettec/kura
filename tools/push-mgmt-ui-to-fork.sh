#!/usr/bin/env bash
#
# Push the monorepo's current kura-management-ui/ tree snapshot to the spnettec fork.
#
# Strategy: snapshot push (not subtree split). Each invocation creates exactly one
# commit on yofc/main containing the current subtree tree-of-files, with the
# previous yofc/main tip as parent. Fast-forward only — no history rewrite.
#
# Why not subtree split: walking 8000+ commits of monorepo history every time costs
# ~3 minutes. We don't need per-commit history on the fork — git blame, log, and
# upstream PRs all work via the monorepo or via the snapshot's commit message.
#
# After this:
#   spnettec/kura-management-ui:yofc/main   ← linear chain of "snapshot from monorepo @ <sha>"
#   spnettec/kura-management-ui:develop     ← still mirrors upstream (untouched)
#
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

REMOTE="yofc-mgmt-ui"
PREFIX="kura-management-ui"
BRANCH="yofc/main"

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
    echo "Remote '$REMOTE' not found. Add it with:"
    echo "  git remote add $REMOTE https://github.com/spnettec/kura-management-ui.git"
    exit 1
fi

if ! git rev-parse --verify "HEAD:$PREFIX" >/dev/null 2>&1; then
    echo "Path '$PREFIX/' not in HEAD commit. Commit your changes first."
    exit 1
fi

echo "Fetching $REMOTE/$BRANCH for parent reference..."
git fetch "$REMOTE" "$BRANCH" 2>/dev/null || echo "(branch doesn't exist on remote yet; will create)"

PARENT_ARGS=()
if git rev-parse --verify --quiet "$REMOTE/$BRANCH" >/dev/null; then
    PARENT_ARGS=(-p "$REMOTE/$BRANCH")
fi

SUBTREE_TREE=$(git rev-parse "HEAD:$PREFIX")
MONOREPO_SHA=$(git rev-parse HEAD)
MONOREPO_SHORT=$(git rev-parse --short HEAD)
BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)

MSG=$(cat <<EOF
Snapshot from monorepo $BRANCH_NAME @ $MONOREPO_SHORT

Synced subtree $PREFIX/ from heyoulin/kura
  source-commit: $MONOREPO_SHA
  source-branch: $BRANCH_NAME
EOF
)

NEW_COMMIT=$(printf '%s' "$MSG" | git commit-tree "$SUBTREE_TREE" "${PARENT_ARGS[@]}")

echo "Pushing snapshot commit $NEW_COMMIT to $REMOTE:$BRANCH..."
git push "$REMOTE" "$NEW_COMMIT:refs/heads/$BRANCH"

echo
echo "Done. https://github.com/spnettec/kura-management-ui/tree/$BRANCH"
echo "Latest snapshot: $NEW_COMMIT (from monorepo $MONOREPO_SHORT)"
