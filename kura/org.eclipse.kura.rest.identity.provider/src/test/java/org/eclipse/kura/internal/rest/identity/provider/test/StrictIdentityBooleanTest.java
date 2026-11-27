/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.internal.rest.identity.provider.test;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.stream.Stream;
import org.eclipse.kura.identity.IdentityConfiguration;
import org.eclipse.kura.identity.IdentityService;
import org.eclipse.kura.identity.PasswordConfiguration;
import org.eclipse.kura.internal.rest.identity.provider.IdentityRestServiceV2;
import org.eclipse.kura.internal.rest.identity.provider.dto.UserDTO;
import org.eclipse.kura.internal.rest.identity.provider.v2.dto.IdentityConfigurationDTO;
import org.eclipse.kura.internal.rest.identity.provider.v2.dto.PasswordConfigurationDTO;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.mockito.ArgumentCaptor;
import com.google.gson.Gson;
import com.google.gson.JsonParseException;
import jakarta.ws.rs.WebApplicationException;

class StrictIdentityBooleanTest {
    // Production GsonSerializer also uses an unmodified new Gson(). These tests
    // exercise field adapters without globally changing other JSON booleans.
    private static final Gson GSON = new Gson();
    static Stream<Arguments> nonBooleans() {
        return Stream.of(UserDTO.class, PasswordConfigurationDTO.class).flatMap(type ->
            Stream.of("passwordAuthEnabled", "passwordChangeNeeded").flatMap(flag ->
                Stream.of("\"false\"", "\"true\"", "\"asd\"", "\"\"", "0", "1", "[]", "{}")
                    .map(value -> Arguments.of(type, flag, value))));
    }
    @ParameterizedTest(name="{0} {1} rejects {2}")
    @MethodSource("nonBooleans")
    void rejectsNonBooleanTokensBeforeTheyCanBecomeIdentityFlags(Class<?> type, String flag, String value) {
        assertThrows(JsonParseException.class, () -> GSON.fromJson("{\""+flag+"\":"+value+"}", type));
    }
    static Stream<Arguments> booleans() {
        return Stream.of(UserDTO.class, PasswordConfigurationDTO.class).flatMap(type ->
            Stream.of("passwordAuthEnabled", "passwordChangeNeeded").flatMap(flag ->
                Stream.of(true, false).map(value -> Arguments.of(type, flag, value))));
    }
    @ParameterizedTest
    @MethodSource("booleans")
    void preservesActualBooleanValuesAndTheirJsonType(Class<?> type, String flag, boolean value) {
        Object dto = GSON.fromJson("{\""+flag+"\":"+value+"}", type);
        var encoded = GSON.toJsonTree(dto).getAsJsonObject().getAsJsonPrimitive(flag);
        assertTrue(encoded.isBoolean()); assertEquals(value, encoded.getAsBoolean());
    }
    static Stream<String> missingFlags() {
        return Stream.of("{}", "{\"passwordAuthEnabled\":true}", "{\"passwordChangeNeeded\":true}",
            "{\"passwordAuthEnabled\":null,\"passwordChangeNeeded\":false}",
            "{\"passwordAuthEnabled\":false,\"passwordChangeNeeded\":null}",
            "{\"passwordAuthEnabled\":null,\"passwordChangeNeeded\":null}");
    }
    @ParameterizedTest
    @MethodSource("missingFlags")
    void v2MissingOrNullFlagsReturn400WithoutCallingTheIdentityWriter(String flags) {
        IdentityService identity = mock(IdentityService.class);
        IdentityRestServiceV2 service = new IdentityRestServiceV2(); service.bindIdentityService(identity);
        IdentityConfigurationDTO dto = GSON.fromJson("{\"identity\":{\"name\":\"strict-boolean-fixture\"},\"passwordConfiguration\":"+flags+"}", IdentityConfigurationDTO.class);
        WebApplicationException error = assertThrows(WebApplicationException.class, () -> service.updateIdentity(dto, null));
        assertEquals(400, error.getResponse().getStatus());
        assertTrue(GSON.toJsonTree(error.getResponse().getEntity()).getAsJsonObject()
                .get("message").getAsString().contains("Missing 'password"));
        verifyNoInteractions(identity);
    }
    @Test
    void v1MissingAndNullFlagsRetainPartialUpdateSemantics() {
        for (String value : new String[]{"{}", "{\"passwordAuthEnabled\":null,\"passwordChangeNeeded\":null}"}) {
            UserDTO dto = GSON.fromJson(value, UserDTO.class);
            assertTrue(dto.isPasswordAuthEnabled().isEmpty()); assertTrue(dto.isPasswordChangeNeeded().isEmpty());
        }
    }
    @Test
    void validV2FlagsReachTheWriterUnchanged() throws Exception {
        for (boolean change : new boolean[]{true, false}) for (boolean auth : new boolean[]{true, false}) {
            IdentityService identity = mock(IdentityService.class);
            IdentityRestServiceV2 service = new IdentityRestServiceV2(); service.bindIdentityService(identity);
            IdentityConfigurationDTO dto = GSON.fromJson("{\"identity\":{\"name\":\"strict-boolean-fixture\"},\"passwordConfiguration\":{\"passwordChangeNeeded\":"+change+",\"passwordAuthEnabled\":"+auth+"}}", IdentityConfigurationDTO.class);
            assertEquals(200, service.updateIdentity(dto, null).getStatus());
            ArgumentCaptor<IdentityConfiguration> argument = ArgumentCaptor.forClass(IdentityConfiguration.class);
            verify(identity).updateIdentityConfiguration(argument.capture());
            PasswordConfiguration password = argument.getValue().getComponent(PasswordConfiguration.class).orElseThrow();
            assertEquals(change, password.isPasswordChangeNeeded()); assertEquals(auth, password.isPasswordAuthEnabled());
        }
    }
}
