#!/usr/bin/env bash
# SPDX-License-Identifier: EPL-2.0
# Run in a dedicated CI checkout: build-all cleans module targets.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MVN="${MVN:-mvn}"
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --check ) ]]; then
    echo "Usage: $0 [--check]" >&2
    exit 2
fi
version="$("$MVN" --version)"
printf '%s\n' "$version"
[[ "$version" =~ Apache\ Maven\ 3\.10\. ]] || { echo 'CI requires Maven 3.10.x' >&2; exit 2; }
[[ "$version" =~ Java\ version:\ 21[.,] ]] || { echo 'CI requires Maven to run on JDK 21' >&2; exit 2; }
command -v python3 >/dev/null
repos=(kura-position kura-opcua kura-deployment kura-networking kura-wires kura-cloud
       kura-camel kura-artemis kura-container kura-triton kura-management-ui kura-yofc-runtime yofc-iot)
for repo in "${repos[@]}"; do
    [[ -f "$ROOT/../$repo/pom.xml" ]] || { echo "Missing prepared sibling checkout: $repo" >&2; exit 2; }
done
if [[ "${1:-}" == --check ]]; then
    echo 'Toolchain and workspace layout passed; PLC4X artifacts must already be installed in the selected Maven repository.'
    exit 0
fi
mkdir -p "$ROOT/target/ci"
# An interrupted run must never publish reports from the preceding build.
rm -rf "$ROOT/target/ci/test-reports"
rm -f "$ROOT/target/ci/summary.json"
started="$(python3 -c 'import time; print(time.time())')"
set +e
RUN_TESTS=1 RUN_IT=1 BUILD_DOCKER=0 MVN="$MVN" "$ROOT/build-all.sh"
build_status=$?
python3 "$ROOT/tools/ci/collect-reports.py" --workspace "$ROOT/.." --since "$started" \
    --output "$ROOT/target/ci" --repositories kura "${repos[@]}"
report_status=$?
set -e
[[ "$build_status" == 0 ]] || exit "$build_status"
exit "$report_status"
