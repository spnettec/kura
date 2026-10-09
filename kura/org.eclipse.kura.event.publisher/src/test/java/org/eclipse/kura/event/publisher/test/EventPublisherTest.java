/*******************************************************************************
 * Copyright (c) 2021, 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *
 * Contributors:
 *  Eurotech
 *******************************************************************************/
package org.eclipse.kura.event.publisher.test;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;

import org.eclipse.kura.event.publisher.helper.CloudEndpointServiceHelper;
import org.eclipse.kura.core.testutil.TestUtil;
import org.eclipse.kura.event.publisher.EventPublisher;
import org.eclipse.kura.cloudconnection.message.KuraMessage;
import org.eclipse.kura.message.KuraPayload;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.MockedConstruction;
import org.osgi.framework.BundleContext;
import org.osgi.service.component.ComponentContext;

class EventPublisherTest {
    private final ComponentContext context = mock(ComponentContext.class);
    private MockedConstruction<CloudEndpointServiceHelper> helpers;
    private EventPublisher publisher;
    private CloudEndpointServiceHelper endpoint;

    @BeforeEach
    void activate() {
        this.helpers = mockConstruction(CloudEndpointServiceHelper.class);
        when(this.context.getBundleContext()).thenReturn(mock(BundleContext.class));
        this.publisher = new EventPublisher();
        this.publisher.activate(this.context, Map.of("topic.prefix", "$EVT", "topic", "EVENT_TOPIC"));
        this.endpoint = this.helpers.constructed().getFirst();
    }

    @AfterEach
    void deactivate() throws Exception {
        try {
            this.publisher.deactivate(this.context);
            verify(this.endpoint).close();
        } finally {
            ExecutorService worker = (ExecutorService) TestUtil.getFieldValue(this.publisher, "worker");
            assertTrue(worker.isShutdown());
            assertTrue(worker.awaitTermination(5, TimeUnit.SECONDS));
            this.helpers.close();
        }
    }

    @Test
    void nullMessageShouldThrowException() {
        assertThrows(IllegalArgumentException.class, () -> this.publisher.publish(null));
        verifyNoInteractions(this.endpoint);
    }

    @Test
    void shouldPublishMessageCorrectly() throws Exception {
        KuraPayload payload = new KuraPayload();
        payload.setBody("test-body 数据".getBytes(StandardCharsets.UTF_8));
        when(this.endpoint.publish(any())).thenReturn("message-id");
        assertEquals("message-id", this.publisher.publish(new KuraMessage(payload)));
        ArgumentCaptor<KuraMessage> capture = ArgumentCaptor.forClass(KuraMessage.class);
        verify(this.endpoint).publish(capture.capture());
        assertSame(payload, capture.getValue().getPayload());
        assertEquals(Map.of("FULL_TOPIC", "$EVT/#account-name/#client-id/EVENT_TOPIC", "QOS", 0,
                "RETAIN", false, "PRIORITY", 7, "CONTROL", true), capture.getValue().getProperties());
    }
}
