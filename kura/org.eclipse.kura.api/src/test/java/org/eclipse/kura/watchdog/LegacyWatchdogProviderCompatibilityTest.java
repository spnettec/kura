/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.watchdog;

import static org.junit.jupiter.api.Assertions.*;
import java.util.List;
import org.junit.jupiter.api.Test;

class LegacyWatchdogProviderCompatibilityTest {
    @Test
    void existingProviderCompilesAndKeepsItsOldContractWithoutClaimingAStatus() {
        WatchdogService provider = new WatchdogService() {
            public int getHardwareTimeout() { return 37000; }
            public void registerCriticalComponent(CriticalComponent component) { }
            public void unregisterCriticalComponent(CriticalComponent component) { }
            public List<CriticalComponent> getCriticalComponents() { return List.of(); }
            public void checkin(CriticalComponent component) { }
        };
        assertEquals(37000, provider.getHardwareTimeout());
        assertThrows(UnsupportedOperationException.class, provider::getWatchdogStatus);
    }
}
