#!/bin/sh
# SPDX-License-Identifier: EPL-2.0
# The installed service uses a systemd credential; direct launchers use the same key.
# A reviewed container adapter can disable injection. Prefer its published
# generation before the package's original direct-read credential.
if [ -z "${CREDENTIALS_DIRECTORY:-}" ]; then
    if [ -e /var/lib/kura-generation-credentials ] || [ -L /var/lib/kura-generation-credentials ]; then
        CREDENTIALS_DIRECTORY=/var/lib/kura-generation-credentials
    elif [ -r /var/lib/kura-credentials/kura_encryption_key ]; then
        CREDENTIALS_DIRECTORY=/var/lib/kura-credentials
    else
        CREDENTIALS_DIRECTORY=/etc/kura/credentials
    fi
    export CREDENTIALS_DIRECTORY
fi
# Keep the installation's private data directory open across the shell-to-JVM exec.
exec 8<"${DIR}/data" || return 1
python3 -I "${DIR}/bin/kura_key_store.py" check-loaded-managed --lock-instance

