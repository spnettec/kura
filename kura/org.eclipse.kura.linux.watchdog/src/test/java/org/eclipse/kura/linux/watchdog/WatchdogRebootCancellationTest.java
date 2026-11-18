/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.linux.watchdog;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.system.reboot.RebootBrokerClient.Outcome;
import org.eclipse.kura.core.testutil.TestUtil;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class WatchdogRebootCancellationTest {
    @TempDir
    private Path temporaryDirectory;

    @Test
    void normalRebootKeepsSyncBeforeRebootUsingOnlyACommandRecorder() throws Exception {
        CommandRecorder service = new CommandRecorder();
        service.runDefaultRebootImplementation();
        assertEquals(List.of("sync", "broker"), service.commands);
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

    @Test
    void unknownBrokerOutcomeDoesNotRedispatchEvenOnDeviceReconfiguration() throws Exception {
        ReplyRecorder service = new ReplyRecorder();
        Path initialCause = this.temporaryDirectory.resolve("reboot-cause");
        Path nextCause = this.temporaryDirectory.resolve("changed-cause");
        service.activate(unavailableDevice("first-test-device", initialCause));
        try {
            assertTrue(service.launched.await(5, TimeUnit.SECONDS));
            ScheduledExecutorService loop = (ScheduledExecutorService) TestUtil.getFieldValue(service, "pollExecutor");
            loop.schedule(() -> { }, 120, TimeUnit.MILLISECONDS).get(5, TimeUnit.SECONDS);
            assertEquals(1, service.attempts.get());
            service.updated(unavailableDevice("other-test-device", nextCause));
            loop.schedule(() -> { }, 120, TimeUnit.MILLISECONDS).get(5, TimeUnit.SECONDS);
            assertEquals(1, service.attempts.get());
            assertTrue(Files.exists(initialCause));
            assertFalse(Files.exists(nextCause));
        } finally {
            service.deactivate();
        }
    }

    private static Map<String, Object> unavailableDevice(String device, Path cause) {
        return Map.of("enabled", true, "watchdogDevice", device, "rebootCauseFilePath", cause.toString(),
                "failOnUnavailableDevice", true, "pingInterval", 10);
    }

    private static final class ReplyRecorder extends SafeWatchdogService {
        private final CountDownLatch launched = new CountDownLatch(1);
        private final AtomicInteger attempts = new AtomicInteger();

        @Override
        protected boolean isWatchdogDeviceAvailable(String path) {
            return false;
        }

        @Override
        protected long getGracePeriod() {
            return 20;
        }

        @Override
        protected long getRebootRetryInterval() {
            return 10;
        }

        @Override
        protected synchronized void rebootSystem() throws KuraException {
            runDefaultRebootImplementation();
        }

        @Override
        protected void runCommand(String command) {
            assertEquals("sync", command);
        }

        @Override
        protected Outcome requestBrokerReboot() {
            this.attempts.incrementAndGet();
            this.launched.countDown();
            return Outcome.UNKNOWN;
        }
    }

    private static final class CommandRecorder extends SafeWatchdogService {
        private final List<String> commands = new ArrayList<>();
        private Runnable afterSync = () -> { };
        @Override
        protected void runCommand(String command) {
            commands.add(command);
            if ("sync".equals(command)) { afterSync.run(); }
        }

        @Override
        protected Outcome requestBrokerReboot() {
            commands.add("broker");
            return Outcome.ACCEPTED;
        }
    }
}
