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

# Stage 1: monorepo only (target-platform + base kura-core.deb).
# All five siblings (management-ui, networking, opcua, position, wires/camel) are
# now Path Y — they self-build via their own Tycho 5.0.2 parent + target-definition + reficio.
# Monorepo no longer pulls any sibling bundle in cross-repo.
mvn "$@" -f target-platform/pom.xml clean install $MAVEN_PROPS &&
mvn "$@" -f kura/pom.xml clean install $MAVEN_PROPS &&
mvn "$@" -f kura/distrib/pom.xml clean install $MAVEN_PROPS &&

# Stage 2: each sibling produces its bundle(s) + addon .deb.
SCRIPT_DIR="$(dirname "$0")"

if [ -f "$SCRIPT_DIR/../kura-management-ui/pom.xml" ]; then
    echo "=== Stage 2: building kura-management-ui addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-management-ui/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-management-ui/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-management-ui (clone not found) ==="
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

if [ -f "$SCRIPT_DIR/../kura-opcua/pom.xml" ]; then
    echo "=== Stage 2: building kura-opcua addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-opcua/pom.xml" clean install $MAVEN_PROPS \
        -pl '!tests/org.eclipse.kura.driver.opcua.test' \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-opcua/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-opcua (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-position/pom.xml" ]; then
    echo "=== Stage 2: building kura-position addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-position/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-position/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-position (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-wires/bundles/pom.xml" ]; then
    echo "=== Stage 2: building kura-wires addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-wires/bundles/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-wires/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-wires (clone not found) ==="
fi

if [ -f "$SCRIPT_DIR/../kura-camel/bundles/pom.xml" ]; then
    echo "=== Stage 2: building kura-camel addon .deb ==="
    mvn "$@" -f "$SCRIPT_DIR/../kura-camel/bundles/pom.xml" clean install $MAVEN_PROPS \
        && mvn "$@" -f "$SCRIPT_DIR/../kura-camel/distrib/pom.xml" clean install $MAVEN_PROPS \
        || exit 1
else
    echo "=== Stage 2: skipping kura-camel (clone not found) ==="
fi

