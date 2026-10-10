#!/usr/bin/env bash
# Copyright (c) 2026 Contributors to the Eclipse Foundation.
# SPDX-License-Identifier: EPL-2.0
set -euo pipefail

# Prepare dependencies with Maven 3.10 / JDK 21 before this offline container run.
: "${MAVEN_HOME:?Set MAVEN_HOME to the Maven 3.10 distribution directory}"
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
maven_repo="${MAVEN_REPO:-$HOME/.m2/repository}"
report_parent="$repo_root/kura/org.eclipse.kura.core.system/target"
container_id=""
cleanup() {
    if [[ -n "$container_id" ]]; then docker rm -f "$container_id" >/dev/null; fi
}
trap cleanup EXIT
test -x "$MAVEN_HOME/bin/mvn"
test -d "$maven_repo"
mkdir -p "$report_parent"
report_dir="$(mktemp -d "$report_parent/isolated-system-reports-XXXXXXXX")"

# No network, host /opt mount, or writable checkout/cache is provided. Only the
# generated reports are copied to a separate writable mount before tmpfs teardown.
container_id="$(docker create --network none --read-only \
    --tmpfs /tmp:exec --tmpfs /opt/eclipse/kura --tmpfs /m2/.locks \
    --tmpfs /workspace/kura/org.eclipse.kura.core.system/target \
    --mount "type=bind,source=$repo_root,target=/workspace,readonly" \
    --mount "type=bind,source=$MAVEN_HOME,target=/maven,readonly" \
    --mount "type=bind,source=$maven_repo,target=/m2,readonly" \
    --mount "type=bind,source=$report_dir,target=/reports" \
    -e KURA_SYSTEM_PATH_FIXTURE=1 \
    -w /workspace/kura/org.eclipse.kura.core.system \
    "${JDK_IMAGE:-eclipse-temurin:21-jdk}" \
    sh -c '/maven/bin/mvn --version && /maven/bin/mvn -o -B -Dmaven.repo.local=/m2 test
status=$?
if [ -d target/surefire-reports ]; then cp -R target/surefire-reports/. /reports/ || exit 1; fi
exit "$status"')"
status=0
docker start -a "$container_id" || status=$?
printf 'Isolated system test reports: %s\n' "$report_dir"
exit "$status"
