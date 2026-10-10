/*******************************************************************************
 * Copyright (c) 2023, 2026 Eurotech and/or its affiliates and others
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
package org.eclipse.kura.endpoint;

import static org.eclipse.kura.rest.system.Constants.*;
import static org.mockito.Mockito.*;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import jakarta.ws.rs.core.Response.Status;
import org.eclipse.kura.core.testutil.requesthandler.TransportType;
import org.eclipse.kura.core.testutil.requesthandler.Transport.MethodSpec;
import org.eclipse.kura.rest.system.SystemRestService;
import org.eclipse.kura.rest.system.provider.test.SystemServiceMockDecorator;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

class SystemEndpointsIT extends EndpointTestBase {
    private static final String EXPECTED_FRAMEWORK_PROPERTIES_RESPONSE = resource("FRAMEWORK_PROPERTIES_RESPONSE");
    private static final String EXPECTED_EXTENDED_PROPERTIES_RESPONSE = resource("EXTENDED_PROPERTIES_RESPONSE");
    private static final String EXPECTED_KURA_PROPERTIES_RESPONSE = resource("KURA_PROPERTIES_RESPONSE");
    private static final String FRAMEWORK_PROPERTIES_FILTER_REQUEST = resource("FRAMEWORK_PROPERTIES_FILTER_REQUEST");
    private static final String EXTENDED_PROPERTIES_FILTER_REQUEST = resource("EXTENDED_PROPERTIES_FILTER_REQUEST");
    private static final String KURA_PROPERTIES_FILTER_REQUEST = resource("KURA_PROPERTIES_FILTER_REQUEST");
    private static final String METHOD_SPEC_GET = "GET";
    private static final String METHOD_SPEC_POST = "POST";
    private SystemService systemServiceMock;
    private SystemRestService endpoint;

    @BeforeEach
    void registerEndpoint() {
        this.systemServiceMock = mock(SystemService.class);
        this.endpoint = new SystemRestService();
        this.endpoint.bindSystemService(this.systemServiceMock);
        this.endpoint.bindRequestHandlerRegistry(this.cloud);
        this.http.resource(this.endpoint);
    }

    @AfterEach
    void unregisterEndpoint() {
        if (this.endpoint != null) { this.endpoint.unbindRequestHandlerRegistry(this.cloud); }
    }

    private static String resource(String name) {
        try (InputStream stream = SystemEndpointsIT.class.getResourceAsStream("/" + name)) {
            if (stream == null) { throw new IllegalStateException("Missing fixture " + name); }
            return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        } catch (java.io.IOException e) { throw new java.io.UncheckedIOException(e); }
    }

    /*
     * Scenarios
     */

    // Positive tests

    // GET

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnExpectedFrameworkProperties(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenSystemServiceMockWithFrameworkProperties();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), RESOURCE_FRAMEWORK_PROPERTIES);

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_FRAMEWORK_PROPERTIES_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnExpectedExtendedProperties(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenSystemServiceMockWithExtendedProperties();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), RESOURCE_EXTENDED_PROPERTIES);

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_EXTENDED_PROPERTIES_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnCorrectKuraProperties(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenSystemServiceMockWithKuraProperties();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), RESOURCE_KURA_PROPERTIES);

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_KURA_PROPERTIES_RESPONSE);
    }

    // POST

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnFilteredFrameworkProperties(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenSystemServiceMockWithFrameworkProperties();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), RESOURCE_FRAMEWORK_PROPERTIES_FILTER,
                FRAMEWORK_PROPERTIES_FILTER_REQUEST);

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_FRAMEWORK_PROPERTIES_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnFilteredExtendedProperties(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenSystemServiceMockWithExtendedProperties();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), RESOURCE_EXTENDED_PROPERTIES_FILTER,
                EXTENDED_PROPERTIES_FILTER_REQUEST);

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_EXTENDED_PROPERTIES_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnFilteredKuraProperties(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenSystemServiceMockWithKuraProperties();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), RESOURCE_KURA_PROPERTIES_FILTER,
                KURA_PROPERTIES_FILTER_REQUEST);

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_KURA_PROPERTIES_RESPONSE);
    }

    // Exceptions test

    // GET

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRethrowWebApplicationExceptionOnFailingFrameworkProperties(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenFailingSystemServiceMock();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), RESOURCE_FRAMEWORK_PROPERTIES);

        thenResponseCodeIs(Status.INTERNAL_SERVER_ERROR.getStatusCode());
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRethrowWebApplicationExceptionOnFailingExtendedProperties(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenFailingSystemServiceMock();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), RESOURCE_EXTENDED_PROPERTIES);

        thenResponseCodeIs(Status.INTERNAL_SERVER_ERROR.getStatusCode());
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRethrowWebApplicationExceptionOnFailingKuraProperties(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenFailingSystemServiceMock();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), RESOURCE_KURA_PROPERTIES);

        thenResponseCodeIs(Status.INTERNAL_SERVER_ERROR.getStatusCode());
    }

    // POST

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRethrowWebApplicationExceptionOnFailingFrameworkPropertiesFilter(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenFailingSystemServiceMock();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), RESOURCE_FRAMEWORK_PROPERTIES_FILTER,
                FRAMEWORK_PROPERTIES_FILTER_REQUEST);

        thenResponseCodeIs(Status.INTERNAL_SERVER_ERROR.getStatusCode());
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRethrowWebApplicationExceptionOnFailingExtendedPropertiesFilter(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenFailingSystemServiceMock();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), RESOURCE_EXTENDED_PROPERTIES_FILTER,
                EXTENDED_PROPERTIES_FILTER_REQUEST);

        thenResponseCodeIs(Status.INTERNAL_SERVER_ERROR.getStatusCode());
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRethrowWebApplicationExceptionOnFailingKuraPropertiesFilter(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenFailingSystemServiceMock();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), RESOURCE_KURA_PROPERTIES_FILTER,
                KURA_PROPERTIES_FILTER_REQUEST);

        thenResponseCodeIs(Status.INTERNAL_SERVER_ERROR.getStatusCode());
    }

    /*
     * Steps
     */

    private void givenSystemServiceMockWithFrameworkProperties() {
        reset(systemServiceMock);
        SystemServiceMockDecorator.addFrameworkPropertiesMockMethods(systemServiceMock);
    }

    private void givenSystemServiceMockWithExtendedProperties() {
        reset(systemServiceMock);
        SystemServiceMockDecorator.addExtendedPropertiesMockMethods(systemServiceMock);
    }

    private void givenSystemServiceMockWithKuraProperties() {
        reset(systemServiceMock);
        SystemServiceMockDecorator.addKuraPropertiesMockMethods(systemServiceMock);
    }

    private void givenFailingSystemServiceMock() {
        reset(systemServiceMock);
        SystemServiceMockDecorator.addFailingMockMethods(systemServiceMock);
    }

}
