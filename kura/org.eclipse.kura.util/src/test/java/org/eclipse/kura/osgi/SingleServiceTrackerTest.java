/*******************************************************************************
 * Copyright (c) 2018, 2026 Red Hat Inc and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Red Hat Inc
 *******************************************************************************/

package org.eclipse.kura.osgi;

import java.util.Dictionary;
import java.util.Hashtable;
import java.util.LinkedList;
import java.util.List;
import java.util.function.Consumer;

import org.eclipse.kura.util.osgi.SingleServiceTracker;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Assertions;
import org.junit.jupiter.api.Test;
import org.osgi.framework.BundleContext;
import org.osgi.framework.Constants;
import org.osgi.framework.ServiceRegistration;

public class SingleServiceTrackerTest extends EquinoxTestBase {

    private static final class MockConsumer<T> implements Consumer<T> {

        private T service;

        @Override
        public void accept(T t) {
            this.service = t;
        }

        public T getService() {
            return service;
        }
    }

    private static final class MockService {
    }

    private final List<SingleServiceTracker<?>> trackers = new LinkedList<>();

    private List<ServiceRegistration<?>> registrations = new LinkedList<>();

    @AfterEach
    public void unregisterAll() {
        this.trackers.forEach(SingleServiceTracker::close);
        this.registrations.forEach(ServiceRegistration::unregister);
    }

    protected <T> ServiceRegistration<T> register(final Class<T> clazz, final T service,
            final Dictionary<String, ?> properties) {

        final ServiceRegistration<T> registration = this.context.registerService(clazz, service, properties);
        this.registrations.add(registration);
        return registration;

    }

    protected void unregister(final ServiceRegistration<?> registration) {
        this.registrations.remove(registration);
        registration.unregister();
    }

    @Test
    public void testInitOrder1() {

        final MockConsumer<MockService> consumer = new MockConsumer<>();
        final SingleServiceTracker<MockService> tracker = new SingleServiceTracker<>(this.context, MockService.class,
                consumer);
        this.trackers.add(tracker);

        Assertions.assertNull(consumer.getService());

        final MockService service1 = new MockService();
        final MockService service2 = new MockService();

        final ServiceRegistration<MockService> handle2 = register(MockService.class, service2, withRanking(2));
        final ServiceRegistration<MockService> handle1 = register(MockService.class, service1, withRanking(1));

        tracker.open();
        Assertions.assertEquals(service2, consumer.getService());
        tracker.close();

        Assertions.assertNull(consumer.getService());

    }

    @Test
    public void testOrderRemove1() {

        final BundleContext context = this.context;

        final MockConsumer<MockService> consumer = new MockConsumer<>();
        final SingleServiceTracker<MockService> tracker = new SingleServiceTracker<>(context, MockService.class,
                consumer);
        this.trackers.add(tracker);

        Assertions.assertNull(consumer.getService());

        final MockService service1 = new MockService();
        final MockService service2 = new MockService();

        final ServiceRegistration<MockService> handle2 = register(MockService.class, service2, withRanking(2));
        final ServiceRegistration<MockService> handle1 = register(MockService.class, service1, withRanking(1));

        tracker.open();
        Assertions.assertEquals(service2, consumer.getService());
        unregister(handle2);
        Assertions.assertEquals(service1, consumer.getService());
        tracker.close();

        Assertions.assertNull(consumer.getService());

    }

    @Test
    public void testOrderAdd1() {

        final BundleContext context = this.context;

        final MockConsumer<MockService> consumer = new MockConsumer<>();
        final SingleServiceTracker<MockService> tracker = new SingleServiceTracker<>(context, MockService.class,
                consumer);
        this.trackers.add(tracker);

        Assertions.assertNull(consumer.getService());

        final MockService service1 = new MockService();
        final MockService service2 = new MockService();

        final ServiceRegistration<MockService> handle1 = register(MockService.class, service1, withRanking(1));

        tracker.open();
        Assertions.assertEquals(service1, consumer.getService());

        final ServiceRegistration<MockService> handle2 = register(MockService.class, service2, withRanking(2));

        Assertions.assertEquals(service2, consumer.getService());
        tracker.close();

        Assertions.assertNull(consumer.getService());

    }

    /**
     * Add new service with same ranking
     */
    @Test
    public void testOrderAdd2() {

        final BundleContext context = this.context;

        final MockConsumer<MockService> consumer = new MockConsumer<>();
        final SingleServiceTracker<MockService> tracker = new SingleServiceTracker<>(context, MockService.class,
                consumer);
        this.trackers.add(tracker);

        Assertions.assertNull(consumer.getService());

        final MockService service1 = new MockService();
        final MockService service2 = new MockService();

        final ServiceRegistration<MockService> handle1 = register(MockService.class, service1, withRanking(1));

        tracker.open();
        Assertions.assertEquals(service1, consumer.getService());

        final ServiceRegistration<MockService> handle2 = register(MockService.class, service2, withRanking(1));

        Assertions.assertEquals(service1, consumer.getService());
        tracker.close();

        Assertions.assertNull(consumer.getService());

    }

