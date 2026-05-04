#!/usr/bin/env python3
#
# Copyright (c) 2024 Eurotech and/or its affiliates and others
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
import sys
import logging
import os
from network_tools import get_eth_wlan_interfaces_names

def main():
    logging.basicConfig(
        format='[customize_iptables.py] %(asctime)s %(levelname)s %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler()
        ]
    )
    
    IPTABLES_FILENAME = "/opt/eclipse/kura/.data/iptables"
    
    (eth_names, wlan_names) = get_eth_wlan_interfaces_names()
    
    eth_number = len(eth_names)
    wlan_number = len(wlan_names)
    
    if eth_number == 0:
        logging.info("ERROR: no ethernet interface found")
        exit(1)
    
    logging.info("%s : starting editing", IPTABLES_FILENAME)
    with open(IPTABLES_FILENAME, 'r', encoding='utf-8') as iptables:
        iptables_content = iptables.read()
    
    iptables_content_updated = ""
    lines = iptables_content.split("\n")
    if wlan_number == 0:
	    if eth_number == 1:
	        lines = [line for line in lines if not any(exc in line for exc in ["WIFI_INTERFACE_0","ETH_INTERFACE_1"])]
	    else:
	        lines = [line for line in lines if not any(exc in line for exc in ["WIFI_INTERFACE_0"])]
    else:
        if eth_number == 1:
            lines = [line for line in lines if not any(exc in line for exc in ["ETH_INTERFACE_1"])]
    iptables_content_updated = '\n'.join(lines)
    if eth_number > 1:
        iptables_content_updated = iptables_content_updated.replace('ETH_INTERFACE_0', eth_names[0])
        iptables_content_updated = iptables_content_updated.replace('ETH_INTERFACE_1', eth_names[1])
    else:
        iptables_content_updated = iptables_content_updated.replace('ETH_INTERFACE_0', eth_names[0])
    if wlan_number > 0:
        iptables_content_updated = iptables_content_updated.replace('WIFI_INTERFACE_0', wlan_names[0])
    
    with open(IPTABLES_FILENAME, 'w', encoding='utf-8') as iptables:
        iptables.write(iptables_content_updated)
        
    logging.info("%s : successfully edited", IPTABLES_FILENAME)
            
if __name__ == "__main__":
    main()