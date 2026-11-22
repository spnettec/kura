/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import org.eclipse.kura.configuration.*;
import org.eclipse.kura.core.configuration.metatype.*;
import org.junit.jupiter.api.Test;
import org.osgi.framework.*;
import org.osgi.service.cm.*;
import org.osgi.service.component.ComponentContext;

class ProviderCoreReadReentryTest {
    @Test @SuppressWarnings("unchecked")
    void anSccCanReadAnOrdinaryCmConfigurationWithoutWaitingForItsCallingCoreMonitor() throws Exception {
        var core = new ConfigurationServiceImpl();
        var reads = new ProviderConfigurationReads(300, 2, 2);
        ((ProviderConfigurationReads) ProviderPlanReadBudgetTest.field("providerReads").get(core)).close();
        ProviderPlanReadBudgetTest.field("providerReads").set(core, reads);
        var bundles = mock(BundleContext.class); var context = mock(ComponentContext.class);
        when(context.getBundleContext()).thenReturn(bundles); ProviderPlanReadBudgetTest.field("ctx").set(core, context);
        var admin = mock(ConfigurationAdmin.class); var configuration = mock(Configuration.class);
        when(admin.getConfiguration("nested.cm", "?")).thenReturn(configuration);
        when(admin.getConfiguration("owned.reentry", "?")).thenReturn(configuration);
        when(configuration.getProperties()).thenReturn(new Hashtable<>(Map.of("value", "current")));
        core.setConfigurationAdmin(admin);
        ((Map<String,String>) ProviderPlanReadBudgetTest.field("servicePidByPid").get(core)).put("nested.cm", "nested.cm");
        var definition = new Tocd(); definition.setId("owned.reentry");
        var attribute = new Tad(); attribute.setId("value"); attribute.setType(Tscalar.STRING); definition.addAD(attribute);
        ((Map<String,Tocd>) ProviderPlanReadBudgetTest.field("ocds").get(core)).put("nested.cm", definition);
        ServiceReference<SelfConfiguringComponent> reference = mock(ServiceReference.class);
        when(reference.getProperty(ConfigurationService.KURA_SERVICE_PID)).thenReturn("owned.reentry");
        when(reference.getProperty(Constants.SERVICE_PID)).thenReturn("owned.reentry");
        when(bundles.getServiceReferences((String)null, "(kura.service.pid=owned.reentry)"))
                .thenReturn(new ServiceReference<?>[]{reference});
        SelfConfiguringComponent component = () -> {
            var nested = core.getComponentConfiguration("nested.cm");
            return new ComponentConfigurationImpl("owned.reentry", definition, nested.getConfigurationProperties());
        };
        when(bundles.getService(reference)).thenReturn(component); core.addSelfConfiguringComponent(reference);
        try {
            var result = core.readRevision("owned.reentry");
            assertEquals("current", result.configuration().getConfigurationProperties().get("value"));
            assertTrue(result.revision().matches("[0-9a-f]{64}"));
            verify(bundles).ungetService(reference);
        } finally { reads.close(); }
    }
}
