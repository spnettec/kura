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

import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.argThat;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.core.testutil.requesthandler.TransportType;
import org.eclipse.kura.core.testutil.requesthandler.Transport.MethodSpec;
import org.eclipse.kura.internal.rest.identity.provider.IdentityRestServiceV1;
import org.eclipse.kura.internal.rest.identity.provider.LegacyIdentityService;
import org.eclipse.kura.internal.rest.identity.provider.dto.UserDTO;
import org.eclipse.kura.util.validation.ValidatorOptions;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import com.google.gson.Gson;

class IdentityV1EndpointsIT extends EndpointTestBase {
    private static final String MQTT_APP_ID = "IDN-V1";
    private static final String REST_APP_ID = "identity/v1";
    private static final String METHOD_SPEC_GET = "GET";
    private static final String METHOD_SPEC_POST = "POST";
    private static final String METHOD_SPEC_DELETE = "DELETE";
    private static final String MQTT_METHOD_SPEC_DEL = "DEL";
    private static final String METHOD_SPEC_PUT = "PUT";
    private LegacyIdentityService identityServiceMock;
    private IdentityRestServiceV1 endpoint;
    private UserDTO user;
    private Set<UserDTO> userConfigs;
    private final Gson gson = new Gson();
    private static final String EXPECTED_GET_USER_CONFIG_RESPONSE = resource("getUserConfigResponse.json");
    private static final String EXPECTED_GET_USER_RESPONSE = resource("getUserResponse.json");
    private static final String EXPECTED_GET_PASSWORD_REQUIREMENTS_RESPONSE = resource("getPasswordRequirementsResponse.json");
    private static final String EXPECTED_NON_EXISTING_USER_RESPONSE = resource("getNonExistingUserResponse.json");

    @BeforeEach
    void registerEndpoint() {
        this.user = null;
        this.userConfigs = new HashSet<>();
        this.identityServiceMock = mock(LegacyIdentityService.class);
        this.endpoint = new IdentityRestServiceV1();
        this.endpoint.bindLegacyIdentityService(this.identityServiceMock);
        this.endpoint.activate();
        this.endpoint.bindRequestHandlerRegistry(this.cloud);
        this.http.resource(this.endpoint);
    }
    @AfterEach
    void unregisterEndpoint() { if (this.endpoint != null) { this.endpoint.unbindRequestHandlerRegistry(this.cloud); } }

    private static String resource(String name) {
        try (InputStream in = IdentityV1EndpointsIT.class.getResourceAsStream("/identity/v1/" + name)) {
            if (in == null) { throw new IllegalStateException("Missing fixture: " + name); }
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (java.io.IOException e) { throw new IllegalStateException(e); }
    }
    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldInvokeCreateUserSuccessfully(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenUser(new UserDTO("testuser", Collections.emptySet(), true, false, "testpassw"));

        givenIdentityService();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/identities", gson.toJson(user));

        thenRequestSucceeds();
        thenResponseBodyIsEmpty();
        verify(identityServiceMock).createUser(argThat(value -> "testuser".equals(value.getUserName())));
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldInvokeUpdateUserSuccessfully(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenUser(new UserDTO("testuser", Collections.emptySet(), true, false, "testpassw"));

        givenIdentityService();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_PUT), "/identities", gson.toJson(user));

        thenRequestSucceeds();
        thenResponseBodyIsEmpty();
        verify(identityServiceMock).updateUser(argThat(value -> "testuser".equals(value.getUserName())));
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldInvokeDeleteUserSuccessfully(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenUser(new UserDTO("testuser", Collections.emptySet(), true, false, "testpassw"));

        givenIdentityService();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_DELETE, MQTT_METHOD_SPEC_DEL), "/identities",
                gson.toJson(user));

        thenRequestSucceeds();
        thenResponseBodyIsEmpty();
        verify(identityServiceMock).deleteUser("testuser");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldReturnUserSuccessfully(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenUser(new UserDTO("testuser3", Collections.emptySet(), true, false));

        givenIdentityService();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/identities/byName", gson.toJson(user));

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_GET_USER_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldReturnUserConfig(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenUserConfigs(new UserDTO("testuser2", //
                new HashSet<String>(Arrays.asList("perm1", "perm2")), //
                false, //
                true));

        givenIdentityService();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), "/identities");

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_GET_USER_CONFIG_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldReturnDefinedPermissions(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenIdentityService();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), "/definedPermissions");

        thenRequestSucceeds();
        thenResponseBodyEqualsJson("{\"permissions\": [\"perm1\",\"perm2\"]}");
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldReturnPasswordRequirements(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenIdentityService();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_GET), "/passwordRequirements");

        thenRequestSucceeds();
        thenResponseBodyEqualsJson(EXPECTED_GET_PASSWORD_REQUIREMENTS_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldReturnNonExistingUserDeleteResponse(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenIdentityService();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_DELETE, MQTT_METHOD_SPEC_DEL), "/identities",
                gson.toJson(new UserDTO("nonExistingUser", null, false, false)));

        thenResponseCodeIs(404);
        thenResponseBodyEqualsJson(EXPECTED_NON_EXISTING_USER_RESPONSE);
    }

    @ParameterizedTest
    @EnumSource(TransportType.class)
    void shouldReturnNonExistingUserPostResponse(TransportType type) throws KuraException {
        useTransport(type, MQTT_APP_ID, REST_APP_ID);
        givenIdentityService();

        whenRequestIsPerformed(new MethodSpec(METHOD_SPEC_POST), "/identities/byName",
                gson.toJson(new UserDTO("nonExistingUser", null, false, false)));

        thenResponseCodeIs(404);
        thenResponseBodyEqualsJson(EXPECTED_NON_EXISTING_USER_RESPONSE);
    }

    private void givenUser(UserDTO userParam) {
        user = userParam;
    }

    private void givenUserConfigs(UserDTO... userConfigurations) {
        userConfigs = new HashSet<>(Arrays.asList(userConfigurations));
    }

    private void givenIdentityService() throws KuraException {
        reset(identityServiceMock);

        when(identityServiceMock.getDefinedPermissions())
                .thenReturn(new HashSet<String>(Arrays.asList("perm1", "perm2")));

        when(identityServiceMock.getUserConfig()).thenReturn(userConfigs);

        if (user != null) {
            when(identityServiceMock.getUser("testuser3"))
                    .thenReturn(new UserDTO("testuser3", Collections.emptySet(), true, false));

            when(identityServiceMock.getUser("testuser"))
                    .thenReturn(new UserDTO("testuser", Collections.emptySet(), true, false));

        }

        when(identityServiceMock.getUser("nonExistingUser"))
                .thenThrow(new KuraException(KuraErrorCode.NOT_FOUND, "Identity does not exist"));

        doThrow(new KuraException(KuraErrorCode.NOT_FOUND, "Identity does not exist")).when(identityServiceMock)
                .deleteUser("nonExistingUser");

        when(identityServiceMock.getValidatorOptions()).thenReturn(new ValidatorOptions(8, false, false, false));
    }

}
