/*******************************************************************************
 * Copyright (c) 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0, available at
 * https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.internal.rest.body;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.util.concurrent.atomic.AtomicReference;

import org.eclipse.kura.internal.rest.body.annotation.MaxRequestBodySize;
import org.junit.jupiter.api.Test;

import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.container.ResourceInfo;
import jakarta.ws.rs.core.HttpHeaders;
import jakarta.ws.rs.core.MultivaluedHashMap;
import jakarta.ws.rs.ext.ReaderInterceptorContext;

class RequestBodySizeLimiterTest {
    @MaxRequestBodySize(kibibytes = 1)
    static class LimitedResource {}

    private Object read(int length, String contentLength) throws Exception {
        RequestBodySizeLimiter limiter = new RequestBodySizeLimiter();
        ResourceInfo resource = mock(ResourceInfo.class);
        when(resource.getResourceClass()).thenReturn((Class) LimitedResource.class);
        Field field = RequestBodySizeLimiter.class.getDeclaredField("resourceInfo");
        field.setAccessible(true);
        field.set(limiter, resource);
        ReaderInterceptorContext context = mock(ReaderInterceptorContext.class);
        MultivaluedHashMap<String, String> headers = new MultivaluedHashMap<>();
        if (contentLength != null) {
            headers.add(HttpHeaders.CONTENT_LENGTH, contentLength);
        }
        when(context.getHeaders()).thenReturn(headers);
        AtomicReference<InputStream> stream = new AtomicReference<>(new ByteArrayInputStream(new byte[length]));
        when(context.getInputStream()).thenAnswer(inv -> stream.get());
        doAnswer(inv -> { stream.set(inv.getArgument(0)); return null; }).when(context).setInputStream(org.mockito.ArgumentMatchers.any());
        when(context.proceed()).thenAnswer(inv -> stream.get().readAllBytes().length);
        return limiter.aroundReadFrom(context);
    }

    @Test
    void allowsBoundaryForChunkedBody() throws Exception {
        assertEquals(1024, read(1024, null));
    }

    @Test
    void rejectsOversizedChunkedBody() {
        WebApplicationException error = assertThrows(WebApplicationException.class, () -> read(1025, null));
        assertEquals(413, error.getResponse().getStatus());
    }

    @Test
    void rejectsOversizedDeclaredBody() {
        WebApplicationException error = assertThrows(WebApplicationException.class, () -> read(0, "1025"));
        assertEquals(413, error.getResponse().getStatus());
    }
}
