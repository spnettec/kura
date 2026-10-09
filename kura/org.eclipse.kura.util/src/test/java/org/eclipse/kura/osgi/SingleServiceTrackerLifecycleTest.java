/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.osgi;

import static org.junit.jupiter.api.Assertions.*;

import java.util.Hashtable;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.eclipse.kura.util.osgi.SingleServiceTracker;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.osgi.framework.Bundle;
import org.osgi.framework.Constants;
import org.osgi.framework.ServiceFactory;
import org.osgi.framework.ServiceRegistration;

class SingleServiceTrackerLifecycleTest extends EquinoxTestBase {

    @Test
    void shouldReleaseEveryAcquiredServiceOnClose() {
        Factory first = new Factory();
        Factory second = new Factory();
        ServiceRegistration<?> one = register(first, 1);
        ServiceRegistration<?> two = register(second, 2);
        SingleServiceTracker<Runnable> tracker = new SingleServiceTracker<>(this.context, Runnable.class, service -> { });
        try {
            tracker.open();
            assertSame(second.service, tracker.getService());
            assertEquals(1, first.acquired.get());
            assertEquals(1, second.acquired.get());
            tracker.close();
            tracker.close();
            assertNull(tracker.getService());
            assertAll(() -> assertEquals(1, first.released.get()),
                    () -> assertEquals(1, second.released.get()),
                    () -> assertNull(one.getReference().getUsingBundles()),
                    () -> assertNull(two.getReference().getUsingBundles()));
        } finally {
            tracker.close();
            one.unregister();
            two.unregister();
        }
    }

    @ParameterizedTest
    @ValueSource(booleans = { true, false })
    void shouldReleaseServiceThatStopsMatching(boolean selected) throws Exception {
        Factory changed = new Factory();
        Factory remaining = new Factory();
        ServiceRegistration<?> one = register(changed, selected ? 2 : 0);
        ServiceRegistration<?> two = register(remaining, 1);
        SingleServiceTracker<Runnable> tracker = new SingleServiceTracker<>(this.context,
                this.context.createFilter("(&(objectClass=java.lang.Runnable)(enabled=true))"), service -> { });
        try {
            tracker.open();
            assertEquals(1, changed.acquired.get());
            assertSame(selected ? changed.service : remaining.service, tracker.getService());
            one.setProperties(new Hashtable<>(Map.of("enabled", false)));
            assertSame(remaining.service, tracker.getService());
            assertAll(() -> assertEquals(1, changed.released.get()),
                    () -> assertNull(one.getReference().getUsingBundles()));
        } finally {
            tracker.close();
            one.unregister();
            two.unregister();
        }
    }

    private ServiceRegistration<?> register(Factory factory, int ranking) {
        return this.context.registerService(Runnable.class.getName(), factory,
                new Hashtable<>(Map.of(Constants.SERVICE_RANKING, ranking, "enabled", true)));
    }

    private static class Factory implements ServiceFactory<Runnable> {
        private final Runnable service = new Runnable() {
            @Override
            public void run() { }
        };
        private final AtomicInteger acquired = new AtomicInteger();
        private final AtomicInteger released = new AtomicInteger();

        @Override
        public Runnable getService(Bundle bundle, ServiceRegistration<Runnable> registration) {
            this.acquired.incrementAndGet();
            return this.service;
        }

        @Override
        public void ungetService(Bundle bundle, ServiceRegistration<Runnable> registration, Runnable instance) {
            assertSame(this.service, instance);
            this.released.incrementAndGet();
        }
    }
}
