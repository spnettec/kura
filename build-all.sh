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

# activate batch mode by default

MAVEN_PROPS="-B"

# allow running tests

[ -z "$RUN_TESTS" ] && MAVEN_PROPS="$MAVEN_PROPS -Dmaven.test.skip=true"

# Stage 1: monorepo bundles only (target-platform + kura/pom.xml).
# kura/distrib (kura-core.deb) moves to Stage 3 because the docker sibling
# (Stage 4) consumes kura-core.deb + sibling .debs from ~/.m2.
mvn "$@" -f target-platform/pom.xml clean install $MAVEN_PROPS || exit 1
mvn "$@" -f kura/pom.xml clean install $MAVEN_PROPS || exit 1

# Stage 2: each sibling produces its bundle(s) + addon .deb.
SCRIPT_DIR="$(dirname "$0")"

# Siblings have no compile-time dependency on each other — each only consumes
# monorepo bundles + third-party. Order here is therefore not load-bearing;
# this listing is just a stable, predictable build sequence.

if [ -f "$SCRIPT_DIR/../kura-position/pom.xml" ]; then
    echo "=== Stage 2: building kura-position addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-position/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-position/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-position (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-networking/pom.xml" ]; then
    echo "=== Stage 2: building kura-networking addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-networking/pom.xml" clean install $MAVEN_PROPS \
        -pl '!tests,!tests/org.eclipse.kura.core.net.test,!tests/org.eclipse.kura.linux.net.test,!tests/org.eclipse.kura.net.admin.firewall.test,!tests/org.eclipse.kura.net.configuration.test,!tests/org.eclipse.kura.network.threat.manager.test,!tests/org.eclipse.kura.nm.test,!tests/org.eclipse.kura.rest.network.configuration.provider.test,!tests/org.eclipse.kura.rest.network.status.provider.test' \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-networking/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-networking (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-management-ui/pom.xml" ]; then
    echo "=== Stage 2: building kura-management-ui addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-management-ui/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-management-ui/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-management-ui (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-opcua/pom.xml" ]; then
    echo "=== Stage 2: building kura-opcua addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-opcua/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-opcua/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-opcua (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-wires/pom.xml" ]; then
    echo "=== Stage 2: building kura-wires addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-wires/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-wires/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-wires (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-camel/pom.xml" ]; then
    echo "=== Stage 2: building kura-camel addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-camel/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-camel/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-camel (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-deployment/pom.xml" ]; then
    echo "=== Stage 2: building kura-deployment addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-deployment/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-deployment/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-deployment (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-artemis/pom.xml" ]; then
    echo "=== Stage 2: building kura-artemis addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-artemis/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-artemis/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-artemis (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-triton/pom.xml" ]; then
    echo "=== Stage 2: building kura-triton addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-triton/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-triton/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-triton (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-container/pom.xml" ]; then
    echo "=== Stage 2: building kura-container addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-container/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-container/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-container (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-cloud/pom.xml" ]; then
    echo "=== Stage 2: building kura-cloud addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-cloud/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-cloud/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-cloud (clone not found) ==="
fi

# Library + IDE-support sibling. Root reactor: target-platform (reficio wrap
# of 10 yofc-only jars into p2.osgi.bundle:*) -> bundles (yofc-iot-repack-vertx-db)
# -> pde-deps (Eclipse IDE target delta) -> distrib (.deb). Single `mvn install`
# walks all four; no second distrib step needed.
if [ -f "$SCRIPT_DIR/../kura-yofc-runtime/pom.xml" ]; then
    echo "=== Stage 2: building kura-yofc-runtime addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-yofc-runtime/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-yofc-runtime (clone not found) ==="
fi

# Stage 2.5: yofc-iot application dp packages. yofc-iot is NOT a Kura sibling
# (.deb) — it produces OSGi .dp deployment packages consumed by kura-docker.
# Depends on kura-yofc-runtime (Stage 2) and plc4x-yofc artifacts in ~/.m2.
if [ -f "$SCRIPT_DIR/../yofc-iot/pom.xml" ]; then
    echo "=== Stage 2.5: building yofc-iot .dp packages ==="
    mvn "$@" -f "$SCRIPT_DIR/../yofc-iot/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2.5: skipping yofc-iot (clone not found) ==="
fi

# Stage 3: kura-core.deb. Runs after Stage 2 so the .deb (attached as a Maven
# artifact by jdeb) is available for downstream consumers like kura-docker.
echo "=== Stage 3: building kura/distrib (kura-core.deb) ==="
mvn "$@" -f kura/distrib/pom.xml clean install $MAVEN_PROPS || exit 1

# Stage 4: Docker image (kura-docker sibling). Pulls kura-core.deb + sibling
# .debs from ~/.m2 and installs them via dpkg -x inside the Dockerfile.
# Builds both ARM64 (native) and AMD64 (via QEMU emulation) images.
if [ -f "$SCRIPT_DIR/../kura-docker/pom.xml" ]; then
    echo "=== Stage 4: building kura-docker image (arm64) ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-docker/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
    # Save arm64 image before amd64 build overwrites the tag
    docker tag kura-alpine:latest kura-alpine:latest-arm64

    echo "=== Stage 4: building kura-docker image (amd64) ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-docker/pom.xml" install $MAVEN_PROPS \
        -Ddocker.platform=linux/amd64 \
        || exit 1
    docker tag kura-alpine:latest kura-alpine:latest-amd64
else
    echo "=== Stage 4: skipping kura-docker (clone not found) ==="
fi

