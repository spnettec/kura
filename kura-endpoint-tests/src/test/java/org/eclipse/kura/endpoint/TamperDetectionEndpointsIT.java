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
 ******************************************************************************/
package org.eclipse.kura.endpoint;

import static org.junit.jupiter.api.Assertions.*;
import java.io.IOException;
import java.net.MalformedURLException;
import java.util.*;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.testutil.requesthandler.TransportType;
import org.eclipse.kura.core.testutil.requesthandler.Transport.MethodSpec;
import org.eclipse.kura.internal.rest.tamper.detection.TamperDetectionRestService;
import org.eclipse.kura.internal.rest.tamper.detection.TamperDetectionRequestHandler;
import org.eclipse.kura.security.tamper.detection.TamperDetectionService;
import org.eclipse.kura.security.tamper.detection.TamperStatus;
import org.eclipse.kura.type.TypedValues;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.mockito.Mockito;
import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;

class TamperDetectionEndpointsIT extends EndpointTestBase {
    private TamperDetectionRestService rest;
    private TamperDetectionRequestHandler mqtt;

    @BeforeEach
    void registerEndpoint() {
        this.rest = new TamperDetectionRestService();
        this.mqtt = new TamperDetectionRequestHandler();
        this.mqtt.setRequestHandlerRegistry(this.cloud);
        this.http.resource(this.rest);
    }

