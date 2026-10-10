/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.lang.reflect.InvocationTargetException;
import java.util.HashMap;
import java.util.Hashtable;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.junit.jupiter.api.Test;
import org.osgi.framework.BundleContext;
import org.osgi.service.cm.Configuration;
import org.osgi.service.cm.ConfigurationAdmin;
import org.osgi.service.component.ComponentContext;

class FactoryRollbackRegistrationTest {
    private static final String PID = "factory.instance";
    private static final String FACTORY = "test.factory";
    private static final String SERVICE_PID = "test.factory~123";

    @Test
    void updatingAnActiveFactoryDuringRollbackDoesNotDeleteItsConfiguration() throws Exception {
        var service = configuredService();
        var admin = mock(ConfigurationAdmin.class);
        var configuration = mock(Configuration.class);
        service.setConfigurationAdmin(admin);
        when(configuration.getPid()).thenReturn(SERVICE_PID);
        when(configuration.getProperties()).thenReturn(new Hashtable<>(Map.of("value", 1)));
        when(admin.getConfiguration(SERVICE_PID, "?")).thenReturn(configuration);
        service.registerComponentConfiguration(PID, SERVICE_PID, FACTORY);

        rollbackConfiguration(service, Optional.of(configuration));

        verify(configuration).update(argThat(properties -> Integer.valueOf(2).equals(properties.get("value"))));
        verify(configuration, never()).delete();
        assertTrue(service.getConfigurableComponentPids().contains(PID));
    }

    @Test
    void aRecreatedFactoryWaitsForScrBeforeBeingMarkedActive() throws Exception {
        var service = configuredService();
        var admin = mock(ConfigurationAdmin.class);
        var configuration = mock(Configuration.class);
        service.setConfigurationAdmin(admin);
        when(configuration.getPid()).thenReturn(SERVICE_PID);
        when(admin.createFactoryConfiguration(FACTORY, null)).thenReturn(configuration);
        when(admin.getConfiguration(SERVICE_PID, "?")).thenReturn(configuration);

        rollbackConfiguration(service, Optional.empty());

        assertTrue(service.getConfigurableComponentPids().contains(PID));
        assertFalse(activePids(service).contains(PID), "CM creation is not SCR activation");
        service.registerComponentConfiguration(PID, SERVICE_PID, FACTORY);
        assertTrue(activePids(service).contains(PID));
        verify(configuration, never()).delete();
    }

    private static ConfigurationServiceImpl configuredService() throws Exception {
        var service = new ConfigurationServiceImpl();
        ComponentContext context = mock(ComponentContext.class);
        when(context.getBundleContext()).thenReturn(mock(BundleContext.class));
        set(service, "ctx", context);
        set(service, "ocds", new HashMap<>(Map.of(FACTORY, new Tocd())));
        return service;
    }

    private static void rollbackConfiguration(ConfigurationServiceImpl service, Optional<Configuration> existing)
            throws Exception {
        var properties = new HashMap<String, Object>(Map.of("service.factoryPid", FACTORY,
                "kura.service.pid", PID, "value", 2));
        var snapshot = new ComponentConfigurationImpl(PID, null, properties);
        var method = ConfigurationServiceImpl.class.getDeclaredMethod("rollbackConfigurationInternal",
                ComponentConfiguration.class, Optional.class);
        method.setAccessible(true);
        try { method.invoke(service, snapshot, existing); }
        catch (InvocationTargetException e) { throw (Exception) e.getCause(); }
    }

    @SuppressWarnings("unchecked")
    private static Set<String> activePids(ConfigurationServiceImpl service) throws Exception {
        var field = ConfigurationServiceImpl.class.getDeclaredField("allActivatedPids");
        field.setAccessible(true);
        return (Set<String>) field.get(service);
    }

    private static void set(Object target, String name, Object value) throws Exception {
        var field = ConfigurationServiceImpl.class.getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }
}
