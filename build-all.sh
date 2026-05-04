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
#   - kura-management-ui (web2) is still pulled in cross-repo by kura/pom.xml so
#     its bundle jar lands in ~/.m2 for the addon distrib in Stage 2.
#   - kura-{networking,opcua} bundles are NOT pulled — those siblings are
#     fully self-contained (own Tycho 5.0.2 parent + target-definition) and
#     build themselves in Stage 2.
mvn "$@" -f target-platform/pom.xml clean install $MAVEN_PROPS &&
mvn "$@" -f kura/pom.xml clean install $MAVEN_PROPS &&
mvn "$@" -f kura/distrib/pom.xml clean install $MAVEN_PROPS &&

# Stage 2: each sibling produces its addon .deb.
#
#   kura-management-ui (Path X)
#       monorepo-built web2 jar in ~/.m2 from Stage 1; sibling distrib pom assembles deb.
#
#   kura-networking, kura-opcua (Path Y)
#       full sibling reactor: target-platform (reficio for opcua only) + bundles + distrib.
#       Tests modules are excluded — they import mockito 5.21.0 which is not in
#       target-platform-bom (still 5.7.0).
SCRIPT_DIR="$(dirname "$0")"

# Path X siblings: monorepo built bundle, sibling builds deb.
for sibling in kura-management-ui; do
    sibling_dir="$SCRIPT_DIR/../$sibling"
    if [ -f "$sibling_dir/distrib/pom.xml" ]; then
        echo "=== Stage 2: building $sibling addon .deb (Path X) ==="
        if [ -f "$sibling_dir/bundles/pom.xml" ]; then
            mvn "$@" -f "$sibling_dir/bundles/pom.xml" -N install $MAVEN_PROPS || exit 1
        fi
        mvn "$@" -f "$sibling_dir/distrib/pom.xml" clean install $MAVEN_PROPS || exit 1
    else
        echo "=== Stage 2: skipping $sibling (clone not found at $sibling_dir) ==="
    fi
done

# Path Y siblings: full self-build (bundle + distrib in one mvn invocation).
if [ -f "$SCRIPT_DIR/../kura-networking/pom.xml" ]; then
    echo "=== Stage 2: building kura-networking addon .deb (Path Y, sibling self-build) ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-networking/pom.xml" clean install $MAVEN_PROPS \
        -pl '!tests,!tests/org.eclipse.kura.core.net.test,!tests/org.eclipse.kura.linux.net.test,!tests/org.eclipse.kura.net.admin.firewall.test,!tests/org.eclipse.kura.net.configuration.test,!tests/org.eclipse.kura.network.threat.manager.test,!tests/org.eclipse.kura.nm.test,!tests/org.eclipse.kura.rest.network.configuration.provider.test,!tests/org.eclipse.kura.rest.network.status.provider.test' \
        || exit 1
else
    echo "=== Stage 2: skipping kura-networking (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-opcua/pom.xml" ]; then
    echo "=== Stage 2: building kura-opcua addon .deb (Path Y, sibling self-build) ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-opcua/pom.xml" clean install $MAVEN_PROPS \
        -pl '!tests/org.eclipse.kura.driver.opcua.test' || exit 1
else
    echo "=== Stage 2: skipping kura-opcua (clone not found) ==="
fi

