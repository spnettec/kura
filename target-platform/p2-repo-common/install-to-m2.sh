#!/usr/bin/env bash
# Install every OSGi-bundle .jar from target/repository/plugins/ into the local
# Maven repository so distrib's maven-dependency-plugin can resolve them.
#
# Coordinates use groupId=p2.osgi.bundle (matching Tycho's convention), with
# artifactId/version parsed from the filename (`<name>_<version>.jar`).
#
# Idempotent: install-file overwrites; safe to re-run on every build.
set -euo pipefail

PLUGINS_DIR="${1:-target/repository/plugins}"
GROUP_ID="${2:-p2.osgi.bundle}"

if [ ! -d "$PLUGINS_DIR" ]; then
    echo "warn: $PLUGINS_DIR not found, skipping install" >&2
    exit 0
fi

count=0
for jar in "$PLUGINS_DIR"/*.jar; do
    [ -f "$jar" ] || continue
    base=$(basename "$jar" .jar)
    case "$base" in
        *.source) continue ;;  # skip Eclipse source bundles
    esac
    name="${base%_*}"
    ver="${base##*_}"
    if [ -z "$name" ] || [ -z "$ver" ] || [ "$name" = "$base" ]; then
        echo "skip (unrecognised name): $jar" >&2
        continue
    fi
    mvn -B -q install:install-file \
        -Dfile="$jar" \
        -DgroupId="$GROUP_ID" \
        -DartifactId="$name" \
        -Dversion="$ver" \
        -Dpackaging=jar
    count=$((count + 1))
done
echo "Installed $count P2 bundles to local Maven repo as $GROUP_ID:*"
