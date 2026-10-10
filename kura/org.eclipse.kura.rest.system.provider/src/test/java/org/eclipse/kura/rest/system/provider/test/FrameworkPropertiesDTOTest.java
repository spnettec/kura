/*******************************************************************************
 * Copyright (c) 2026 Eurotech and/or its affiliates and others
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 *******************************************************************************/
package org.eclipse.kura.rest.system.provider.test;

import static org.eclipse.kura.system.SystemService.KEY_KURA_HAVE_NET_ADMIN;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Properties;

import org.eclipse.kura.rest.system.dto.FrameworkPropertiesDTO;
import org.eclipse.kura.system.SystemService;
import org.junit.jupiter.api.Test;

import com.google.gson.Gson;

class FrameworkPropertiesDTOTest {

    private static final String DTO_NAME = "kuraHaveNetAdmin";

    @Test
    void acceptsStringSystemPropertyOverride() {
        assertFalse(valueFor("false"));
    }

    @Test
    void keepsBooleanPropertyValue() {
        assertTrue(valueFor(Boolean.TRUE));
    }

    private boolean valueFor(Object propertyValue) {
        SystemService systemService = mock(SystemService.class);
        Properties properties = new Properties();
        properties.put(KEY_KURA_HAVE_NET_ADMIN, propertyValue);
        when(systemService.getProperties()).thenReturn(properties);

        FrameworkPropertiesDTO dto = new FrameworkPropertiesDTO(systemService, List.of(DTO_NAME));
        return new Gson().toJsonTree(dto).getAsJsonObject().get(DTO_NAME).getAsBoolean();
    }
}
