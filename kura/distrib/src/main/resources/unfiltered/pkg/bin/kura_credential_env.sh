#!/bin/sh
# SPDX-License-Identifier: EPL-2.0
# The installed service uses a systemd credential; direct launchers use the same key.
if [ -z "${CREDENTIALS_DIRECTORY:-}" ]; then
    CREDENTIALS_DIRECTORY=/etc/kura/credentials
    export CREDENTIALS_DIRECTORY
fi
python3 -I "${DIR}/bin/kura_key_store.py" check-loaded

