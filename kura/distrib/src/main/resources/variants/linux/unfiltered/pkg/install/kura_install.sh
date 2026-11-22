#!/bin/sh
#
# Copyright (c) 2023 Eurotech and/or its affiliates and others
#
# This program and the accompanying materials are made
# available under the terms of the Eclipse Public License 2.0
# which is available at https://www.eclipse.org/legal/epl-2.0/
#
# SPDX-License-Identifier: EPL-2.0
#
# Contributors:
#  Eurotech
#

systemctl_if_present() {
    ACTION="$1"
    SERVICE="$2"

    if systemctl list-unit-files "${SERVICE}.service" > /dev/null 2>&1 || systemctl list-units --all "${SERVICE}.service" > /dev/null 2>&1; then
        systemctl "${ACTION}" "${SERVICE}" > /dev/null 2>&1 || true
    fi
}

IS_NETWORKING_PROFILE=false
INSTALL_DIR=/opt/eclipse
DEFER_KEY_SERVICE=false
KEY_PROVISION_ACTION=auto
CONFIGURE_STEP=all
case "${1-}" in
    '') ;;
    --defer-key-service) DEFER_KEY_SERVICE=true; KEY_PROVISION_ACTION=package ;;
    --configure-layout|--configure-brokers|--configure-runtime|--configure-https|--configure-ownership)
        DEFER_KEY_SERVICE=true
        KEY_PROVISION_ACTION=package
        CONFIGURE_STEP=${1#--configure-}
        ;;
    *) echo "Unsupported Kura installer argument" >&2; exit 1 ;;
esac

