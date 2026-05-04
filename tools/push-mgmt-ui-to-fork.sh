#!/usr/bin/env bash
#
# Push the monorepo's kura-management-ui/ subtree to the spnettec fork.
#
# After this:
#   - spnettec/kura-management-ui:yofc/main   ← reflects this monorepo's web2 source
#   - spnettec/kura-management-ui:develop     ← left alone (continues to mirror upstream)
#
# Re-runnable. Each run amends yofc/main with whatever the monorepo currently has.
# Build artifacts (target/, lib/, gwt-unitCache/) are not tracked, so they don't ship.
#
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

REMOTE="yofc-mgmt-ui"
PREFIX="kura-management-ui"
BRANCH="yofc/main"
TMP_BRANCH="mgmt-ui-export-$$"

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
    echo "Remote '$REMOTE' not found. Add it with:"
    echo "  git remote add $REMOTE https://github.com/spnettec/kura-management-ui.git"
    exit 1
fi

if [ ! -d "$PREFIX" ]; then
    echo "Subtree path '$PREFIX/' not in working tree."
    exit 1
fi

if ! git ls-tree -d --name-only HEAD "$PREFIX" >/dev/null 2>&1; then
    echo "Subtree path '$PREFIX/' not in HEAD commit."
    echo "Commit your changes first, then re-run."
    exit 1
fi

echo "Splitting $PREFIX/ into temporary branch $TMP_BRANCH..."
git subtree split --prefix="$PREFIX" -b "$TMP_BRANCH"

echo "Pushing to $REMOTE:$BRANCH (force)..."
git push "$REMOTE" "$TMP_BRANCH:$BRANCH" --force

git branch -D "$TMP_BRANCH"

echo
echo "Done. https://github.com/spnettec/kura-management-ui/tree/$BRANCH should now reflect the"
echo "monorepo's $PREFIX/ subtree."
