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

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.io.IOException;
import java.util.*;
import jakarta.ws.rs.core.Response.Status;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.testutil.requesthandler.TransportType;
import org.eclipse.kura.core.testutil.requesthandler.Transport.MethodSpec;
import org.eclipse.kura.internal.rest.security.provider.SecurityRestServiceV1;
import org.eclipse.kura.security.SecurityService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

class SecurityEndpointsV1IT extends EndpointTestBase {
    private static final String MQTT_APP_ID = "SEC-V1";
    private static final String REST_APP_ID = "security/v1";
    private static final String METHOD_SPEC_GET = "GET";
    private static final String METHOD_SPEC_POST = "POST";
    private static final String ADMIN_ADMIN = "endpoint.admin:Endpoint-Admin-1!";
    private static final String DEBUG_ENABLED = "/debug-enabled";
    private static final String EXPECTED_DEBUG_ENABLE_TRUE_RESPONSE = "{\"enabled\":true}";
    private static final String SECURITY_POLICY_APPLY_DEFAULT_PRODUCTION = "/security-policy/apply-default-production";
    private static final String SECURITY_POLICY_APPLY = "/security-policy/apply";
    private SecurityService securityServiceMock;
    private SecurityRestServiceV1 endpoint;
    private boolean debugEnabled;
    private String securityPolicy;

    @BeforeEach
    void registerEndpoint() {
        this.debugEnabled = false;
        this.securityPolicy = null;
        this.securityServiceMock = mock(SecurityService.class);
        this.endpoint = new SecurityRestServiceV1();
        this.endpoint.bindSecurityService(this.securityServiceMock);
        this.endpoint.bindRequestHandlerRegistry(this.cloud);
        this.http.resource(this.endpoint);
    }

    @AfterEach
    void unregisterEndpoint() {
        if (this.endpoint != null) { this.endpoint.unbindRequestHandlerRegistry(this.cloud); }
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldInvokeReloadSecurityPolicyFingerprintSuccessfully(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenSecurityService();
        givenRestBasicCredentials(ADMIN_ADMIN);

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/security-policy-fingerprint/reload");

        thenRequestSucceeds();
        thenResponseBodyIsEmpty();
        verify(this.securityServiceMock).reloadSecurityPolicyFingerprint();
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldInvokeReloadCommandLineFingerprintSuccessfully(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenSecurityService();
        givenRestBasicCredentials(ADMIN_ADMIN);

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/command-line-fingerprint/reload");

        thenRequestSucceeds();
        thenResponseBodyIsEmpty();
        verify(this.securityServiceMock).reloadCommandLineFingerprint();
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnExpectedDebugStatus(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenDebugEnabledStatus(true);
        givenSecurityService();
        givenRestBasicCredentials(ADMIN_ADMIN);

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), DEBUG_ENABLED);

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_DEBUG_ENABLE_TRUE_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldNotReturnDebugStatusOverRestIfNotLoggedIn(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenDebugEnabledStatus(true);
        givenSecurityService();
        givenNoRestBasicCredentials();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), DEBUG_ENABLED);

        thenResponseCodeIs(type == TransportType.REST ? 401 : 200);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldReturnDebugStatusEvenIfIdentityHasNoPermissions(TransportType type) {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenDebugEnabledStatus(true);
        givenSecurityService();
        givenIdentity("foo", Optional.of("Endpoint-User-1!"), Collections.emptyList(), false);
        givenRestBasicCredentials("foo:Endpoint-User-1!");

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), DEBUG_ENABLED);

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_DEBUG_ENABLE_TRUE_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRethrowWebApplicationExceptionOnReloadSecurityPolicyFingerprint(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenFailingSecurityService();
        givenRestBasicCredentials(ADMIN_ADMIN);

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/security-policy-fingerprint/reload");

        thenResponseCodeIs(Status.INTERNAL_SERVER_ERROR.getStatusCode());
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRethrowWebApplicationExceptionOnReloadCommandLineFingerprint(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenFailingSecurityService();
        givenRestBasicCredentials(ADMIN_ADMIN);

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/command-line-fingerprint/reload");

        thenResponseCodeIs(Status.INTERNAL_SERVER_ERROR.getStatusCode());
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    public void shouldRethrowWebApplicationExceptionOnGetDebugStatus(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenFailingSecurityService();
        givenRestBasicCredentials(ADMIN_ADMIN);

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), DEBUG_ENABLED);

        thenResponseCodeIs(Status.INTERNAL_SERVER_ERROR.getStatusCode());
    }

    private void givenDebugEnabledStatus(boolean debugStatus) {
        debugEnabled = debugStatus;
    }

    private void givenSecurityService() {
        reset(securityServiceMock);

        when(securityServiceMock.isDebugEnabled()).thenReturn(debugEnabled);
    }

    private void givenFailingSecurityService() throws KuraException {
        reset(securityServiceMock);

        when(securityServiceMock.isDebugEnabled()).thenThrow(RuntimeException.class);
        doThrow(RuntimeException.class).when(securityServiceMock).applyDefaultProductionSecurityPolicy();
        doThrow(RuntimeException.class).when(securityServiceMock).reloadCommandLineFingerprint();
        doThrow(RuntimeException.class).when(securityServiceMock).reloadSecurityPolicyFingerprint();
    }

    private void givenRestBasicCredentials(String value) { givenBasicCredentials(Optional.of(value)); }
    private void givenNoRestBasicCredentials() { givenBasicCredentials(Optional.empty()); }

    private void givenIdentity(String username, Optional<String> password, List<String> roles, boolean changeRequired) {
        assertDoesNotThrow(() -> {
            this.http.identityFixture().create(username, password.orElseThrow(), roles);
            if (changeRequired) { this.http.identityFixture().requirePasswordChange(username); }
        });
    }
}