configure_layout() {
    # Standalone invocation must reject an unsupported backend before any changes.
    bash "$(dirname "$0")/manage_kura_users.sh" --check-polkit || exit 1
    bash "$(dirname "$0")/manage_kura_users.sh" --check-pam || exit 1
    bash "$(dirname "$0")/manage_kura_users.sh" --check-nm-policy || exit 1
    python3 -I "$(dirname "$0")/../bin/kura_key_service_lifecycle.py" --enter install || exit 1

    if [ "${KEY_PROVISION_ACTION}" = package ]; then
        # A package phase runs its attested installer inside the incoming tree.
        # Other physical installations must not influence the selected link.
        KURA_VERSION_DIR=$(cd -P -- "$(dirname -- "$0")/.." && pwd) || exit 1
        [ "$(dirname -- "${KURA_VERSION_DIR}")" = "${INSTALL_DIR}" ] || exit 1
        case "${KURA_VERSION_DIR##*/}" in
            kura_*) ;;
            *) return 1 ;;
        esac
    else
        KURA_VERSION_DIR=$(ls -d ${INSTALL_DIR}/kura_*/ 2>/dev/null | head -1)
    fi

    # If ${INSTALL_DIR}/kura already exists as a real directory (e.g. an addon .deb such as
    # kura-management-ui was unpacked before kura's setup ran), merge its files into the
    # unpacked kura_*/ tree so they survive the symlink replacement below.
    if [ -d "${INSTALL_DIR}/kura" ] && [ ! -L "${INSTALL_DIR}/kura" ]; then
        if [ -n "${KURA_VERSION_DIR}" ]; then
            cp -rn "${INSTALL_DIR}/kura/." "${KURA_VERSION_DIR}" 2>/dev/null || true
            rm -rf "${INSTALL_DIR}/kura"
        fi
    fi

    # create known kura install location
    if [ "${KEY_PROVISION_ACTION}" = package ]; then
        ln -snf "${KURA_VERSION_DIR}" "${INSTALL_DIR}/kura" || exit 1
    else
        ln -snf ${INSTALL_DIR}/kura_* "${INSTALL_DIR}/kura" || exit 1
    fi

    # Package mode requires preinst's captured key and maintenance fence. Standalone
    # bootstrap retains its separate fresh-key and ordinary-startup checks.
    # Failure must precede replacing the installed service or changing user state.
    python3 -I "${INSTALL_DIR}/kura/bin/kura_key_store.py" prepare "${KEY_PROVISION_ACTION}" || exit 1
    if [ -e /var/lib/kura-retained ] || [ -L /var/lib/kura-retained ]; then
        # Validate the original removal fence, saved unit and unchanged numeric
        # identities before publishing a unit or creating any runtime accounts.
        python3 -I "${INSTALL_DIR}/kura/bin/kura_key_service_lifecycle.py" --check-retained-main-state || exit 1
    fi

    # Main must start with this journal already hidden in its mount namespace.
    /usr/bin/python3 -I -B "${INSTALL_DIR}/kura/bin/kura_bind_service.py" provision || exit 1
    /usr/bin/python3 -I -B "${INSTALL_DIR}/kura/bin/kura_dhcp_service.py" provision || exit 1
    /usr/bin/python3 -I -B "${INSTALL_DIR}/kura/bin/kura_modem_reset.py" provision || exit 1

    # set up kura init
    # Upgrade leaves the managed unit and its enable/mask links in place. Publishing
    # a new template must not re-enable a service the operator deliberately disabled,
    # or turn runtime enablement into a persistent boot choice.
    KURA_MAIN_SERVICE_EXISTS=false
    for KURA_SERVICE_PATH in /lib/systemd/system/kura.service /usr/lib/systemd/system/kura.service /etc/systemd/system/kura.service /run/systemd/system/kura.service; do
        if [ -e "${KURA_SERVICE_PATH}" ] || [ -L "${KURA_SERVICE_PATH}" ]; then
            KURA_MAIN_SERVICE_EXISTS=true
        fi
    done
    sed "s|INSTALL_DIR|${INSTALL_DIR}|" ${INSTALL_DIR}/kura/install/kura.service > /lib/systemd/system/kura.service || exit 1
    /usr/bin/systemctl daemon-reload || exit 1
    if [ "${KURA_MAIN_SERVICE_EXISTS}" = false ] && [ ! -e /var/lib/kura-retained ]; then
        /usr/bin/systemctl enable kura.service || exit 1
    fi
    chmod +x "${INSTALL_DIR}"/kura/bin/*.sh || exit 1

    # setup snapshot_0 recovery folder
    if [ ! -d ${INSTALL_DIR}/kura/.data ]; then
        mkdir "${INSTALL_DIR}/kura/.data" || exit 1
    fi

    mkdir -p ${INSTALL_DIR}/kura/data
}

configure_brokers() {
    if [ -f /usr/lib/sysusers.d/kura-journal-export.conf ]; then
        /usr/bin/systemd-sysusers /usr/lib/sysusers.d/kura-journal-export.conf || exit 1
    fi
    if [ -f /usr/lib/sysusers.d/kura-icmp-probe.conf ]; then
        /usr/bin/systemd-sysusers /usr/lib/sysusers.d/kura-icmp-probe.conf || exit 1
    fi
    # manage running services — kura.core.clock owns NTP, so stop the system
    # time daemons. Anything network-related (NetworkManager, ModemManager,
    # dnsmasq, dhcpcd, systemd-networkd) is handled by kura-networking's own
    # install script when that sibling is installed.
    /usr/bin/systemctl daemon-reload || exit 1
    systemctl_if_present stop systemd-timesyncd
    systemctl_if_present disable systemd-timesyncd
    systemctl_if_present stop chrony
    systemctl_if_present disable chrony

    # set up users and grant permissions
    cp "${INSTALL_DIR}/kura/install/manage_kura_users.sh" "${INSTALL_DIR}/kura/.data/manage_kura_users.sh" || exit 1
    chmod 700 "${INSTALL_DIR}/kura/.data/manage_kura_users.sh" || exit 1
    # Retain the historical copy for recovery; execute the installed code only.
    bash "${INSTALL_DIR}/kura/install/manage_kura_users.sh" -i || exit 1
    python3 -I "${INSTALL_DIR}/kura/bin/kura_key_recovery_setup.py" --install || exit 1
    python3 -I -B "${INSTALL_DIR}/kura/bin/kura_clock_setup.py" install || exit 1
    for key_unit in kura-key-service.socket kura-key-service.service kura-key-recovery.service \
            kura-snapshot-validation.socket kura-snapshot-validation.service; do
        install -o root -g root -m 0644 "${INSTALL_DIR}/kura/install/${key_unit}" "/lib/systemd/system/${key_unit}" || exit 1
    done

    # D-Bus may have loaded package policies before their accounts were created.
    # Reload after account/policy installation, then require the packaged daemon.
    if [ -d /run/systemd/system ]; then
        busctl --system call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig || exit 1
        systemctl start polkit.service || exit 1
        systemctl is-active --quiet polkit.service || exit 1
    fi
}

configure_runtime() {
    bash "${INSTALL_DIR}/kura/install/customize-installation.sh" "${IS_NETWORKING_PROFILE}" || exit 1

    # copy snapshot_0.xml
    cp "${INSTALL_DIR}/kura/user/snapshots/snapshot_0.xml" "${INSTALL_DIR}/kura/.data/snapshot_0.xml" || exit 1

    # Networking setup (firewall/iptables, netplan/NM renderer, cloud-init disable,
    # /etc/network/interfaces commenting, dnsmasq, bind/named, systemd-resolved
    # stub) is owned by kura-networking. kura-core no longer touches the host's
    # network configuration so a core-only install leaves netplan/NM/iptables
    # untouched.

    # disable NTP service — kura.core.clock owns time, regardless of networking
    if command -v timedatectl > /dev/null ;
      then
        timedatectl set-ntp false
    fi

    # Main writes these files as kurad. Keep site-owned files and aliases on upgrades.
    for log_file in /var/log/kura.log /var/log/kura-audit.log /var/log/kura-console.log; do
        if [ -e "${log_file}" ] || [ -L "${log_file}" ]; then
            continue
        fi
        printf 'f %s :0600 :kurad :kurad -\n' "${log_file}" | systemd-tmpfiles --create - || exit 1
    done

    # The active logs keep their original paths. Log4j publishes its compressed
    # files in a directory writable by Main even when /var/log is root-owned.
    systemd-tmpfiles --create - <<'KURA_LOG_DIRECTORIES' || exit 1
d /var/log/kura :0700 :kurad :kurad -
d /var/log/kura/archives :0700 :kurad :kurad -
KURA_LOG_DIRECTORIES

    # set up logrotate - no need to restart as it is a cronjob
    cp "${INSTALL_DIR}/kura/install/kura.logrotate" /etc/logrotate-kura.conf || exit 1

    if [ ! -f /etc/cron.d/logrotate-kura ]; then
        test -d /etc/cron.d || mkdir -p /etc/cron.d || exit 1
        echo "*/5 * * * * root /usr/sbin/logrotate --state /var/log/logrotate-kura.status /etc/logrotate-kura.conf" > /etc/cron.d/logrotate-kura || exit 1
    fi

    # set up systemd-tmpfiles
    cp "${INSTALL_DIR}/kura/install/kura-tmpfiles.conf" /etc/tmpfiles.d/kura.conf || exit 1

    # The final ownership pass follows generation of private runtime files.
    chmod a+rx /opt/eclipse || exit 1

    # Ensure UTF-8 locale is available before generating the certificate, otherwise
    # Chinese characters in the DN will be corrupted (replaced by '?' fallback chars).
    if ! locale -a 2>/dev/null | grep -qi 'en_US.utf8\|en_US.UTF-8'; then
        if command -v locale-gen > /dev/null 2>&1; then
            locale-gen en_US.UTF-8 2>/dev/null || true
        elif command -v localedef > /dev/null 2>&1; then
            localedef -i en_US -f UTF-8 en_US.UTF-8 2>/dev/null || true
        fi
    fi
}

