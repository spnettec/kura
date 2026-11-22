/*******************************************************************************
 * Copyright (c) 2021, 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.linux.clock;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Date;
import java.util.Map;

import org.eclipse.kura.KuraException;
import org.junit.jupiter.api.Test;

public class ChronyClockSyncProviderTest {

    @Test
    void publishesOnlyNewStepsInMonotonicOrderWithoutClockWrites() throws Exception {
        ClockPrivilegeClient broker = mock(ClockPrivilegeClient.class);
        when(broker.inspectChrony()).thenReturn(new ClockPrivilegeClient.ChronyStatus("chrony.service", true));
        when(broker.stepChrony("chrony.service")).thenReturn(true);
        var first = new ClockPrivilegeClient.ChronyStep(2000000, 30);
        var laterAfterWallClockMovedBack = new ClockPrivilegeClient.ChronyStep(1000000, 31);
        when(broker.latestChronyStep()).thenReturn(first, first, new ClockPrivilegeClient.ChronyStep(0, 0),
                laterAfterWallClockMovedBack);
        ChronyClockSyncProvider provider = new ChronyClockSyncProvider(broker);
        ClockSyncListener listener = mock(ClockSyncListener.class);
        provider.init(new ClockServiceConfig(Map.of()), null, listener);

        for (int i = 0; i < 4; i++) {
            assertTrue(provider.syncClock());
        }
        assertEquals(new Date(1000), provider.getLastSync());
        verify(listener, times(2)).onClockUpdate(0, false);
        verify(broker, times(4)).stepChrony("chrony.service");
    }

    @Test
    void serviceSwitchBetweenInitAndStartDoesNotDispatchAnyCommand() throws Exception {
        ClockPrivilegeClient broker = mock(ClockPrivilegeClient.class);
        when(broker.inspectChrony()).thenReturn(new ClockPrivilegeClient.ChronyStatus("chrony.service", false),
                new ClockPrivilegeClient.ChronyStatus("chronyd.service", true));
        ChronyClockSyncProvider provider = new ChronyClockSyncProvider(broker);
        provider.init(new ClockServiceConfig(Map.of()), null, (offset, update) -> {});
        assertThrows(KuraException.class, provider::start);
        verify(broker, never()).stepChrony(anyString());
        verify(broker, never()).setChronyRunning(anyString(), anyBoolean());
    }
}
