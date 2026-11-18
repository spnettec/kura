/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.linux.watchdog;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

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

    @Test
    void nonzeroExitOfLaunchedRebootDoesNotRedispatch() throws Exception {
        Process process = mock(Process.class);
        when(process.waitFor(60, TimeUnit.SECONDS)).thenReturn(true);
        when(process.exitValue()).thenReturn(1);
        assertNoRedispatch(process);
    }

    @Test
    void rebootReplyTimeoutDoesNotRedispatch() throws Exception {
        Process process = mock(Process.class);
        when(process.waitFor(60, TimeUnit.SECONDS)).thenReturn(false);
        assertNoRedispatch(process);
    }

    @Test
    void interruptedRebootReplyDoesNotRedispatch() throws Exception {
        Process process = mock(Process.class);
        when(process.waitFor(60, TimeUnit.SECONDS)).thenThrow(new InterruptedException("reply interrupted"));
        assertNoRedispatch(process);
    }

    private void assertNoRedispatch(Process process) throws Exception {
        ReplyRecorder service = new ReplyRecorder(process);
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
        private final Process process;
        private final CountDownLatch launched = new CountDownLatch(1);
        private final AtomicInteger attempts = new AtomicInteger();

        private ReplyRecorder(Process process) {
            this.process = process;
        }

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
        protected void runCommand(String command) throws KuraException {
            if ("reboot".equals(command)) {
                runDefaultCommandImplementation(command);
            } else {
                assertEquals("sync", command);
            }
        }

        @Override
        protected Process startCommand(String command) {
            assertEquals("reboot", command);
            this.attempts.incrementAndGet();
            this.launched.countDown();
            return this.process;
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
    }
}
