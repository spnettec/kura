#!/usr/bin/env bash
# Install every OSGi-bundle .jar from target/repository/plugins/ into the local
# Maven repository so distrib's maven-dependency-plugin can resolve them.
#
# Coordinates use groupId=p2.osgi.bundle (matching Tycho's convention), with
# artifactId/version parsed from the filename (`<name>_<version>.jar`).
#
# Bypasses `mvn install:install-file` (which spawns a JVM per jar, ~2s each →
# ~15 min for 441 bundles). Writes directly into ~/.m2/repository instead, and
# skips bundles whose jar size already matches the destination — so repeat
# builds finish in seconds.
set -euo pipefail

PLUGINS_DIR="${1:-target/repository/plugins}"
GROUP_ID="${2:-p2.osgi.bundle}"

if [ ! -d "$PLUGINS_DIR" ]; then
    echo "warn: $PLUGINS_DIR not found, skipping install" >&2
    exit 0
fi

LOCAL_REPO="${MAVEN_LOCAL_REPO:-$HOME/.m2/repository}"
GROUP_PATH="${GROUP_ID//.//}"

# Portable file-size helper (BSD stat on macOS, GNU stat on Linux).
file_size() {
    stat -f%z "$1" 2>/dev/null || stat -c%s "$1"
}

installed=0
skipped=0
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

    target_dir="$LOCAL_REPO/$GROUP_PATH/$name/$ver"
    target_jar="$target_dir/$name-$ver.jar"
    target_pom="$target_dir/$name-$ver.pom"
    target_marker="$target_dir/_remote.repositories"

    if [ -f "$target_jar" ] && [ -f "$target_pom" ] && [ -f "$target_marker" ]; then
        if [ "$(file_size "$jar")" = "$(file_size "$target_jar")" ]; then
            skipped=$((skipped + 1))
            continue
        fi
    fi

    mkdir -p "$target_dir"
    cp -f "$jar" "$target_jar"
    cat > "$target_pom" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>$GROUP_ID</groupId>
  <artifactId>$name</artifactId>
  <version>$ver</version>
  <packaging>jar</packaging>
  <description>Installed by target-platform/install-to-m2.sh</description>
</project>
EOF
    # _remote.repositories tells Maven the artifact is locally installed (not
    # downloaded), so it won't try to resolve from a remote repo.
    cat > "$target_marker" <<EOF
#NOTE: This is a Maven Resolver internal implementation file, its format can be changed without prior notice.
$name-$ver.jar>=
$name-$ver.pom>=
EOF
    installed=$((installed + 1))
done
echo "P2 -> local m2 ($GROUP_ID): installed $installed, skipped $skipped (already up-to-date)"
