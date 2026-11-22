/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.core.status;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.core.status.runnables.StatusRunnable;
import org.eclipse.kura.status.CloudConnectionStatusEnum;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

class LedBlinkTimingTest {

    @ParameterizedTest
    @EnumSource(value = CloudConnectionStatusEnum.class, names = { "FAST_BLINKING", "SLOW_BLINKING" })
    void statusSelectsItsOwnBlinkCadenceWithoutGpio(CloudConnectionStatusEnum status) throws Exception {
        CloudConnectionStatusServiceImpl service = new CloudConnectionStatusServiceImpl();
        RecordingLed led = new RecordingLed();
        Method factory = CloudConnectionStatusServiceImpl.class.getDeclaredMethod("createLedRunnable",
                CloudConnectionStatusEnum.class, LedManager.class);
        factory.setAccessible(true);
        StatusRunnable worker = (StatusRunnable) factory.invoke(service, status, led);
        Thread thread = Thread.ofVirtual().unstarted(worker);
        try {
            thread.start();
            assertTrue(led.observed.await(8, TimeUnit.SECONDS), "LED cadence did not produce enough transitions");
        } finally {
            worker.stopRunnable();
            thread.interrupt();
            thread.join(1000);
            Field executor = CloudConnectionStatusServiceImpl.class.getDeclaredField("notificationExecutor");
            executor.setAccessible(true);
            ((ExecutorService) executor.get(service)).shutdownNow();
        }
        assertFalse(thread.isAlive(), "Blink worker must terminate after interruption");
        boolean fast = status == CloudConnectionStatusEnum.FAST_BLINKING;
        long min = fast ? 60 : 250;
        long max = fast ? 240 : 1200;
        for (boolean on : new boolean[] { true, false }) {
            long median = led.medianPhaseMillis(on);
            assertTrue(median >= min && median < max,
                    () -> status + " " + (on ? "on" : "off") + " median phase was " + median + " ms");
        }
    }

    private static final class RecordingLed implements LedManager {
        private final CountDownLatch observed = new CountDownLatch(9);
        private final List<Boolean> values = new ArrayList<>();
        private final List<Long> times = new ArrayList<>();

        @Override
        public synchronized void writeLed(boolean enabled) {
            this.values.add(enabled);
            this.times.add(System.nanoTime());
            this.observed.countDown();
        }

        synchronized long medianPhaseMillis(boolean enabled) {
            List<Long> phases = new ArrayList<>();
            for (int i = 1; i < this.values.size(); i++) {
                if (this.values.get(i - 1) == enabled) {
                    phases.add(TimeUnit.NANOSECONDS.toMillis(this.times.get(i) - this.times.get(i - 1)));
                }
            }
            phases.sort(Long::compareTo);
            return phases.get(phases.size() / 2);
        }
    }
}
