#!/usr/bin/env bash
#
# Show new commits in upstream eclipse-kura/kura-management-ui that touch
# bundles/org.eclipse.kura.web2/ since the last reviewed marker.
#
# Read-only. Does NOT cherry-pick. The whole point: you read the list, decide
# manually which (if any) to backport.
#
# Backport workflow per chosen commit:
#   git cherry-pick <sha>
#   # path-aligned (B.2 layout) — applies cleanly into kura-management-ui/bundles/...
#
# To skip a commit forever (won't show again):
#   echo <sha> >> .upstream-mgmt-ui-rejected
#
# After reviewing all listed commits:
#   git rev-parse upstream-mgmt-ui/develop > .upstream-mgmt-ui-last-reviewed
#
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

REMOTE="upstream-mgmt-ui"
BRANCH="develop"
SUBPATH="bundles/org.eclipse.kura.web2"
MARKER=".upstream-mgmt-ui-last-reviewed"
REJECTED=".upstream-mgmt-ui-rejected"

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
    echo "Remote '$REMOTE' not found. Add it with:"
    echo "  git remote add $REMOTE https://github.com/eclipse-kura/kura-management-ui.git"
    exit 1
fi

git fetch "$REMOTE" --quiet "$BRANCH"

if [ -f "$MARKER" ]; then
    LAST=$(cat "$MARKER")
else
    LAST="$REMOTE/$BRANCH~50"
    echo "No marker file at $MARKER. Showing last 50 upstream commits as a starting point."
    echo
fi

echo "=== Upstream $REMOTE/$BRANCH commits since $(git rev-parse --short "$LAST") touching $SUBPATH/ ==="

REJECTED_LIST=""
if [ -f "$REJECTED" ]; then
    REJECTED_LIST=$(tr '\n' '|' < "$REJECTED" | sed 's/|$//')
fi

git log --reverse --oneline "$LAST..$REMOTE/$BRANCH" -- "$SUBPATH" | while read -r line; do
    sha=$(echo "$line" | awk '{print $1}')
    if [ -n "$REJECTED_LIST" ] && echo "$sha" | grep -qE "^($REJECTED_LIST)"; then
        continue
    fi
    echo "$line"
done

echo
echo "----"
echo "Backport one:    git cherry-pick <sha>"
echo "Reject forever:  echo <sha> >> $REJECTED"
echo "Mark all done:   git rev-parse $REMOTE/$BRANCH > $MARKER"
