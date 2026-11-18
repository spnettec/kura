#!/bin/bash
#
#  Copyright (c) 2020, 2024 Eurotech and/or its affiliates and others
#
#  This program and the accompanying materials are made
#  available under the terms of the Eclipse Public License 2.0
#  which is available at https://www.eclipse.org/legal/epl-2.0/
#
#  SPDX-License-Identifier: EPL-2.0
#
#  Contributors:
#   Eurotech
#

function require_modern_polkit {
    local package_info version
    package_info=$(dpkg-query -W -f='${db:Status-Status} ${Version}' polkitd 2>/dev/null) || {
        echo "Kura requires a configured polkitd package (>= 0.106)." >&2
        return 1
    }
    case "${package_info}" in
        installed\ *) version="${package_info#installed }" ;;
        *) echo "Configure polkitd before installing Kura." >&2; return 1 ;;
    esac
    if ! dpkg --validate-version "${version}" >/dev/null 2>&1 ||
        ! dpkg --compare-versions "${version#*:}" ge 0.106; then
        echo "Kura requires the JavaScript polkit backend (polkitd >= 0.106)." >&2
        return 1
    fi
}

function manage_su_pam_policy {
    local helper_dir
    helper_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../bin" && pwd) || return 1
    python3 -I "${helper_dir}/kura_su_pam.py" "$1"
}

# Backups have no .rules/.pkla suffix, so neither polkit backend loads them.
# Never discard a previous local rule while replacing the package's policy.
function archive_kura_polkit_file {
    local policy_file="$1"
    if [ -L "${policy_file}" ] || { [ -e "${policy_file}" ] && [ ! -f "${policy_file}" ]; }; then
        echo "Refusing non-regular Kura polkit policy: ${policy_file}" >&2
        return 1
    fi
    [ -e "${policy_file}" ] || return 0
    local digest backup
    digest=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "${policy_file}") || return 1
    backup="${policy_file}.${digest}.kurasave"
    if [ -L "${backup}" ] || { [ -e "${backup}" ] && ! cmp -s "${policy_file}" "${backup}"; }; then
        echo "Refusing conflicting Kura polkit backup: ${backup}" >&2
        return 1
    fi
    if [ ! -e "${backup}" ]; then
        cp -p "${policy_file}" "${backup}" && chmod 600 "${backup}" || return 1
    fi
}

function write_systemd_polkit_policy {
    local rules_dir="${1:-/usr/share/polkit-1/rules.d}"
    local legacy_file="${2:-/etc/polkit-1/localauthority/50-local.d/51-org.freedesktop.systemd1.pkla}"
    local allow_dns=false policy_file temporary
    case "${NN:-NO}" in
        NO) allow_dns=true ;;
        YES) ;;
        *) echo "Invalid Kura networking profile" >&2; return 1 ;;
    esac
    mkdir -p "${rules_dir}" || return 1
    policy_file="${rules_dir}/kura.rules"
    # Check and preserve the old backend grant before changing either policy.
    archive_kura_polkit_file "${legacy_file}" || return 1
    if [ -L "${policy_file}" ] || { [ -e "${policy_file}" ] && [ ! -f "${policy_file}" ]; }; then
        echo "Refusing non-regular Kura polkit policy: ${policy_file}" >&2
        return 1
    fi
    temporary=$(mktemp "${rules_dir}/.kura.rules.XXXXXX") || return 1
    if ! cat >"${temporary}" <<EOF
