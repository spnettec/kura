/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.linux.watchdog;

import static org.junit.jupiter.api.Assertions.*;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.watchdog.WatchdogState;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

@Timeout(15)
class WatchdogShutdownContractTest {
    @Test
    void queuedConfigurationCannotOpenADeviceAfterShutdownReturns() throws Exception {
        RecordingService service = new RecordingService();
        CountDownLatch release = new CountDownLatch(1);
        ScheduledExecutorService executor = null;
        try {
            service.activate(Map.of("enabled", false));
            executor = executor(service);
            executor.submit(() -> { }).get(2, TimeUnit.SECONDS);
            CountDownLatch entered = new CountDownLatch(1);
            executor.submit(() -> {
                entered.countDown();
                try { release.await(); }
                catch (InterruptedException e) { Thread.currentThread().interrupt(); }
            });
            assertTrue(entered.await(2, TimeUnit.SECONDS));
            service.updated(Map.of("enabled", true, "watchdogDevice", "owned-shutdown-fixture"));
            service.deactivate();
            release.countDown();
            assertTrue(executor.awaitTermination(3, TimeUnit.SECONDS));
            assertEquals(0, service.opens.get(), "Queued update must be cancelled before device open");
            assertFalse(service.getWatchdogStatus().isDeviceOpen());
        } finally {
            release.countDown();
            if (executor != null) { executor.shutdownNow(); executor.awaitTermination(3, TimeUnit.SECONDS); }
            service.deactivate();
        }
    }

    @Test
    void stoppedServiceCannotStillReportActiveSupervision() throws Exception {
        RecordingService service = new RecordingService();
        try {
            service.activate(Map.of("enabled", true, "watchdogDevice", "owned-shutdown-fixture"));
            executor(service).submit(() -> { }).get(2, TimeUnit.SECONDS);
            assertEquals(WatchdogState.SUPERVISING, service.getWatchdogStatus().getState());
            service.deactivate();
            assertFalse(service.getWatchdogStatus().isDeviceOpen());
            assertEquals(WatchdogState.DISABLED, service.getWatchdogStatus().getState());
        } finally { service.deactivate(); }
    }

    @Test
    void updateAfterShutdownIsRejectedAsALifecycleError() throws Exception {
        RecordingService service = new RecordingService();
        service.activate(Map.of("enabled", false));
        executor(service).submit(() -> { }).get(2, TimeUnit.SECONDS);
        service.deactivate();
        assertThrows(IllegalStateException.class, () -> service.updated(Map.of("enabled", true)));
    }

    @Test
    void theSameProviderCanReactivateWithTheSameConfiguration() throws Exception {
        RecordingService service = new RecordingService();
        Map<String, Object> configuration = Map.of("enabled", true, "watchdogDevice", "owned-shutdown-fixture");
        try {
            service.activate(configuration);
            executor(service).submit(() -> { }).get(2, TimeUnit.SECONDS);
            service.deactivate();
            service.activate(configuration);
            executor(service).submit(() -> { }).get(2, TimeUnit.SECONDS);
            assertEquals(2, service.opens.get());
            assertTrue(service.getWatchdogStatus().isDeviceOpen());
            assertEquals(WatchdogState.SUPERVISING, service.getWatchdogStatus().getState());
        } finally { service.deactivate(); }
    }

    @Test
    void anOpenAlreadyInProgressIsRolledBackBeforeShutdownCompletes() throws Exception {
        CountDownLatch opened = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        CountDownLatch interrupted = new CountDownLatch(1);
        AtomicInteger disarms = new AtomicInteger();
        AtomicInteger closes = new AtomicInteger();
        SafeWatchdogService service = new SafeWatchdogService() {
            protected boolean isWatchdogDeviceAvailable(String path) { return true; }
            protected WatchdogDevice createWatchdogDevice(String path) {
                opened.countDown();
                boolean restoreInterrupt = false;
                for (;;) {
                    try { release.await(); break; }
                    catch (InterruptedException e) { restoreInterrupt = true; interrupted.countDown(); }
                }
                if (restoreInterrupt) { Thread.currentThread().interrupt(); }
                return new WatchdogDevice() {
                    public void keepAlive() { }
                    public int getTimeout() { return 30; }
                    public void disarm() { disarms.incrementAndGet(); }
                    public void close() { closes.incrementAndGet(); }
                };
            }
        };
        Thread shutdown = null;
        try {
            service.activate(Map.of("enabled", true, "watchdogDevice", "owned-inflight-fixture"));
            assertTrue(opened.await(2, TimeUnit.SECONDS));
            shutdown = Thread.ofVirtual().start(service::deactivate);
            assertTrue(interrupted.await(2, TimeUnit.SECONDS));
            assertTrue(shutdown.isAlive(), "Shutdown must wait for the in-flight operation");
            release.countDown();
            shutdown.join(3000);
            assertFalse(shutdown.isAlive());
            assertEquals(1, disarms.get());
            assertEquals(1, closes.get());
            assertFalse(service.getWatchdogStatus().isDeviceOpen());
            assertEquals(WatchdogState.DISABLED, service.getWatchdogStatus().getState());
        } finally {
            release.countDown();
            if (shutdown != null) { shutdown.join(3000); }
            service.deactivate();
        }
    }

    private static ScheduledExecutorService executor(RecordingService service) throws Exception {
        return (ScheduledExecutorService) TestUtil.getFieldValue(service, "pollExecutor");
    }

    private static final class RecordingService extends SafeWatchdogService {
        private final AtomicInteger opens = new AtomicInteger();
        @Override
        protected boolean isWatchdogDeviceAvailable(String path) { return true; }
        @Override
        protected WatchdogDevice createWatchdogDevice(String path) {
            opens.incrementAndGet();
            return new WatchdogDevice() {
                public void keepAlive() { }
                public int getTimeout() { return 30; }
                public void disarm() { }
                public void close() { }
            };
        }
    }
}
