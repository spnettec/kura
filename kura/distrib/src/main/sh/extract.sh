#!/bin/sh
# Copyright (c) 2011, 2026 Eurotech and/or its affiliates and others
# SPDX-License-Identifier: EPL-2.0

set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
unset DPKG_ROOT DPKG_ADMINDIR DPKG_FORCE
umask 077

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

[ "$#" -eq 0 ] || fail 'Run this Kura Core installer without arguments.'
[ "$(id -u)" -eq 0 ] || fail 'Installing Kura Core requires root.'
command -v dpkg >/dev/null && command -v dpkg-query >/dev/null ||
    fail 'This Kura Core installer requires dpkg.'

# An interrupted configure already has its own durable package state. Never
# unpack over it or fall back to the historical unmanaged installer.
status=$(LC_ALL=C dpkg-query -W -f='${db:Status-Status}' kura-core 2>&1) || {
    [ "$status" = 'dpkg-query: no packages found matching kura-core' ] ||
        fail 'Cannot determine the installed Kura Core package state.'
    status=not-installed
}
case "$status" in
    installed) ;;
    not-installed|config-files)
        for path in /opt/eclipse/kura* /opt/eclipse/esf* /opt/eclipse/data; do
            if [ -e "$path" ] || [ -L "$path" ]; then
                fail 'Existing unmanaged Kura files require an explicit migration before installation.'
            fi
        done
        ;;
    unpacked|half-configured)
        fail 'Kura Core has a pending configure. Resolve the cause and run dpkg --configure kura-core.'
        ;;
    *)
        fail 'Kura Core has an unsettled package state. Inspect dpkg before installing.'
        ;;
esac

workdir=$(mktemp -d /var/tmp/kura-core-installer.XXXXXXXX)
trap 'rm -rf -- "$workdir"' EXIT
trap 'exit 1' HUP INT TERM
package="$workdir/kura-core.deb"
payload_line=$(LC_ALL=C awk '/^__KURA_CORE_DEB__$/ { print NR + 1; exit }' "$0")
[ -n "$payload_line" ] || fail 'Missing Kura Core package payload.'
tail -n "+$payload_line" -- "$0" > "$package"
printf '%s  %s\n' '@CORE_DEB_SHA256@' "$package" | sha256sum --check --status ||
    fail 'Kura Core package payload failed its checksum.'

# Keep the caller's working directory clear of package maintenance.
cd "$workdir"
dpkg --install "$package"
exit 0
__KURA_CORE_DEB__
