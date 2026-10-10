#!/usr/bin/env bash
set -euo pipefail
MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${KURA_DEV_PROFILE:-auto}"
if [[ "${1:-}" == "--no-build" ]]; then
  shift
else
  args=(-B -f "$MODULE_DIR/../pom.xml" -Pworkspace -pl :kura-workspace,:kura-dev-runtime -am install -DskipTests -DskipITs "-Dkura.dev.profile=$PROFILE")
  if [[ -n "${KURA_MAVEN_REPO:-}" ]]; then
    args+=("-Dmaven.repo.local=$KURA_MAVEN_REPO")
  fi
  "${MVN:-mvn}" "${args[@]}"
fi
exec python3 "$MODULE_DIR/tools/runtime.py" run --profile "$PROFILE" "$@"