    /**
     * Add new service with a lower ranking
     */
    @Test
    public void testOrderAdd3() {

        final BundleContext context = this.context;

        final MockConsumer<MockService> consumer = new MockConsumer<>();
        final SingleServiceTracker<MockService> tracker = new SingleServiceTracker<>(context, MockService.class,
                consumer);
        this.trackers.add(tracker);

        Assertions.assertNull(consumer.getService());

        final MockService service1 = new MockService();
        final MockService service2 = new MockService();
        final MockService service3 = new MockService();

        final ServiceRegistration<MockService> handle1 = register(MockService.class, service1, withRanking(null));
        final ServiceRegistration<MockService> handle2 = register(MockService.class, service2, withRanking(null));

        tracker.open();
        Assertions.assertEquals(service1, consumer.getService());

        final ServiceRegistration<MockService> handle3 = register(MockService.class, service3, withRanking(-1));

        Assertions.assertEquals(service1, consumer.getService());
        tracker.close();

        Assertions.assertNull(consumer.getService());

    }

    @Test
    public void testOrderModify1() {

        final BundleContext context = this.context;

        final MockConsumer<MockService> consumer = new MockConsumer<>();
        final SingleServiceTracker<MockService> tracker = new SingleServiceTracker<>(context, MockService.class,
                consumer);
        this.trackers.add(tracker);

        Assertions.assertNull(consumer.getService());

        final MockService service1 = new MockService();
        final MockService service2 = new MockService();

        final ServiceRegistration<MockService> handle2 = register(MockService.class, service2, withRanking(2));
        final ServiceRegistration<MockService> handle1 = register(MockService.class, service1, withRanking(1));

        tracker.open();
        Assertions.assertEquals(service2, consumer.getService());
        handle1.setProperties(withRanking(3));
        Assertions.assertEquals(service1, consumer.getService());
        tracker.close();

        Assertions.assertNull(consumer.getService());

    }

    @Test
    public void testOrderModify2() {

        final BundleContext context = this.context;

        final MockConsumer<MockService> consumer = new MockConsumer<>();
        final SingleServiceTracker<MockService> tracker = new SingleServiceTracker<>(context, MockService.class,
                consumer);
        this.trackers.add(tracker);

        Assertions.assertNull(consumer.getService());

        final MockService service1 = new MockService();
        final MockService service2 = new MockService();

        final ServiceRegistration<MockService> handle1 = register(MockService.class, service1, withRanking(null));
        final ServiceRegistration<MockService> handle2 = register(MockService.class, service2, withRanking(2));

        tracker.open();
        Assertions.assertEquals(service2, consumer.getService());
        handle1.setProperties(withRanking(3));
        Assertions.assertEquals(service1, consumer.getService());
        tracker.close();

        Assertions.assertNull(consumer.getService());

    }

    @Test
    public void testOrderModify3() throws InterruptedException {

        final BundleContext context = this.context;

        final MockConsumer<MockService> consumer = new MockConsumer<>();
        final SingleServiceTracker<MockService> tracker = new SingleServiceTracker<>(context, MockService.class,
                consumer);
        this.trackers.add(tracker);

        Assertions.assertNull(consumer.getService());

        final MockService service1 = new MockService();
        final MockService service2 = new MockService();

        final ServiceRegistration<MockService> handle1 = register(MockService.class, service1, withRanking(1));
        final ServiceRegistration<MockService> handle2 = register(MockService.class, service2, withRanking(1));

        tracker.open();

        // expect the first registered service
        Assertions.assertEquals(service1, consumer.getService());

        // update, but don't change ranking
        handle1.setProperties(withRanking(1));

        // should still be the same service
        Assertions.assertEquals(service1, consumer.getService());

        // change ranking

        handle2.setProperties(withRanking(2));
        Assertions.assertEquals(service2, consumer.getService());

        tracker.close();

        Assertions.assertNull(consumer.getService());

    }

    /**
     * Add new service with same ranking
     */
    @Test
    public void testOrder1() {

        final BundleContext context = this.context;

        final MockConsumer<MockService> consumer = new MockConsumer<>();
        final SingleServiceTracker<MockService> tracker = new SingleServiceTracker<>(context, MockService.class,
                consumer);
        this.trackers.add(tracker);

        Assertions.assertNull(consumer.getService());

        final MockService service1 = new MockService();
        final MockService service2 = new MockService();
        final MockService service3 = new MockService();

        final ServiceRegistration<MockService> handle1 = register(MockService.class, service1, withRanking(1));
        final ServiceRegistration<MockService> handle2 = register(MockService.class, service2, withRanking(1));
        final ServiceRegistration<MockService> handle3 = register(MockService.class, service3, withRanking(2));

        tracker.open();

        Assertions.assertEquals(service3, consumer.getService());

        unregister(handle3);
        Assertions.assertEquals(service1, consumer.getService());

        tracker.close();

        Assertions.assertNull(consumer.getService());
    }

    private Dictionary<String, ?> withRanking(final Integer ranking) {
        final Hashtable<String, Object> properties = new Hashtable<>();
        if (ranking != null) {
            properties.put(Constants.SERVICE_RANKING, ranking);
        }
        return properties;
    }
}
