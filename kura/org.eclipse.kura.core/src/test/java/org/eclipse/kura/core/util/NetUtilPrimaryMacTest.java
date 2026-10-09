/*******************************************************************************
 * Copyright (c) 2017, 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 ******************************************************************************/
package org.eclipse.kura.core.util;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.when;

import java.net.NetworkInterface;
import java.util.Collections;
import java.util.List;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.MockedStatic;

class NetUtilPrimaryMacTest {
    @ParameterizedTest
    @ValueSource(strings = { "eth0", "en0" })
    void testGetPrimaryMacAddress(String name) throws Exception {
        NetworkInterface networkInterface = mock(NetworkInterface.class);
        when(networkInterface.getName()).thenReturn(name);
        when(networkInterface.getHardwareAddress()).thenReturn(new byte[] { 0, 1, 2, 3, (byte) 0x89, (byte) 0xAB });
        try (MockedStatic<NetworkInterface> interfaces = mockStatic(NetworkInterface.class)) {
            interfaces.when(NetworkInterface::getNetworkInterfaces)
                    .thenAnswer(invocation -> Collections.enumeration(List.of(networkInterface)));
            assertEquals("00:01:02:03:89:AB", NetUtil.getPrimaryMacAddress());
        }
    }
}
