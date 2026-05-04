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

# Stage 1: monorepo (target-platform + base kura.deb / kura-nn.deb).
#   - kura-{management-ui,networking}/bundles are pulled in cross-repo by kura/pom.xml so
#     their bundle jars land in ~/.m2 for the addon distribs in Stage 2.
#   - kura-opcua bundle is NOT pulled here — the sibling has its own self-contained
#     target-platform (reficio P2 in kura-opcua/target-platform/p2-repo-opcua-deps) and
#     its own Tycho version (5.0.2 vs monorepo's 4.0.11), so it builds itself in Stage 2.
mvn "$@" -f target-platform/pom.xml clean install $MAVEN_PROPS &&
mvn "$@" -f kura/pom.xml clean install $MAVEN_PROPS &&
mvn "$@" -f kura/distrib/pom.xml clean install $MAVEN_PROPS &&

# Stage 2: each sibling produces its addon .deb.
#
#   kura-management-ui, kura-networking
#       monorepo-built bundle jars in ~/.m2 from Stage 1; sibling distrib pom assembles deb.
#
#   kura-opcua
#       sibling self-contained reactor: target-platform (reficio) + bundle + distrib.
#       Tests bundle is excluded — it pulls mockito which the sibling target-platform
#       doesn't ship.
SCRIPT_DIR="$(dirname "$0")"
for sibling in kura-management-ui kura-networking; do
    sibling_dir="$SCRIPT_DIR/../$sibling"
    if [ -f "$sibling_dir/distrib/pom.xml" ]; then
        echo "=== Stage 2: building $sibling addon .deb ==="
        # Install sibling parent pom one-time so distrib can resolve it.
        if [ -f "$sibling_dir/bundles/pom.xml" ]; then
            mvn "$@" -f "$sibling_dir/bundles/pom.xml" -N install $MAVEN_PROPS || exit 1
        fi
        mvn "$@" -f "$sibling_dir/distrib/pom.xml" clean install $MAVEN_PROPS || exit 1
    else
        echo "=== Stage 2: skipping $sibling (clone not found at $sibling_dir) ==="
    fi
done

# kura-opcua: full sibling reactor, skip tests bundle.
if [ -f "$SCRIPT_DIR/../kura-opcua/pom.xml" ]; then
    echo "=== Stage 2: building kura-opcua addon .deb (sibling self-build) ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-opcua/pom.xml" clean install $MAVEN_PROPS \
        -pl '!tests/org.eclipse.kura.driver.opcua.test' || exit 1
else
    echo "=== Stage 2: skipping kura-opcua (clone not found) ==="
fi

