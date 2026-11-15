/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.linux.watchdog;

import static org.junit.jupiter.api.Assertions.*;
import java.util.ArrayList;
import java.util.List;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.testutil.TestUtil;
import org.junit.jupiter.api.Test;

class WatchdogRebootCancellationTest {
    @Test
    void normalRebootKeepsSyncBeforeRebootUsingOnlyACommandRecorder() throws Exception {
        CommandRecorder service = new CommandRecorder();
        service.runDefaultRebootImplementation();
        assertEquals(List.of("sync", "reboot"), service.commands);
    }

    @Test
    void shutdownBetweenSyncAndRebootCancelsTheRebootCommand() {
        CommandRecorder service = new CommandRecorder();
        service.afterSync = () -> {
            try { TestUtil.setFieldValue(service, "stopping", true); }
            catch (Exception e) { throw new AssertionError(e); }
        };
        assertThrows(KuraException.class, service::runDefaultRebootImplementation);
        assertEquals(List.of("sync"), service.commands);
    }

    @Test
    void interruptionBetweenSyncAndRebootDoesNotDispatchTheReboot() {
        CommandRecorder service = new CommandRecorder();
        service.afterSync = () -> Thread.currentThread().interrupt();
        try {
            assertThrows(KuraException.class, service::runDefaultRebootImplementation);
            assertEquals(List.of("sync"), service.commands);
            assertTrue(Thread.currentThread().isInterrupted());
        } finally { Thread.interrupted(); }
    }

    @Test
    void aStoppedProviderDoesNotStartACommandSequence() throws Exception {
        CommandRecorder service = new CommandRecorder();
        TestUtil.setFieldValue(service, "stopping", true);
        assertThrows(KuraException.class, service::runDefaultRebootImplementation);
        assertTrue(service.commands.isEmpty());
    }

    private static final class CommandRecorder extends SafeWatchdogService {
        private final List<String> commands = new ArrayList<>();
        private Runnable afterSync = () -> { };
        @Override
        protected void runCommand(String command) {
            commands.add(command);
            if ("sync".equals(command)) { afterSync.run(); }
        }
    }
}
