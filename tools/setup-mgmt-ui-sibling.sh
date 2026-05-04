#!/usr/bin/env bash
#
# Set up the kura-management-ui sibling clone next to the kura monorepo.
# The kura monorepo's reactor (kura/kura/pom.xml) references the sibling via
# ../../kura-management-ui/bundles/org.eclipse.kura.web2 — so without this
# clone, `mvn -f kura/pom.xml install` cannot compile web2.
#
# Remote naming mirrors the kura monorepo:
#   origin   = eclipse-kura/kura-management-ui.git   (official upstream)
#   heyoulin = spnettec/kura-management-ui.git       (YOFC fork; tracks yofc/main)
#
# Default sibling location: ~/iot-kura-develop/git/kura-management-ui/
# Override via SIBLING_DIR env var or first positional arg.
#
set -euo pipefail

DEFAULT_DIR="$(cd "$(git rev-parse --show-toplevel)/.." && pwd)/kura-management-ui"
SIBLING_DIR="${SIBLING_DIR:-${1:-$DEFAULT_DIR}}"

UPSTREAM_URL="https://github.com/eclipse-kura/kura-management-ui.git"
FORK_URL="https://github.com/spnettec/kura-management-ui.git"

if [ -d "$SIBLING_DIR/.git" ]; then
    echo "Sibling already exists at $SIBLING_DIR — updating remotes + fetching."
    cd "$SIBLING_DIR"
    git remote get-url origin   >/dev/null 2>&1 || git remote add origin   "$UPSTREAM_URL"
    git remote get-url heyoulin >/dev/null 2>&1 || git remote add heyoulin "$FORK_URL"
    git remote set-url origin   "$UPSTREAM_URL"
    git remote set-url heyoulin "$FORK_URL"
else
    echo "Cloning eclipse-kura/kura-management-ui into $SIBLING_DIR ..."
    mkdir -p "$(dirname "$SIBLING_DIR")"
    git clone "$UPSTREAM_URL" "$SIBLING_DIR"
    cd "$SIBLING_DIR"
    git remote add heyoulin "$FORK_URL"
fi

git fetch origin
git fetch heyoulin

if git rev-parse --verify --quiet heyoulin/yofc/main >/dev/null; then
    if git rev-parse --verify --quiet yofc/main >/dev/null; then
        git checkout yofc/main
        git pull --ff-only heyoulin yofc/main
    else
        git checkout -b yofc/main heyoulin/yofc/main
    fi
else
    echo "WARN: heyoulin/yofc/main not found on the fork."
fi

echo
echo "Sibling ready: $SIBLING_DIR"
echo "  origin   = $UPSTREAM_URL  (official upstream)"
echo "  heyoulin = $FORK_URL  (YOFC fork)"
echo
echo "The monorepo's reactor at kura/kura/pom.xml builds web2 directly from this"
echo "sibling — no sync needed. Edit web2 here, commit + push to heyoulin yofc/main:"
echo "  git push heyoulin yofc/main"
echo
echo "Pulling upstream commits into the YOFC fork:"
echo "  cd $SIBLING_DIR"
echo "  git fetch origin"
echo "  git log yofc/main..origin/develop -- bundles/org.eclipse.kura.web2/"
echo "  git cherry-pick <sha>          # path-aligned with upstream, applies cleanly"
echo "  git push heyoulin yofc/main"
echo
echo "Sending a fix back to upstream (do NOT use yofc/main as PR base):"
echo "  cd $SIBLING_DIR"
echo "  git checkout -b fix/<topic> origin/develop"
echo "  # ... commit ..."
echo "  git push heyoulin fix/<topic>"
echo "  # PR on github: spnettec/kura-management-ui:fix/<topic> -> eclipse-kura/kura-management-ui:develop"
