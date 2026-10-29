#!/usr/bin/env bash
# Integration test for a disposable Debian/Ubuntu VM. This installs and removes
# Kura, including a purge. It must never be run on a machine with real Kura data.
set -euo pipefail

: "${KURA_TEST_PACKAGE:?Set KURA_TEST_PACKAGE to the absolute path of the core .deb}"
if [ "${KURA_TEST_ALLOW_DESTRUCTIVE:-}" != 1 ] || [ "$(id -u)" != 0 ]; then
    echo "Run as root in a disposable VM with KURA_TEST_ALLOW_DESTRUCTIVE=1." >&2
    exit 1
fi
if dpkg-query -W -f='${db:Status-Status}' kura-core 2>/dev/null | grep -qv '^not-installed$'; then
    echo "kura-core must not already be installed or have retained configuration." >&2
    exit 1
fi
if [ -e /opt/eclipse/kura ] || [ -e /var/lib/kura-retained ] || [ -e /opt/eclipse/.kura-preserve ]; then
    echo "Existing Kura data or a recovery copy was found; refusing to run." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
install_core() {
    apt-get install -y "${KURA_TEST_PACKAGE}"
    test -z "$(dpkg --audit)"
}
make_fixtures() {
    local root=/opt/eclipse/kura
    install -o root -g kurad -m 640 /dev/null "${root}/user/security/retention-test.key"
    printf 'test-key-only\n' > "${root}/user/security/retention-test.key"
    stat -c '%u:%g:%a' "${root}/user/security/retention-test.key" > /tmp/kura-retention-key-mode.txt
    cp -a "${root}/user/snapshots/snapshot_0.xml" "${root}/user/snapshots/snapshot_99.xml"
    printf 'test-database-only\n' > "${root}/data/retention-test.db"
    printf 'test-package-only\n' > "${root}/packages/retention-test.dp"
    printf 'test-runtime-log-only\n' > "${root}/log/retention-test.log"
    printf 'test-audit-log-only\n' > /var/log/kura-retention-test.log
    chown kurad:kurad "${root}/data/retention-test.db" "${root}/packages/retention-test.dp" "${root}/log/retention-test.log"
    sha256sum /var/log/kura-retention-test.log > /tmp/kura-retention-log.sha
    # A real deployment may put the snapshot master key in the systemd unit.
    # Use a test-only key, and never print its value to the test log.
    python3 - <<'PY'
from pathlib import Path
p = Path('/lib/systemd/system/kura.service')
lines = p.read_text().splitlines(keepends=True)
indexes = [i for i, line in enumerate(lines) if line.startswith('Environment=KURA_CRYPTO_SECRET_KEY=')]
assert len(indexes) == 1
lines[indexes[0]] = 'Environment=KURA_CRYPTO_SECRET_KEY=retention-test-master-key\n'
p.write_text(''.join(lines))
PY
    chmod 640 /lib/systemd/system/kura.service
    mkdir -p /etc/systemd/system/kura.service.d
    printf '[Service]\nEnvironment=KURA_RETENTION_TEST=1\n' > /etc/systemd/system/kura.service.d/retention-test.conf
    cp -a /lib/systemd/system/kura.service /tmp/kura-retention-service-before
    cp -a /etc/systemd/system/kura.service.d/retention-test.conf /tmp/kura-retention-dropin-before
    systemctl daemon-reload
    (cd "${root}" && sha256sum user/snapshots/snapshot_0.xml user/snapshots/snapshot_99.xml \
        user/security/cacerts.ks user/security/httpskeystore.ks user/security/retention-test.key \
        user/kura_custom.properties data/retention-test.db packages/dpa.properties packages/retention-test.dp log/retention-test.log) > /tmp/kura-retention-hashes.txt
}
verify_files() {
    (cd "$1" && sha256sum -c /tmp/kura-retention-hashes.txt)
}
assert_purged() {
    test ! -e /opt/eclipse/kura
    test ! -e /var/lib/kura-retained
    test ! -e /opt/eclipse/.kura-preserve
    test ! -e /etc/kura/preserved-state.conf
    test ! -e /etc/systemd/system/kura.service.d
    test ! -e /etc/systemd/system/kura.service
    test ! -e /lib/systemd/system/kura.service
    test ! -e /var/log/kura-retention-test.log
    test -z "$(dpkg --audit)"
}

