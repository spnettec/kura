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

# Stage 1: monorepo (target-platform + sibling bundle jars + base kura.deb / kura-nn.deb)
# Sibling bundles live in ../kura-{management-ui,networking,opcua}/bundles/ and are pulled in
# by kura/pom.xml's cross-repo <module> entries. They land in ~/.m2 so Stage 2 can pick them up.
mvn "$@" -f target-platform/pom.xml clean install $MAVEN_PROPS &&
mvn "$@" -f kura/pom.xml clean install $MAVEN_PROPS &&
mvn "$@" -f kura/distrib/pom.xml clean install $MAVEN_PROPS &&

# Stage 2: each sibling owns its own distrib/ and produces an addon .deb. Driven by the sibling
# bundle jars already in ~/.m2 from Stage 1. Skipped if the sibling clone is missing.
for sibling in kura-management-ui kura-networking kura-opcua; do
    sibling_dir="$(dirname "$0")/../$sibling"
    if [ -f "$sibling_dir/distrib/pom.xml" ]; then
        echo "=== Stage 2: building $sibling addon .deb ==="
        # Install sibling parent pom (kura-X.parent at bundles/pom.xml) one-time so distrib can resolve it
        mvn "$@" -f "$sibling_dir/bundles/pom.xml" -N install $MAVEN_PROPS &&
        mvn "$@" -f "$sibling_dir/distrib/pom.xml" clean install $MAVEN_PROPS || exit 1
    else
        echo "=== Stage 2: skipping $sibling (clone not found at $sibling_dir) ==="
    fi
done

