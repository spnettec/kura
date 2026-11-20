#!/bin/sh
# SPDX-License-Identifier: EPL-2.0
# The installed service uses a systemd credential; direct launchers use the same key.
kura_prepare_configuration() (
    output=$1
    mkdir -p -- "$(dirname -- "$output")" || exit 1
    [ ! -d "$output" ] || exit 1
    pending=$(mktemp "${output}.XXXXXX") || exit 1
    trap 'rm -f -- "$pending"' 0
    trap 'exit 1' HUP INT TERM

    # Copy the template separately so its read errors reach the launcher. The
    # paired bundle loader appends its normal bundle list from an empty template.
    cat "${DIR}/framework/config.ini" > "$pending" || exit 1
    "${DIR}/bin/gen_config_ini.sh" /dev/null "${DIR}/plugins" "${DIR}/siblings" >> "$pending" || exit 1
    mv -f -- "$pending" "$output" || exit 1
    trap - 0 HUP INT TERM
)

if [ -z "${CREDENTIALS_DIRECTORY:-}" ]; then
    CREDENTIALS_DIRECTORY=/etc/kura/credentials
    export CREDENTIALS_DIRECTORY
fi
python3 -I "${DIR}/bin/kura_key_store.py" check-loaded-managed

