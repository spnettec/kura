#!/usr/bin/env bash
set -euo pipefail
MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${KURA_DEV_PROFILE:-auto}"
NETWORK_PROVIDER="${KURA_DEV_NETWORK_PROVIDER:-none}"
# The collector and launcher must select the same variant, including CLI overrides.
runtime_args=("$@")
for ((i=0; i<${#runtime_args[@]}; i++)); do
  case "${runtime_args[i]}" in
    --network-provider) NETWORK_PROVIDER="${runtime_args[i+1]:-}" ;;
    --network-provider=*) NETWORK_PROVIDER="${runtime_args[i]#*=}" ;;
  esac
done
case "$NETWORK_PROVIDER" in
  none|netplan) ;;
  *) echo 'Supported network providers: none, netplan' >&2; exit 1 ;;
esac
export KURA_DEV_NETWORK_PROVIDER="$NETWORK_PROVIDER"
if [[ "${1:-}" == "--no-build" ]]; then
  shift
else
  args=(-B -f "$MODULE_DIR/../pom.xml" -Pworkspace -pl :kura-workspace,:kura-dev-runtime -am install -DskipTests -DskipITs "-Dkura.dev.profile=$PROFILE" "-Dkura.dev.network-provider=$NETWORK_PROVIDER")
  if [[ -n "${KURA_MAVEN_REPO:-}" ]]; then
    args+=("-Dmaven.repo.local=$KURA_MAVEN_REPO")
  fi
  "${MVN:-mvn}" "${args[@]}"
fi
exec python3 "$MODULE_DIR/tools/runtime.py" run --profile "$PROFILE" "$@"
