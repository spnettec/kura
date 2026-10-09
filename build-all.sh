#!/usr/bin/env bash

#
#  Copyright (c) 2016, 2020 Red Hat and others
#
#  This program and the accompanying materials are made
#  available under the terms of the Eclipse Public License 2.0
#  which is available at https://www.eclipse.org/legal/epl-2.0/
#
#  SPDX-License-Identifier: EPL-2.0
#
#  Contributors:
#     Red Hat
#     Eurotech
#

# Complete Kura/YOFC workspace build. PLC4X is an independent prerequisite:
# install its required JARs into the same Maven repository before running this script.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MVN="${MVN:-mvn}"
RUN_TESTS="${RUN_TESTS:-0}"
RUN_IT="${RUN_IT:-0}"
BUILD_DOCKER="${BUILD_DOCKER:-1}"
KURA_BUILD_QUALIFIER="${KURA_BUILD_QUALIFIER:-$(date -u +%Y%m%d%H%M)}"
for flag in "$RUN_TESTS" "$RUN_IT" "$BUILD_DOCKER"; do
    [[ "$flag" == 0 || "$flag" == 1 ]] || { echo "Build flags must be 0 or 1" >&2; exit 2; }
done
[[ "$RUN_IT" == 0 ]] || RUN_TESTS=1
args=(-B "-Dkura.build.qualifier=$KURA_BUILD_QUALIFIER")
if [[ -n "${KURA_MAVEN_REPO:-}" ]]; then
    args+=("-Dmaven.repo.local=$KURA_MAVEN_REPO")
fi
if [[ "$RUN_TESTS" == 0 ]]; then
    args+=(-Dmaven.test.skip=true)
fi
args+=("$@")
siblings=(kura-position kura-opcua kura-deployment kura-networking kura-wires kura-cloud
          kura-camel kura-artemis kura-container kura-triton kura-management-ui kura-yofc-runtime)
for repo in "${siblings[@]}" yofc-iot; do
    [[ -f "$SCRIPT_DIR/../$repo/pom.xml" ]] || { echo "Required workspace repository missing: $SCRIPT_DIR/../$repo" >&2; exit 2; }
done
if [[ "$BUILD_DOCKER" == 1 && ! -f "$SCRIPT_DIR/../kura-docker/pom.xml" ]]; then
    echo "Required Docker repository missing: $SCRIPT_DIR/../kura-docker (or set BUILD_DOCKER=0)" >&2
    exit 2
fi
build() {
    local pom="$1"
    shift
    "$MVN" "${args[@]}" -f "$pom" "$@"
}

# Bootstrap published parents/plugins before consumers are read, including on a cold repository.
echo "=== Stage 1: public parent, BOM, build tools and third-party wrappers ==="
build "$SCRIPT_DIR/build-support/pom.xml" clean install

echo "=== Stage 2: core bundles ==="
build "$SCRIPT_DIR/kura/pom.xml" clean install
if [[ "$RUN_IT" == 1 ]]; then
    build "$SCRIPT_DIR/pom.xml" -Posgi-it -pl :kura-workspace,:kura-osgi-tests -am verify
fi

# Each sibling's root already includes its own distrib/dp modules.
for repo in "${siblings[@]}"; do
    echo "=== Stage 3: $repo ==="
    build "$SCRIPT_DIR/../$repo/pom.xml" clean install
done

echo "=== Stage 4: YOFC applications (consumes independently installed PLC4X JARs) ==="
if ! build "$SCRIPT_DIR/../yofc-iot/pom.xml" clean install; then
    echo "YOFC build failed. If PLC4X artifacts are missing, build plc4x-yofc separately into the same Maven repository." >&2
    exit 1
fi

echo "=== Stage 5: core distribution and standalone development runtime ==="
build "$SCRIPT_DIR/kura/distrib/pom.xml" clean install
build "$SCRIPT_DIR/kura-dev-runtime/pom.xml" clean install

if [[ "$BUILD_DOCKER" == 1 ]]; then
    echo "=== Stage 6: Docker ARM64 and AMD64 images ==="
    # A deb has an architecture-specific USB fragment. Build the matching deb
    # before each image instead of reusing the host architecture's artifact.
    build "$SCRIPT_DIR/kura/distrib/pom.xml" install -Parch-aarch64,!arch-x86_64
    build "$SCRIPT_DIR/../kura-docker/pom.xml" clean install -Ddocker.platform=linux/arm64
    docker tag kura-alpine:latest kura-alpine:latest-arm64
    build "$SCRIPT_DIR/kura/distrib/pom.xml" clean install -Parch-x86_64,!arch-aarch64
    build "$SCRIPT_DIR/../kura-docker/pom.xml" install -Ddocker.platform=linux/amd64
    docker tag kura-alpine:latest kura-alpine:latest-amd64
fi
