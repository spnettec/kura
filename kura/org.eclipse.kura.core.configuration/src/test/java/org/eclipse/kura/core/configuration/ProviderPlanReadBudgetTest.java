/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.lang.reflect.Field;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.*;
import org.eclipse.kura.core.configuration.metatype.*;
import org.junit.jupiter.api.Test;
import org.osgi.framework.*;
import org.osgi.service.component.ComponentContext;

class ProviderPlanReadBudgetTest {
    static class Fixture extends ConfigurationServiceImpl implements AutoCloseable {
        final ProviderConfigurationReads reads = new ProviderConfigurationReads(300, 2, 2);
        final AtomicBoolean slow = new AtomicBoolean();
        final BundleContext bundles = mock(BundleContext.class);
        int writes;
        boolean failAfterDispatch;
        Fixture() throws Exception {
            ComponentContext context = mock(ComponentContext.class);
            when(context.getBundleContext()).thenReturn(bundles);
            field("ctx").set(this, context);
            ((ProviderConfigurationReads) field("providerReads").get(this)).close();
            field("providerReads").set(this, reads);
            for (String pid : List.of("first.provider", "second.provider")) {
                @SuppressWarnings("unchecked") ServiceReference<SelfConfiguringComponent> reference = mock(ServiceReference.class);
                when(reference.getProperty(ConfigurationService.KURA_SERVICE_PID)).thenReturn(pid);
                when(reference.getProperty(Constants.SERVICE_PID)).thenReturn(pid);
                when(bundles.getServiceReferences((String) null, "(kura.service.pid=" + pid + ")"))
                        .thenReturn(new ServiceReference<?>[] { reference });
                Tocd definition = new Tocd(); definition.setId(pid);
                Tad attribute = new Tad(); attribute.setId("value"); attribute.setType(Tscalar.STRING); definition.addAD(attribute);
                SelfConfiguringComponent provider = () -> {
                    if (slow.get()) {
                        try { Thread.sleep(200); }
                        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
                    }
                    return new ComponentConfigurationImpl(pid, definition, Map.of("value", "original"));
                };
                when(bundles.getService(reference)).thenReturn(provider);
                addSelfConfiguringComponent(reference);
            }
        }
        @Override protected boolean revisionTargetTracked(String pid) { return true; }
        @Override public Set<String> getFactoryComponentPids() { return Set.of(); }
        @Override public synchronized void updateConfigurations(List<ComponentConfiguration> configs, boolean snapshot)
                throws KuraException {
            writes++;
            if (failAfterDispatch) {
                slow.set(true);
                // A snapshot can traverse multiple SCCs after the writer has already run.
                try (var budget = reads.budget()) {
                    getComponentConfiguration("first.provider");
                    getComponentConfiguration("second.provider");
                }
            }
        }
        Map<String, String> baseline() throws KuraException {
            Map<String, String> result = new LinkedHashMap<>();
            for (String pid : List.of("first.provider", "second.provider")) result.put(pid, readRevision(pid).revision());
            return result;
        }
        @Override public void close() { reads.close(); }
    }
    static Field field(String name) throws Exception {
        Field result = ConfigurationServiceImpl.class.getDeclaredField(name); result.setAccessible(true); return result;
    }
    static ComponentConfiguration update() {
        return new ComponentConfigurationImpl("first.provider", null, new HashMap<>(Map.of("value", "changed")));
    }
    @Test void planGuardsShareOneProviderReadBudgetAndDoNotDispatchAfterExpiry() throws Exception {
        try (var core = new Fixture()) {
            Map<String, String> baseline = core.baseline(); core.slow.set(true);
            var rejection = assertThrows(ConfigurationRevisionService.Rejected.class, () ->
                    core.applyConfigurationPlanIfUnchanged(List.of(update()), List.of(), Set.of(), baseline));
            assertEquals(ConfigurationRevisionService.Reason.CONFLICT, rejection.getReason());
            assertEquals(0, core.writes);
            assertTrue(((Map<?, ?>) field("revisionAdmissions").get(core)).isEmpty());
            assertTrue(((Set<?>) field("revisionUncertain").get(core)).isEmpty());
        }
    }
    @Test void aProviderDeadlineAfterDispatchRemainsUncertainAndDoesNotAuthorizeASecondWrite() throws Exception {
        try (var core = new Fixture()) {
            Map<String, String> baseline = core.baseline(); core.failAfterDispatch = true;
            KuraException failure = assertThrows(KuraException.class, () ->
                    core.applyConfigurationPlanIfUnchanged(List.of(update()), List.of(), Set.of(), baseline));
            assertFalse(failure instanceof ConfigurationRevisionService.Rejected);
            assertEquals(1, core.writes);
            assertTrue(((Set<?>) field("revisionUncertain").get(core)).containsAll(baseline.keySet()));
            core.slow.set(false);
            var rejection = assertThrows(ConfigurationRevisionService.Rejected.class, () -> core.readRevision("first.provider"));
            assertEquals(ConfigurationRevisionService.Reason.CONFLICT, rejection.getReason());
            assertEquals(1, core.writes);
        }
    }
    @Test void immutableProviderPropertiesCanBeOverlaidAndNullKeysAreRejected() throws Exception {
        assertEquals(Map.of("value", "changed"),
                ConfigurationRevision.overlay(Map.of("value", "original"), Map.of("value", "changed")));
        Map<String, Object> invalid = new HashMap<>(); invalid.put(null, "invalid");
        assertThrows(ConfigurationRevisionService.Rejected.class,
                () -> ConfigurationRevision.overlay(invalid, Map.of()));
    }

}
