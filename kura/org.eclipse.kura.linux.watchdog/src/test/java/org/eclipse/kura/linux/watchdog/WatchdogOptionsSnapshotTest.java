/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.linux.watchdog;

import static org.junit.jupiter.api.Assertions.*;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class WatchdogOptionsSnapshotTest {
    @Test
    void callerMutationCannotRewriteAnAppliedConfigurationSnapshot() {
        Map<String, Object> original = new HashMap<>(Map.of("enabled", false, "pingInterval", 10000));
        WatchdogServiceOptions applied = new WatchdogServiceOptions(original);
        original.put("enabled", true);
        original.put("pingInterval", 20000);
        assertFalse(applied.isEnabled());
        assertEquals(10000, applied.getPingInterval());
        assertNotEquals(applied, new WatchdogServiceOptions(original));
    }

    @Test
    void nonPositiveIntervalIsRejectedBeforeAnyDeviceCanOpen() {
        for (int value : new int[] { 0, -1, Integer.MIN_VALUE }) {
            SafeWatchdogService service = new SafeWatchdogService();
            assertThrows(IllegalArgumentException.class,
                    () -> service.updated(Map.of("enabled", true, "pingInterval", value)));
        }
    }

    @Test
    void newRebootPolicyAndExistingSupervisionRemainDisabledByDefault() {
        WatchdogServiceOptions options = new WatchdogServiceOptions(Map.of());
        assertFalse(options.isEnabled());
        assertFalse(options.isFailOnUnavailableDevice());
    }
}
