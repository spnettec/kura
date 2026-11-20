/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.Map;
import java.util.Set;
import java.util.concurrent.*;
import org.eclipse.kura.configuration.*;
import org.eclipse.kura.core.configuration.metatype.*;
import org.junit.jupiter.api.Test;
import org.osgi.framework.*;
import org.osgi.service.component.ComponentContext;

class ProviderReadBoundsTest {
    @Test
    void pidSnapshotWaitsForRegistrationAndRemainsUnchangedAfterRemoval() throws Exception {
        var core = new ConfigurationServiceImpl();
        var started = new CountDownLatch(1);
        String pid = "registering.provider";
        try (var executor = Executors.newSingleThreadExecutor()) {
            Future<Set<String>> read;
            synchronized (core) {
                read = executor.submit(() -> {
                    started.countDown();
                    return core.getConfigurableComponentPids();
                });
                assertTrue(started.await(2, TimeUnit.SECONDS));
                assertThrows(TimeoutException.class, () -> read.get(150, TimeUnit.MILLISECONDS));
                core.registerSelfConfiguringComponent(pid, pid);
            }
            Set<String> pids = read.get(2, TimeUnit.SECONDS);
            core.unregisterComponentConfiguration(pid);
            assertEquals(Set.of(pid), pids);
            assertTrue(core.getConfigurableComponentPids().isEmpty());
        }
    }

    @Test
    @SuppressWarnings("unchecked")
    void anUncooperativeProviderCannotKeepTheCoreMonitorAndItsLeaseIsNotReleasedEarly() throws Exception {
        var core = new ConfigurationServiceImpl();
        BundleContext bundles = mock(BundleContext.class);
        ComponentContext context = mock(ComponentContext.class);
        when(context.getBundleContext()).thenReturn(bundles);
        var field = ConfigurationServiceImpl.class.getDeclaredField("ctx");
        field.setAccessible(true); field.set(core, context);
        ServiceReference<SelfConfiguringComponent> reference = mock(ServiceReference.class);
        String pid = "blocked.provider";
        when(reference.getProperty(ConfigurationService.KURA_SERVICE_PID)).thenReturn(pid);
        when(reference.getProperty(Constants.SERVICE_PID)).thenReturn(pid);
        when(bundles.getServiceReferences((String) null, "(kura.service.pid=" + pid + ")"))
                .thenReturn(new ServiceReference<?>[] {reference});
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        Tocd definition = new Tocd(); definition.setId(pid);
        Tad attribute = new Tad(); attribute.setId("value"); attribute.setType(Tscalar.STRING);
        definition.addAD(attribute);
        SelfConfiguringComponent provider = () -> {
            entered.countDown();
            boolean complete = false;
            while (!complete) {
                try { release.await(); complete = true; }
                catch (InterruptedException deliberatelyIgnored) { /* emulate a non-cooperative provider */ }
            }
            return new ComponentConfigurationImpl(pid, definition, Map.of("value", "late"));
        };
        when(bundles.getService(reference)).thenReturn(provider);
        core.addSelfConfiguringComponent(reference);
        ExecutorService caller = Executors.newSingleThreadExecutor();
        try {
            Future<?> request = caller.submit(() -> core.readRevision(pid));
            assertTrue(entered.await(1, TimeUnit.SECONDS));
            ExecutionException failure = assertThrows(ExecutionException.class,
                    () -> request.get(3500, TimeUnit.MILLISECONDS));
            assertInstanceOf(ConfigurationRevisionService.Rejected.class, failure.getCause());
            assertEquals(ConfigurationRevisionService.Reason.CONFLICT,
                    ((ConfigurationRevisionService.Rejected) failure.getCause()).getReason());
            Future<Boolean> monitor = caller.submit(() -> { synchronized (core) { return true; } });
            assertTrue(monitor.get(500, TimeUnit.MILLISECONDS));
            ConfigurationRevisionService.Rejected metadataUnavailable = assertThrows(
                    ConfigurationRevisionService.Rejected.class, () -> core.revisionTargetTracked(pid));
            assertEquals(ConfigurationRevisionService.Reason.CONFLICT, metadataUnavailable.getReason());
            verify(bundles, never()).ungetService(reference);
            core.deactivate();
            verify(bundles, never()).ungetService(reference);
        } finally {
            release.countDown(); caller.shutdownNow(); caller.awaitTermination(2, TimeUnit.SECONDS);
        }
        verify(bundles, timeout(1000)).ungetService(reference);
    }
}