configure_https() {
    export LC_ALL=en_US.UTF-8

    # Existing HTTPS identity belongs to the gateway and must survive upgrades.
    HTTPS_KEYSTORE="${INSTALL_DIR}/kura/user/security/httpskeystore.ks"
    if [ -L "${HTTPS_KEYSTORE}" ] || { [ -e "${HTTPS_KEYSTORE}" ] && [ ! -f "${HTTPS_KEYSTORE}" ]; }; then
        echo "Refusing an unsafe existing HTTPS keystore; retain the gateway state." >&2
        exit 1
    fi
    if [ ! -f "${HTTPS_KEYSTORE}" ]; then
        keytool -genkey -alias localhost -keyalg RSA -keysize 2048 -keystore "${HTTPS_KEYSTORE}" -deststoretype pkcs12 -dname "CN=YOFC, OU=信息技术部, O=长飞光纤光缆股份有限公司, L=武汉, S=湖北, C=中国" -ext ku=digitalSignature,nonRepudiation,keyEncipherment,dataEncipherment,keyAgreement,keyCertSign -ext eku=serverAuth,clientAuth,codeSigning,timeStamping -validity 1000 -storepass changeit -keypass changeit || exit 1
    fi
}

configure_ownership() {
    python3 -I "${INSTALL_DIR}/kura/bin/kura_runtime_ownership.py" || exit 1
}

case "${CONFIGURE_STEP}" in
    all)
        configure_layout || exit 1
        configure_brokers || exit 1
        configure_runtime || exit 1
        configure_https || exit 1
        configure_ownership || exit 1
        ;;
    layout) configure_layout || exit 1 ;;
    brokers) configure_brokers || exit 1 ;;
    runtime) configure_runtime || exit 1 ;;
    https) configure_https || exit 1 ;;
    ownership) configure_ownership || exit 1 ;;
esac

if [ "${DEFER_KEY_SERVICE}" = false ]; then
    python3 -I "${INSTALL_DIR}/kura/bin/kura_key_service_lifecycle.py" --leave || exit 1
    systemctl daemon-reload || exit 1
    systemctl enable --now kura-key-service.socket || exit 1
    systemctl enable --now kura-key-recovery.service || exit 1
    if systemctl is-active --quiet kura-management-agent-v2.service; then
        systemctl start kura-snapshot-validation.socket || exit 1
    fi
    python3 -I -B "${INSTALL_DIR}/kura/bin/kura_clock_setup.py" resume || exit 1
fi
