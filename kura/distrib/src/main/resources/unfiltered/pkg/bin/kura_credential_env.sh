#!/bin/sh
# SPDX-License-Identifier: EPL-2.0
# The installed service uses a systemd credential; direct launchers use the same key.
if [ -z "${CREDENTIALS_DIRECTORY:-}" ]; then
    CREDENTIALS_DIRECTORY=/etc/kura/credentials
    export CREDENTIALS_DIRECTORY
fi
# Keep the installation's private data directory open across the shell-to-JVM exec.
exec 8<"${DIR}/data" || return 1
python3 -I "${DIR}/bin/kura_key_store.py" check-loaded-managed --lock-instance

