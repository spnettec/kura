/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.HashMap;
import java.util.Map;
import org.eclipse.kura.configuration.Password;
import org.eclipse.kura.configuration.SelfConfiguringComponent;
import org.eclipse.kura.core.configuration.metatype.Tad;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.eclipse.kura.core.configuration.metatype.Tscalar;
import org.eclipse.kura.crypto.CryptoService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.osgi.framework.BundleContext;
import org.osgi.framework.ServiceReference;
import org.osgi.service.component.ComponentContext;

class DefaultComponentConfigurationTest {
    @Test
    @SuppressWarnings("unchecked")
    void passwordDefaultIsDecryptedAtThePublicApiBoundary() throws Exception {
        var service = new ConfigurationServiceImpl();
        BundleContext bundles = mock(BundleContext.class);
        ComponentContext context = mock(ComponentContext.class);
        when(context.getBundleContext()).thenReturn(bundles);
        set(service, "ctx", context);
        CryptoService crypto = mock(CryptoService.class);
        ServiceReference<CryptoService> reference = mock(ServiceReference.class);
        when(bundles.getServiceReference(CryptoService.class)).thenReturn(reference);
        when(bundles.getService(reference)).thenReturn(crypto);
        when(crypto.encryptAes(any(char[].class))).thenReturn("encrypted-default".toCharArray());
        when(crypto.decryptAes("encrypted-default".toCharArray())).thenReturn("secret".toCharArray());
        service.setCryptoService(crypto);
        Tocd definition = definition("component", "password", Tscalar.PASSWORD, "secret");
        set(service, "ocds", new HashMap<>(Map.of("component", definition)));

        var result = service.getDefaultComponentConfiguration("component");
        Password password = assertInstanceOf(Password.class, result.getConfigurationProperties().get("password"));
        assertArrayEquals("secret".toCharArray(), password.getPassword());
        assertEquals("secret", definition.getAD().get(0).getDefault());
        verify(crypto).decryptAes("encrypted-default".toCharArray());
    }

    @Test
    @SuppressWarnings("unchecked")
    void selfConfiguringDefaultsComeFromItsDefinitionAndReleaseTheService() throws Exception {
        var service = new ConfigurationServiceImpl();
        BundleContext bundles = mock(BundleContext.class);
        ComponentContext context = mock(ComponentContext.class);
        when(context.getBundleContext()).thenReturn(bundles);
        set(service, "ctx", context);
        ServiceReference<SelfConfiguringComponent> reference = mock(ServiceReference.class);
        when(reference.getProperty("kura.service.pid")).thenReturn("self.component");
        when(reference.getProperty("service.pid")).thenReturn("self.component");
        when(bundles.getServiceReferences((String) null, "(kura.service.pid=self.component)"))
                .thenReturn(new ServiceReference<?>[] {reference});
        SelfConfiguringComponent component = mock(SelfConfiguringComponent.class);
        when(bundles.getService(reference)).thenReturn(component);
        Tocd definition = definition("self.component", "value", Tscalar.STRING, "default-value");
        when(component.getConfiguration()).thenReturn(new ComponentConfigurationImpl("self.component", definition,
                Map.of("value", "running-value")));
        service.addSelfConfiguringComponent(reference);

        var result = service.getDefaultComponentConfiguration("self.component");
        assertSame(definition, result.getDefinition());
        assertEquals(Map.of("value", "default-value"), result.getConfigurationProperties());
        verify(bundles).ungetService(reference);
    }

    @ParameterizedTest
    @NullAndEmptySource
    void absentDefinitionsKeepTheExistingEmptyResult(String pid) throws Exception {
        var result = new ConfigurationServiceImpl().getDefaultComponentConfiguration(pid);
        assertEquals(pid, result.getPid());
        assertNull(result.getDefinition());
        assertTrue(result.getConfigurationProperties().isEmpty());
    }

    private static Tocd definition(String pid, String id, Tscalar type, String defaultValue) {
        var definition = new Tocd();
        definition.setId(pid);
        var attribute = new Tad();
        attribute.setId(id);
        attribute.setType(type);
        attribute.setCardinality(0);
        attribute.setDefault(defaultValue);
        definition.addAD(attribute);
        return definition;
    }

    private static void set(Object target, String name, Object value) throws Exception {
        var field = ConfigurationServiceImpl.class.getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }
}