echo '=== Install and prepare test data ==='
install_core
systemctl start kura
sleep 15
make_fixtures

echo '=== Existing upgrade recovery data prevents destructive reinstall ==='
mkdir -m 700 /opt/eclipse/.kura-preserve
printf 'existing upgrade recovery copy\n' > /opt/eclipse/.kura-preserve/test-sentinel
if apt-get install -y --reinstall "${KURA_TEST_PACKAGE}"; then
    echo 'Reinstall unexpectedly succeeded with an existing upgrade recovery copy.' >&2
    exit 1
fi
test -f /opt/eclipse/.kura-preserve/test-sentinel
verify_files /opt/eclipse/kura
test "$(dpkg-query -W -f='${db:Status-Status}' kura-core)" = installed
rm -rf /opt/eclipse/.kura-preserve
systemctl start kura

echo '=== Existing recovery data prevents destructive removal ==='
mkdir -m 700 /var/lib/kura-retained
printf 'existing recovery copy\n' > /var/lib/kura-retained/test-sentinel
if apt-get remove -y kura-core; then
    echo 'Removal unexpectedly succeeded with an existing recovery copy.' >&2
    exit 1
fi
test -f /var/lib/kura-retained/test-sentinel
verify_files /opt/eclipse/kura
test "$(dpkg-query -W -f='${db:Status-Status}' kura-core)" = installed
rm -rf /var/lib/kura-retained
systemctl start kura

echo '=== Remove and verify retained data ==='
apt-get remove -y kura-core
test "$(dpkg-query -W -f='${db:Status-Status}' kura-core)" = config-files
test ! -e /opt/eclipse/kura
test "$(stat -c %a /var/lib/kura-retained)" = 700
verify_files /var/lib/kura-retained
test "$(stat -c '%u:%g:%a' /var/lib/kura-retained/user/security/retention-test.key)" = "$(cat /tmp/kura-retention-key-mode.txt)"
sha256sum -c /tmp/kura-retention-log.sha
cmp /tmp/kura-retention-service-before /var/lib/kura-retained/systemd/kura.service
test "$(stat -c %a /var/lib/kura-retained/systemd/kura.service)" = 640
cmp /tmp/kura-retention-dropin-before /etc/systemd/system/kura.service.d/retention-test.conf
test -f /etc/kura/preserved-state.conf

echo '=== Reinstall and verify restored data ==='
install_core
verify_files /opt/eclipse/kura
test "$(stat -c '%u:%g:%a' /opt/eclipse/kura/user/security/retention-test.key)" = "$(cat /tmp/kura-retention-key-mode.txt)"
sha256sum -c /tmp/kura-retention-log.sha
cmp /tmp/kura-retention-service-before /lib/systemd/system/kura.service
test "$(stat -c %a /lib/systemd/system/kura.service)" = 640
cmp /tmp/kura-retention-dropin-before /etc/systemd/system/kura.service.d/retention-test.conf
cmp /opt/eclipse/kura/user/snapshots/snapshot_0.xml /opt/eclipse/kura/.data/snapshot_0.xml
test ! -e /var/lib/kura-retained
systemctl start kura
systemctl is-active --quiet kura
python3 - "$(systemctl show -p MainPID --value kura)" <<'PY'
import pathlib, sys
assert b'KURA_CRYPTO_SECRET_KEY=retention-test-master-key' in pathlib.Path('/proc', sys.argv[1], 'environ').read_bytes().split(b'\0')
PY

echo '=== Remove, then purge ==='
apt-get remove -y kura-core
verify_files /var/lib/kura-retained
sha256sum -c /tmp/kura-retention-log.sha
dpkg --purge kura-core
assert_purged

echo '=== Purge directly from installed state ==='
install_core
make_fixtures
dpkg --purge kura-core
assert_purged
echo 'KURA_RETENTION_TEST_SUCCESS'
