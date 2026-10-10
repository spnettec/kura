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
package org.eclipse.kura.watchdog.criticaltest;

import static org.junit.jupiter.api.Assertions.*;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.linux.watchdog.CriticalComponentRegistration;
import org.eclipse.kura.linux.watchdog.WatchdogServiceImpl;
import org.junit.jupiter.api.Test;

class FailingCriticalComponentTest {
    @Test
    void registersAndExpiresWithoutCheckinThenUnregisters() throws Exception {
        WatchdogServiceImpl watchdog = new WatchdogServiceImpl();
        List<CriticalComponentRegistration> registrations = new CopyOnWriteArrayList<>();
        TestUtil.setFieldValue(watchdog, "criticalComponentRegistrations", registrations);
        FailingCriticalComponent component = new FailingCriticalComponent();
        component.bindWatchdogService(watchdog);
        try {
            component.activate(null, Map.of(ConfigurationService.KURA_SERVICE_PID, "critical-test"));
            assertEquals(List.of(component), watchdog.getCriticalComponents());
            assertEquals("critical-test", component.getCriticalComponentName());
            assertEquals(30000, component.getCriticalComponentTimeout());
            CriticalComponentRegistration registration = registrations.get(0);
            assertFalse(registration.isTimedOut());
            TestUtil.setFieldValue(registration, "updated", System.nanoTime() - TimeUnit.SECONDS.toNanos(31));
            assertTrue(registration.isTimedOut());
        } finally {
            component.deactivate(null);
            component.unbindWatchdogService(watchdog);
        }
        assertTrue(watchdog.getCriticalComponents().isEmpty());
    }
}
