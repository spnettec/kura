#!/bin/bash
#
#  Copyright (c) 2020, 2021 Eurotech and/or its affiliates and others
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

function create_users {
    # create kura user without home directory
    useradd -M kura
    # disable login for kura user
    passwd -l kura
    
    # create kurad system user without home directory
    useradd -r -M kurad
    # disable login for kurad user
    KURAD_USER_ENTRY=`cat /etc/passwd | grep kurad:`
    sed -i "s@${KURAD_USER_ENTRY}@${KURAD_USER_ENTRY%:*}:/sbin/nologin@" /etc/passwd
    passwd -l kurad
    # add kurad to dialout group (for managing serial ports)
    gpasswd -a kurad dialout
    tee /etc/sudoers.d/kurad <<< '%kurad ALL=(ALL) NOPASSWD: ALL'
    chmod 440 /etc/sudoers.d/kurad
	# get polkit package version
	trim() {
       str=""
       if [ $# -gt 0 ]; then
          str="$1"
       fi
       echo "$str" | sed -e 's/^[ \t\r\n]*//g' | sed -e 's/[ \t\r\n]*$//g'
    }
    os() {
       os=$(trim $(cat /etc/os-release 2>/dev/null | grep ^ID= | awk -F= '{print $2}'))
       if [ "$os" = "" ]; then
          os=$(trim $(lsb_release -i 2>/dev/null | awk -F: '{print $2}'))
       fi
       if [ ! "$os" = "" ]; then
          os=$(echo $os | tr '[A-Z]' '[a-z]')
       fi
       echo $os
    }
    if [ $(os) == "\"centos\"" ]; then
       POLKIT=`yum list --installed | grep polkit`
       IFS=" " POLKIT_ARRAY=($POLKIT)
	   POLKIT_VERSION=${POLKIT_ARRAY[1]}
    else
       POLKIT=`dpkg --list | grep libpolkit`
       IFS=" " POLKIT_ARRAY=($POLKIT)
	   POLKIT_VERSION=${POLKIT_ARRAY[2]}
    fi
	
    # add polkit policy
	if [[ ${POLKIT_VERSION} < 0.106 ]]; then
		if [ ! -f /etc/polkit-1/localauthority/50-local.d/51-org.freedesktop.systemd1.pkla ]; then
		    echo "[No password prompt for kurad user]
Identity=unix-user:kurad
Action=org.freedesktop.systemd1.*
ResultInactive=no
ResultActive=no
ResultAny=yes" > /etc/polkit-1/localauthority/50-local.d/51-org.freedesktop.systemd1.pkla
	    fi
	else  
	    if [ ! -f /usr/share/polkit-1/rules.d/kura.rules ]; then
	    	if [[ $NN == "NO" ]]; then
	            echo "polkit.addRule(function(action, subject) {
    if (action.id == \"org.freedesktop.systemd1.manage-units\" &&
        subject.user == \"kurad\" &&
        (action.lookup(\"unit\") == \"named.service\" ||
        action.lookup(\"unit\") == \"bluetooth.service\")) {
        return polkit.Result.YES;
    }
    if (action.id == \"org.freedesktop.systemd1.manage-unit-files\" &&
        subject.user == \"kurad\") {
        return polkit.Result.YES;
    }
});" > /usr/share/polkit-1/rules.d/kura.rules
			else
			    echo "polkit.addRule(function(action, subject) {
    if (action.id == \"org.freedesktop.systemd1.manage-units\" &&
        subject.user == \"kurad\" &&
        action.lookup(\"unit\") == \"bluetooth.service\") {
        return polkit.Result.YES;
    }
    if (action.id == \"org.freedesktop.systemd1.manage-unit-files\" &&
        subject.user == \"kurad\") {
        return polkit.Result.YES;
    }
});" > /usr/share/polkit-1/rules.d/kura.rules
			fi
	    fi
	fi
	
	# modify pam policy
	if [ -f /etc/pam.d/su ]; then
	   if [ $(os) == "\"centos\"" ]; then
          sed -i '/pam_wheel.so use_uid/a auth       [success=ignore default=1] pam_succeed_if.so user = kura\nauth       sufficient                 pam_succeed_if.so use_uid user = kurad' /etc/pam.d/su 
       else
          sed -i '/^auth       sufficient pam_rootok.so/a auth       [success=ignore default=1] pam_succeed_if.so user = kura\nauth       sufficient                 pam_succeed_if.so use_uid user = kurad' /etc/pam.d/su 
       fi		
	fi
	
        
    # grant kurad user the privileges to manage ble via dbus
    grep -lR kurad /etc/dbus-1/system.d/bluetooth.conf
    if [ $? != 0 ]; then
        cp /etc/dbus-1/system.d/bluetooth.conf /etc/dbus-1/system.d/bluetooth.conf.save
        awk 'done != 1 && /^<\/busconfig>/ {
            print "  <policy user=\"kurad\">"
            print "    <allow own=\"org.bluez\"/>"
            print "    <allow send_destination=\"org.bluez\"/>"
            print "    <allow send_interface=\"org.bluez.Agent1\"/>"
            print "    <allow send_interface=\"org.bluez.MediaEndpoint1\"/>"
            print "    <allow send_interface=\"org.bluez.MediaPlayer1\"/>"
            print "    <allow send_interface=\"org.bluez.Profile1\"/>"
            print "    <allow send_interface=\"org.bluez.GattCharacteristic1\"/>"
            print "    <allow send_interface=\"org.bluez.GattDescriptor1\"/>"
            print "    <allow send_interface=\"org.bluez.LEAdvertisement1\"/>"
            print "    <allow send_interface=\"org.freedesktop.DBus.ObjectManager\"/>"
            print "    <allow send_interface=\"org.freedesktop.DBus.Properties\"/>"
            print "  </policy>\n"
            done = 1
        } 1' /etc/dbus-1/system.d/bluetooth.conf >tempfile && mv tempfile /etc/dbus-1/system.d/bluetooth.conf
    fi
    
    # Change kura folder ownership and permission
    chown -R kurad:kurad /opt/eclipse
    chmod -R +X /opt/eclipse
}