// Managed by Kura. Put site overrides in /etc/polkit-1/rules.d/.
polkit.addRule(function(action, subject) {
    if (subject.user != "kurad") {
        return;
    }
    if (action.id == "org.freedesktop.systemd1.manage-units") {
        var unit = action.lookup("unit");
        var verb = action.lookup("verb");
        var startOrStop = verb == "start" || verb == "stop";
        var clock = unit == "chrony.service" || unit == "chronyd.service";
        var dns = ${allow_dns} && (unit == "named.service" || unit == "bind9.service");
        if ((clock && startOrStop) || (dns && (startOrStop || verb == "restart"))) {
            return polkit.Result.YES;
        }
        return polkit.Result.NO;
    }
    // manage-unit-files implies arbitrary manage-units and reload-daemon.
    // Unit-file installation belongs to the root package installer.
    if (action.id.indexOf("org.freedesktop.systemd1.") == 0) {
        return polkit.Result.NO;
    }
    if (action.id == "org.freedesktop.login1.reboot-multiple-sessions" ||
        action.id == "org.freedesktop.login1.suspend-multiple-sessions" ||
        action.id == "org.freedesktop.login1.power-off-multiple-sessions") {
        return polkit.Result.YES;
    }
});
EOF
    then
        rm -f "${temporary}"
        return 1
    fi
    if ! chmod 644 "${temporary}"; then
        rm -f "${temporary}"
        return 1
    fi
    if [ -f "${policy_file}" ] && cmp -s "${temporary}" "${policy_file}"; then
        rm -f "${temporary}"
    else
        if ! archive_kura_polkit_file "${policy_file}" || ! mv -f "${temporary}" "${policy_file}"; then
            rm -f "${temporary}"
            return 1
        fi
    fi
    # A retained legacy wildcard would bypass the new service restrictions.
    [ ! -e "${legacy_file}" ] || rm -f "${legacy_file}" || return 1
}

