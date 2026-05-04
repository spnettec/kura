#!/usr/bin/env bash
#
# Set up a satellite checkout of spnettec/kura-management-ui that has paths
# aligned with upstream eclipse-kura/kura-management-ui — so Eclipse Synchronize,
# diff tools, and cherry-pick all work against upstream without path rewriting.
#
# Why a satellite: the monorepo stores the same source under
# kura-management-ui/bundles/..., adding a prefix that doesn't exist in the
# upstream repo. Comparing monorepo↔upstream directly fails on every file. The
# satellite has the upstream-shaped layout, so daily evaluation/cherry-pick is
# clean. Sync to monorepo via tools/pull-mgmt-ui-from-fork.sh.
#
# Default satellite location: ~/forks/kura-management-ui.
# Override via SATELLITE_DIR env var or first positional arg.
#
set -euo pipefail

DEFAULT_DIR="$HOME/forks/kura-management-ui"
SATELLITE_DIR="${SATELLITE_DIR:-${1:-$DEFAULT_DIR}}"

FORK_URL="https://github.com/spnettec/kura-management-ui.git"
UPSTREAM_URL="https://github.com/eclipse-kura/kura-management-ui.git"

if [ -d "$SATELLITE_DIR/.git" ]; then
    echo "Satellite already exists at $SATELLITE_DIR — updating remotes + fetching."
    cd "$SATELLITE_DIR"
    git remote get-url origin >/dev/null 2>&1 || git remote add origin "$FORK_URL"
    git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "$UPSTREAM_URL"
    git remote set-url origin "$FORK_URL"
    git remote set-url upstream "$UPSTREAM_URL"
else
    echo "Cloning spnettec/kura-management-ui into $SATELLITE_DIR ..."
    mkdir -p "$(dirname "$SATELLITE_DIR")"
    git clone "$FORK_URL" "$SATELLITE_DIR"
    cd "$SATELLITE_DIR"
    git remote add upstream "$UPSTREAM_URL"
fi

git fetch origin
git fetch upstream

# Check out yofc/main (the YOFC snapshot branch) if it exists
if git rev-parse --verify --quiet origin/yofc/main >/dev/null; then
    if git rev-parse --verify --quiet yofc/main >/dev/null; then
        git checkout yofc/main
        git reset --hard origin/yofc/main
    else
        git checkout -b yofc/main origin/yofc/main
    fi
else
    echo "WARN: origin/yofc/main not found. Run tools/push-mgmt-ui-to-fork.sh from the monorepo first."
fi

echo
echo "Satellite ready: $SATELLITE_DIR"
echo "  origin   = $FORK_URL"
echo "  upstream = $UPSTREAM_URL"
echo
echo "Daily workflow inside the satellite:"
echo "  git fetch upstream"
echo "  git log yofc/main..upstream/develop -- bundles/org.eclipse.kura.web2/   # what's new upstream"
echo "  git diff yofc/main..upstream/develop -- <path>                          # detail diff"
echo "  git cherry-pick <sha>                                                   # backport one upstream commit"
echo "  git push origin yofc/main                                               # publish your decision"
echo
echo "Then in the monorepo:"
echo "  ./tools/pull-mgmt-ui-from-fork.sh                                       # pull yofc/main back into the monorepo"