function delete_users {
    trim() {
       str=""
       if [ $# -gt 0 ]; then
          str="$1"
       fi
       echo "$str" | sed -e 's/^[ \t\r\n]*//g' | sed -e 's/[ \t\r\n]*$//g'
    }
    os() {
       os=$(trim $(cat /etc/os-release 2>/dev/null | grep ^ID= | awk -F= '{print $2}'))
       if [ "$os" = "" ]; then
          os=$(trim $(lsb_release -i 2>/dev/null | awk -F: '{print $2}'))
       fi
       if [ ! "$os" = "" ]; then
          os=$(echo $os | tr '[A-Z]' '[a-z]')
       fi
       echo $os
    }
	# delete kura user
	userdel kura
	
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
	
	# recover pam policy
	if [ -f /etc/pam.d/su ]; then	
	   if [ $(os) == "\"centos\"" ]; then
          sed -i '/pam_wheel.so use_uid/ {n;d}' /etc/pam.d/su
		  sed -i '/pam_wheel.so use_uid/ {n;d}' /etc/pam.d/su
       else
          sed -i '/^auth       sufficient pam_rootok.so/ {n;d}' /etc/pam.d/su
		  sed -i '/^auth       sufficient pam_rootok.so/ {n;d}' /etc/pam.d/su
       fi		
	fi
	
	# recover old dbus config
	mv /etc/dbus-1/system.d/bluetooth.conf.save /etc/dbus-1/system.d/bluetooth.conf
}

INSTALL=YES
NN=NO

while [[ $# > 0 ]]
do
key="$1"

case $key in
    -i|--install)
    INSTALL=YES
    ;;
    -u|--uninstall)
    INSTALL=NO
    ;;
    -nn)
    NN=YES
    ;;
    -h|--help)
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

if [[ $INSTALL == "YES" ]]
then
    create_users
else
	delete_users
fi