function create_users {
    require_modern_polkit || return 1
    manage_su_pam_policy check || return 1
    # create kura user without home directory
    useradd -M kura
    # disable login for kura user
    passwd -l kura

    # create kurad system user without home directory
    useradd -r -M kurad
    # disable login for kurad user
    KURAD_USER_ENTRY=$(cat /etc/passwd | grep kurad:)
    sed -i "s@${KURAD_USER_ENTRY}@${KURAD_USER_ENTRY%:*}:/sbin/nologin@" /etc/passwd
    passwd -l kurad
    # add kurad to dialout group (for managing serial ports)
    gpasswd -a kurad dialout

    # The formal Ubuntu 24.04/26.04 release uses the JavaScript backend.
    write_systemd_polkit_policy || return 1
    if [[ $NN == "NO" ]]; then
            if [ ! -f /usr/share/polkit-1/rules.d/kura-nm.rules ]; then
                echo "polkit.addRule(function(action, subject) {
        if ((action.id.indexOf(\"org.freedesktop.NetworkManager.\") == 0 ||
            action.id.indexOf(\"org.freedesktop.ModemManager1.\") == 0 ||
            action.id.indexOf(\"fi.w1.wpa_supplicant1.\") == 0) &&
            subject.user == \"kurad\") {
            return polkit.Result.YES;
        }
    });" >/usr/share/polkit-1/rules.d/kura-nm.rules
            fi
    fi

    # Keep the target restriction and caller grant in one atomic PAM update.
    manage_su_pam_policy install || return 1

    # Bluetooth support was removed from this YOFC distribution.

    # grant kurad user the privileges to manage wpa supplicant via dbus
    if [ -f /etc/dbus-1/system.d/wpa_supplicant.conf ] && ! grep -q kurad /etc/dbus-1/system.d/wpa_supplicant.conf && [ $NN == "NO" ]; then
        cp /etc/dbus-1/system.d/wpa_supplicant.conf /etc/dbus-1/system.d/wpa_supplicant.conf.save
        awk 'done != 1 && /^<\/busconfig>/ {
            print "    <policy user=\"kurad\">"
            print "        <allow own=\"fi.w1.wpa_supplicant1\"/>"
            print "        <allow send_destination=\"fi.w1.wpa_supplicant1\"/>"
            print "        <allow send_interface=\"fi.w1.wpa_supplicant1\"/>"
            print "        <allow receive_sender=\"fi.w1.wpa_supplicant1\" receive_type=\"signal\"/>"
            print "    </policy>\n"
            done = 1
        } 1' /etc/dbus-1/system.d/wpa_supplicant.conf >tempfile && mv tempfile /etc/dbus-1/system.d/wpa_supplicant.conf
    fi

    # Code and root installer helpers must not belong to the running daemon.
    python3 -I /opt/eclipse/kura/bin/kura_runtime_ownership.py || return 1
}

function delete_users {
    # The locked recovery account/control group and independent TLS/journal are
    # retained with their UID/GID. Package lifecycle removes both listeners.
    # Revoke both halves before changing any account or other host policy.
    manage_su_pam_policy remove || return 1
    # A retained reinstall must keep the numeric owners of copied user data.
    # Both accounts are already locked; revoke grants without recycling a UID.
    if [ ! -e /var/lib/kura-retained ]; then
        userdel kura || return 1
    fi

    # we cannot delete kurad system user because there should be several process owned by this user,
    # so only try to remove it from sudoers.
    if [ -f /etc/sudoers.d/kurad ]; then
        rm -f /etc/sudoers.d/kurad
    fi
    # remove kurad from dialout group
    gpasswd -d kurad dialout

    # remove polkit policy
    if [ -f /usr/share/polkit-1/rules.d/kura.rules ]; then
        rm -f /usr/share/polkit-1/rules.d/kura.rules
    fi
    if [ -f /etc/polkit-1/localauthority/50-local.d/51-org.freedesktop.systemd1.pkla ]; then
        rm -f /etc/polkit-1/localauthority/50-local.d/51-org.freedesktop.systemd1.pkla
    fi
    if [ -f /etc/polkit-1/localauthority/50-local.d/52-org.freedesktop.networkmanager.pkla ]; then
        rm -f /etc/polkit-1/localauthority/50-local.d/52-org.freedesktop.networkmanager.pkla
    fi
    if [ -f /etc/polkit-1/localauthority/50-local.d/53-org.freedesktop.modemmanager.pkla ]; then
        rm -f /etc/polkit-1/localauthority/50-local.d/53-org.freedesktop.modemmanager.pkla
    fi
    if [ -f /etc/polkit-1/localauthority/50-local.d/54-fi.w1.wpa_supplicant1.pkla ]; then
        rm -f /etc/polkit-1/localauthority/50-local.d/54-fi.w1.wpa_supplicant1.pkla
    fi

    # recover old configs
    if [ -f /etc/dbus-1/system.d/bluetooth.conf.save ]; then
        mv /etc/dbus-1/system.d/bluetooth.conf.save /etc/dbus-1/system.d/bluetooth.conf
    fi
    if [ -f /etc/dbus-1/system.d/wpa_supplicant.conf.save ]; then
        mv /etc/dbus-1/system.d/wpa_supplicant.conf.save /etc/dbus-1/system.d/wpa_supplicant.conf
    fi
}

INSTALL=YES
NN=NO

while [[ $# > 0 ]]; do
    key="$1"

    case $key in
    --check-polkit)
        # Internal installer preflight; no accounts, files or services are changed.
        require_modern_polkit
        exit $?
        ;;
    --check-pam)
        # Internal read-only preflight; preserve site policy on rejection.
        manage_su_pam_policy check
        exit $?
        ;;
    -i | --install)
        INSTALL=YES
        ;;
    -u | --uninstall)
        INSTALL=NO
        ;;
    -nn)
        NN=YES
        ;;
    -h | --help)
        echo
        echo "Options:"
        echo "    -i | --install    create kura default users"
        echo "    -u | --uninstall  delete kura default users"
        echo "    -nn               set kura no network version"
        echo "Default: --install"
        exit 0
        ;;
    *)
        echo "Unknown option."
        exit 1
        ;;
    esac
    shift # past argument or value
done

if [[ $INSTALL == "YES" ]]; then
    create_users
else
    delete_users
fi