    @AfterEach
    void unregisterEndpoint() {
        if (this.mqtt != null) { this.mqtt.unsetRequestHandlerRegistry(this.cloud); }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportListingTamperDetectionServices(TransportType type) throws MalformedURLException, IOException {
        useTransport(type, "TAMPER-V1", "tamper/v1");
        assertEquals(0, runRequestAndGetResponse("/list", new MethodSpec("GET"),
                new TypeToken<ArrayList<TamperDetectionServiceInfo>>() {
                }).size());
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldProvideTamperDetectionServiceInfo(TransportType type) throws MalformedURLException, IOException {
        useTransport(type, "TAMPER-V1", "tamper/v1");
        try (final Fixture fixture = new Fixture()) {
            final TamperDetectionService tamperDetectionService = Mockito.mock(TamperDetectionService.class);
            Mockito.when(tamperDetectionService.getDisplayName()).thenReturn("foo");

            fixture.registerService(tamperDetectionService, TamperDetectionService.class, "moo");

            final List<TamperDetectionServiceInfo> infos = runRequestAndGetResponse("/list", new MethodSpec("GET"),
                    new TypeToken<ArrayList<TamperDetectionServiceInfo>>() {
                    });

            assertEquals(1, infos.size());
            assertEquals("foo", infos.get(0).getDisplayName());
            assertEquals("moo", infos.get(0).getPid());
        }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReportNotFound(TransportType type) throws MalformedURLException, IOException {
        useTransport(type, "TAMPER-V1", "tamper/v1");
        try (final Fixture fixture = new Fixture()) {
            final TamperDetectionService tamperDetectionService = Mockito.mock(TamperDetectionService.class);
            Mockito.when(tamperDetectionService.getDisplayName()).thenReturn("foo");

            fixture.registerService(tamperDetectionService, TamperDetectionService.class, "moo");

            assertEquals(404, runRequest("/pid/boo", new MethodSpec("GET")).getStatus());
        }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldProvideMultipleTamperDetectionServiceInfo(TransportType type) throws MalformedURLException, IOException {
        useTransport(type, "TAMPER-V1", "tamper/v1");
        try (final Fixture fixture = new Fixture()) {

            final TamperDetectionService first = Mockito.mock(TamperDetectionService.class);
            Mockito.when(first.getDisplayName()).thenReturn("foo");
            fixture.registerService(first, TamperDetectionService.class, "moo");

            final TamperDetectionService second = Mockito.mock(TamperDetectionService.class);
            Mockito.when(second.getDisplayName()).thenReturn("boo");
            fixture.registerService(second, TamperDetectionService.class, "bar");

            final List<TamperDetectionServiceInfo> infos = runRequestAndGetResponse("/list", new MethodSpec("GET"),
                    new TypeToken<ArrayList<TamperDetectionServiceInfo>>() {
                    });

            assertEquals(2, infos.size());
            assertTrue(infos.stream().anyMatch(p -> p.getPid().equals("moo") && p.getDisplayName().equals("foo")));
            assertTrue(infos.stream().anyMatch(p -> p.getPid().equals("bar") && p.getDisplayName().equals("boo")));
        }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReportTamperStatusInfo(TransportType type) throws MalformedURLException, IOException, KuraException {
        useTransport(type, "TAMPER-V1", "tamper/v1");
        try (final Fixture fixture = new Fixture()) {
            final TamperDetectionService tamperDetectionService = Mockito.mock(TamperDetectionService.class);
            Mockito.when(tamperDetectionService.getDisplayName()).thenReturn("foo");
            Mockito.when(tamperDetectionService.getTamperStatus())
                    .thenReturn(new TamperStatus(false, Collections.emptyMap()));

            fixture.registerService(tamperDetectionService, TamperDetectionService.class, "moo");

            final TamperStatusInfo info = runRequestAndGetResponse("/pid/moo", new MethodSpec("GET"),
                    new TypeToken<TamperStatusInfo>() {
                    });

            assertEquals(false, info.isDeviceTampered);
            assertTrue(info.properties.isEmpty());
        }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReportTamperStatusInfoTimestamp(TransportType type) throws MalformedURLException, IOException, KuraException {
        useTransport(type, "TAMPER-V1", "tamper/v1");
        try (final Fixture fixture = new Fixture()) {
            final TamperDetectionService tamperDetectionService = Mockito.mock(TamperDetectionService.class);
            Mockito.when(tamperDetectionService.getDisplayName()).thenReturn("foo");
            Mockito.when(tamperDetectionService.getTamperStatus()).thenReturn(
                    new TamperStatus(true, Collections.singletonMap("timestamp", TypedValues.newLongValue(5000L))));

            fixture.registerService(tamperDetectionService, TamperDetectionService.class, "moo");

            final TamperStatusInfo info = runRequestAndGetResponse("/pid/moo", new MethodSpec("GET"),
                    new TypeToken<TamperStatusInfo>() {
                    });

            assertEquals(true, info.isDeviceTampered);
            assertEquals(5000.0d, info.properties.get("timestamp"));
        }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportTamperStatusReset(TransportType type) throws MalformedURLException, IOException, KuraException {
        useTransport(type, "TAMPER-V1", "tamper/v1");
        try (final Fixture fixture = new Fixture()) {
            final TamperDetectionService tamperDetectionService = new TamperDetectionService() {

                boolean isDeviceTampered = true;

                @Override
                public void resetTamperStatus() throws KuraException {
                    isDeviceTampered = false;
                }

                @Override
                public TamperStatus getTamperStatus() throws KuraException {
                    return new TamperStatus(isDeviceTampered, Collections.emptyMap());
                }

                @Override
                public String getDisplayName() {
                    return "Foo";
                }
            };

            fixture.registerService(tamperDetectionService, TamperDetectionService.class, "moo");

            assertEquals(true,
                    runRequestAndGetResponse("/pid/moo", new MethodSpec("GET"), new TypeToken<TamperStatusInfo>() {
                    }).isDeviceTampered);

            int resetStatus = runRequest("/pid/moo/_reset", new MethodSpec("POST", "EXEC")).getStatus();
            assertTrue(resetStatus >= 200 && resetStatus < 300);

            assertEquals(false,
                    runRequestAndGetResponse("/pid/moo", new MethodSpec("GET"), new TypeToken<TamperStatusInfo>() {
                    }).isDeviceTampered);
        }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldSupportTrackingByServicePid(TransportType type) throws MalformedURLException, IOException {
        useTransport(type, "TAMPER-V1", "tamper/v1");
        try (final Fixture fixture = new Fixture()) {
            final TamperDetectionService tamperDetectionService = Mockito.mock(TamperDetectionService.class);
            Mockito.when(tamperDetectionService.getDisplayName()).thenReturn("foo");

            fixture.registerService(tamperDetectionService, TamperDetectionService.class,
                    Collections.singletonMap("service.pid", "moo"));

            final List<TamperDetectionServiceInfo> infos = runRequestAndGetResponse("/list", new MethodSpec("GET"),
                    new TypeToken<ArrayList<TamperDetectionServiceInfo>>() {
                    });

            assertEquals(1, infos.size());
            assertEquals("foo", infos.get(0).getDisplayName());
            assertEquals("moo", infos.get(0).getPid());
        }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldRemoveUnregisteredServices(TransportType type) throws Exception {
        useTransport(type, "TAMPER-V1", "tamper/v1");
        try (Fixture fixture = new Fixture()) {
            TamperDetectionService service = Mockito.mock(TamperDetectionService.class);
            Mockito.when(service.getDisplayName()).thenReturn("temporary");
            fixture.registerService(service, TamperDetectionService.class, "temporary.pid");
            assertEquals(1, runRequestAndGetResponse("/list", new MethodSpec("GET"),
                    new TypeToken<ArrayList<TamperDetectionServiceInfo>>() {}).size());
        }
        assertTrue(runRequestAndGetResponse("/list", new MethodSpec("GET"),
                new TypeToken<ArrayList<TamperDetectionServiceInfo>>() {}).isEmpty());
        assertEquals(404, runRequest("/pid/temporary.pid", new MethodSpec("GET")).getStatus());
    }

    private class Fixture implements AutoCloseable {
        private final List<Runnable> unbind = new ArrayList<>();

        <T extends TamperDetectionService> void registerService(T service, Class<? super T> type, String pid) {
            registerService(service, type, Map.of("kura.service.pid", pid));
        }

        <T extends TamperDetectionService> void registerService(T service, Class<? super T> type,
                Map<String, Object> properties) {
            rest.setTamperDetectionService(service, properties);
            mqtt.setTamperDetectionService(service, properties);
            this.unbind.add(() -> {
                rest.unsetTamperDetectionService(service, properties);
                mqtt.unsetTamperDetectionService(service, properties);
            });
        }

        @Override
        public void close() {
            this.unbind.forEach(Runnable::run);
            this.unbind.clear();
        }
    }

    private <T> T runRequestAndGetResponse(final String resource, final MethodSpec method,
            final TypeToken<T> responseType) {
        final var result = runRequest(resource, method);
        assertEquals(200, result.getStatus());
        final String response = result.getBody()
                .orElseThrow(() -> new IllegalStateException("expected body"));

        final Gson gson = new Gson();
        return gson.fromJson(response, responseType.getType());
    }

    public class TamperStatusInfo {

        private boolean isDeviceTampered;
        private Map<String, Object> properties;

        public boolean isDeviceTampered() {
            return isDeviceTampered;
        }

        public Map<String, Object> getProperties() {
            return properties;
        }
    }

    public class TamperDetectionServiceInfo {

        private String pid;
        private String displayName;

        public String getPid() {
            return pid;
        }

        public String getDisplayName() {
            return displayName;
        }
    }
}
