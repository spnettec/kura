/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.event.publisher.test;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import org.eclipse.kura.cloudconnection.listener.CloudConnectionListener;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.event.publisher.EventPublisher;
import org.eclipse.kura.event.publisher.helper.CloudEndpointServiceHelper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.MockedConstruction;
import org.osgi.framework.BundleContext;
import org.osgi.service.component.ComponentContext;

class EventPublisherLifecycleTest {
    private final ComponentContext context = mock(ComponentContext.class);
    private MockedConstruction<CloudEndpointServiceHelper> helpers;
    private EventPublisher publisher;
    private ExecutorService worker;

    @BeforeEach
    void activate() throws Exception {
        this.helpers = mockConstruction(CloudEndpointServiceHelper.class);
        when(this.context.getBundleContext()).thenReturn(mock(BundleContext.class));
        this.publisher = new EventPublisher();
        this.publisher.activate(this.context, Map.of());
        this.worker = (ExecutorService) TestUtil.getFieldValue(this.publisher, "worker");
    }

    @AfterEach
    void cleanup() throws Exception {
        try {
            for (CloudEndpointServiceHelper helper : this.helpers.constructed()) {
                doNothing().when(helper).close();
            }
            this.publisher.deactivate(this.context);
        } finally {
            this.worker.shutdownNow();
            assertTrue(this.worker.awaitTermination(5, TimeUnit.SECONDS));
            this.helpers.close();
        }
    }

    @Test
    void shouldClosePreviousEndpointOnUpdate() {
        CloudEndpointServiceHelper previous = this.helpers.constructed().getFirst();
        this.publisher.updated(Map.of("topic", "next"));
        verify(previous).close();
        CloudEndpointServiceHelper current = this.helpers.constructed().getLast();
        assertNotSame(previous, current);
        verify(current, never()).close();
        this.publisher.deactivate(this.context);
        verify(current).close();
    }

    @Test
    void shouldStopOwnedWorkerAfterDeliveringCallbacks() throws Exception {
        CloudConnectionListener listener = mock(CloudConnectionListener.class);
        CountDownLatch delivered = new CountDownLatch(1);
        AtomicBoolean virtual = new AtomicBoolean();
        doAnswer(call -> {
            virtual.set(Thread.currentThread().isVirtual());
            delivered.countDown();
            return null;
        }).when(listener).onConnectionEstablished();
        this.publisher.registerCloudConnectionListener(listener);
        this.publisher.onConnectionEstablished();
        assertTrue(delivered.await(5, TimeUnit.SECONDS));
        assertTrue(virtual.get());
        this.publisher.deactivate(this.context);
        assertTrue(this.worker.isShutdown(), "Owned callback executor is still accepting tasks");
        assertTrue(this.worker.awaitTermination(5, TimeUnit.SECONDS));
    }

    @Test
    void shouldStopWorkerIfEndpointCleanupFails() throws Exception {
        IllegalStateException failure = new IllegalStateException("endpoint cleanup failed");
        doThrow(failure).when(this.helpers.constructed().getFirst()).close();
        assertSame(failure, assertThrows(IllegalStateException.class, () -> this.publisher.deactivate(this.context)));
        assertTrue(this.worker.isShutdown(), "Cleanup failure retained the callback executor");
        assertTrue(this.worker.awaitTermination(5, TimeUnit.SECONDS));
    }
}
