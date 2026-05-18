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

# If ${INSTALL_DIR}/kura already exists as a real directory (e.g. an addon .deb such as
# kura-management-ui was unpacked before kura's setup ran), merge its files into the
# unpacked kura_*/ tree so they survive the symlink replacement below.
if [ -d "${INSTALL_DIR}/kura" ] && [ ! -L "${INSTALL_DIR}/kura" ]; then
    KURA_VERSION_DIR=$(ls -d ${INSTALL_DIR}/kura_*/ 2>/dev/null | head -1)
    if [ -n "${KURA_VERSION_DIR}" ]; then
        cp -rn "${INSTALL_DIR}/kura/." "${KURA_VERSION_DIR}" 2>/dev/null || true
        rm -rf "${INSTALL_DIR}/kura"
    fi
fi

# create known kura install location
ln -snf ${INSTALL_DIR}/kura_* ${INSTALL_DIR}/kura

# set up kura init
sed "s|INSTALL_DIR|${INSTALL_DIR}|" ${INSTALL_DIR}/kura/install/kura.service > /lib/systemd/system/kura.service
systemctl daemon-reload
systemctl enable kura
chmod +x ${INSTALL_DIR}/kura/bin/*.sh

# setup snapshot_0 recovery folder
if [ ! -d ${INSTALL_DIR}/kura/.data ]; then
    mkdir ${INSTALL_DIR}/kura/.data
fi

mkdir -p ${INSTALL_DIR}/kura/data

# manage running services — kura.core.clock owns NTP, so stop the system
# time daemons. Anything network-related (NetworkManager, ModemManager,
# dnsmasq, dhcpcd, systemd-networkd) is handled by kura-networking's own
# install script when that sibling is installed.
systemctl daemon-reload
systemctl_if_present stop systemd-timesyncd
systemctl_if_present disable systemd-timesyncd
systemctl_if_present stop chrony
systemctl_if_present disable chrony

# set up users and grant permissions
cp ${INSTALL_DIR}/kura/install/manage_kura_users.sh ${INSTALL_DIR}/kura/.data/manage_kura_users.sh
chmod 700 ${INSTALL_DIR}/kura/.data/manage_kura_users.sh
${INSTALL_DIR}/kura/.data/manage_kura_users.sh -i

bash "${INSTALL_DIR}/kura/install/customize-installation.sh" ${IS_NETWORKING_PROFILE}

# copy snapshot_0.xml
cp ${INSTALL_DIR}/kura/user/snapshots/snapshot_0.xml ${INSTALL_DIR}/kura/.data/snapshot_0.xml

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

# set up logrotate - no need to restart as it is a cronjob
cp ${INSTALL_DIR}/kura/install/kura.logrotate /etc/logrotate-kura.conf

if [ ! -f /etc/cron.d/logrotate-kura ]; then
    test -d /etc/cron.d || mkdir -p /etc/cron.d
    touch /etc/cron.d/logrotate-kura
    echo "*/5 * * * * root /usr/sbin/logrotate --state /var/log/logrotate-kura.status /etc/logrotate-kura.conf" >> /etc/cron.d/logrotate-kura
fi

# set up systemd-tmpfiles
cp ${INSTALL_DIR}/kura/install/kura-tmpfiles.conf /etc/tmpfiles.d/kura.conf

# set up kura files permissions
chmod 700 ${INSTALL_DIR}/kura/bin/*.sh
chown -R kurad:kurad /opt/eclipse
chmod -R go-rwx /opt/eclipse
chmod a+rx /opt/eclipse
find /opt/eclipse/kura -type d -exec chmod u+x "{}" \;

keytool -genkey -alias localhost -keyalg RSA -keysize 2048 -keystore /opt/eclipse/kura/user/security/httpskeystore.ks -deststoretype pkcs12 -dname "CN=YOFC, OU=信息技术部, O=长飞光纤光缆股份有限公司, L=武汉, S=湖北, C=中国" -ext ku=digitalSignature,nonRepudiation,keyEncipherment,dataEncipherment,keyAgreement,keyCertSign -ext eku=serverAuth,clientAuth,codeSigning,timeStamping -validity 1000 -storepass changeit -keypass changeit
