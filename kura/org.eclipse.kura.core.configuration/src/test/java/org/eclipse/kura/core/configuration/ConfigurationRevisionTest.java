/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Vector;

import org.eclipse.kura.configuration.ConfigurationRevisionService.Rejected;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.configuration.metatype.AD;
import org.eclipse.kura.configuration.metatype.Scalar;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.junit.jupiter.api.Test;

class ConfigurationRevisionTest {
    static AD attribute(String id, Scalar type, int cardinality) {
        AD value = mock(AD.class);
        when(value.getId()).thenReturn(id); when(value.getType()).thenReturn(type);
        when(value.getCardinality()).thenReturn(cardinality);
        return value;
    }

    static ComponentConfigurationImpl component(Map<String, Object> values) {
        Tocd definition = mock(Tocd.class);
        var attributes = List.of(attribute("name", Scalar.STRING, 0),
                attribute("password", Scalar.PASSWORD, 0), attribute("count", Scalar.LONG, 0),
                attribute("array", Scalar.INTEGER, 4), attribute("service.pid", Scalar.STRING, 0));
        when(definition.getAD()).thenReturn(attributes);
        return new ComponentConfigurationImpl("fixture.revision", definition, values);
    }

    @Test void revisionIsStableForMapOrderButBindsSecretTypeMetadataAndBothCounters() throws Exception {
        var signer = new ConfigurationRevision();
        Map<String, Object> first = new LinkedHashMap<>();
        first.put("name", "one"); first.put("password", new Password("private-value"));
        var component = component(first);
        String token = signer.token(component, 2, 3);
        assertTrue(token.matches("[0-9a-f]{64}")); assertFalse(token.contains("private-value"));
        assertFalse(new org.eclipse.kura.configuration.ConfigurationRevisionService.Read(component, token)
                .toString().contains("private-value"));
        Map<String, Object> reordered = new LinkedHashMap<>();
        reordered.put("password", new Password("private-value")); reordered.put("name", "one");
        assertEquals(token, signer.token(component(reordered), 2, 3));
        assertNotEquals(token, new ConfigurationRevision().token(component, 2, 3));
        assertNotEquals(token, signer.token(component, 3, 3));
        assertNotEquals(token, signer.token(component, 2, 4));
        first.put("password", new Password("changed-secret"));
        assertNotEquals(token, signer.token(component, 2, 3));
        first.put("password", "private-value");
        assertNotEquals(token, signer.token(component, 2, 3));
        String beforeMetadata = signer.token(component, 2, 3);
        when(component.getDefinition().getAD().get(0).getCardinality()).thenReturn(2);
        assertNotEquals(beforeMetadata, signer.token(component, 2, 3));
    }

    @Test void canonicalizationRejectsUnsafeObjectsCyclesAndExcessiveWork() throws Exception {
        var signer = new ConfigurationRevision();
        Object unsafe = new Object() { @Override public String toString() { throw new AssertionError("unsafe"); } };
        assertThrows(Rejected.class, () -> signer.token(component(Map.of("name", unsafe)), 0, 0));
        Vector<Object> cycle = new Vector<>(); cycle.add(cycle);
        assertThrows(Rejected.class, () -> ConfigurationRevision.copyPatch(Map.of("array", cycle)));
        assertThrows(Rejected.class, () -> signer.token(component(Map.of("name", "x".repeat(16385))), 0, 0));
        assertThrows(Rejected.class, () -> signer.token(component(Map.of("array", new int[257])), 0, 0));
        var large = new HashMap<String, Object>();
        for (int i = 0; i < 32; i++) { large.put("key" + i, "x".repeat(16384)); }
        assertThrows(Rejected.class, () -> signer.token(component(large), 0, 0));
        assertThrows(Rejected.class, () -> ConfigurationRevision.copyPatch(large));
        assertThrows(Rejected.class, () -> ConfigurationRevision.copyPatch(Map.of("count", Double.NaN)));
    }

    @Test void patchCopiesPasswordsAndContainersAndEnforcesTypeAndCardinality() throws Exception {
        int[] array = { 1, 2 }; Password password = new Password("before");
        var patch = ConfigurationRevision.copyPatch(Map.of("array", array, "password", password));
        array[0] = 99; password.getPassword()[0] = 'X';
        assertArrayEquals(new int[] { 1, 2 }, (int[]) patch.get("array"));
        assertArrayEquals("before".toCharArray(), ((Password) patch.get("password")).getPassword());
        assertTrue(ConfigurationRevision.accepts(attribute("count", Scalar.LONG, 0), Long.MAX_VALUE));
        assertFalse(ConfigurationRevision.accepts(attribute("count", Scalar.LONG, 0), Integer.MAX_VALUE));
        assertTrue(ConfigurationRevision.accepts(attribute("array", Scalar.INTEGER, 2), new int[] { 1, 2 }));
        assertFalse(ConfigurationRevision.accepts(attribute("array", Scalar.INTEGER, 1), new int[] { 1, 2 }));
        assertFalse(ConfigurationRevision.accepts(attribute("array", Scalar.INTEGER, -2), new int[] { 1, 2 }));
        assertTrue(ConfigurationRevision.accepts(attribute("array", Scalar.INTEGER, Integer.MIN_VALUE), new Vector<>(List.of(1, 2))));
        assertThrows(Rejected.class, () -> ConfigurationRevision.copyPatch(new HashMap<>() {{ put("name", null); }}));
    }
}
