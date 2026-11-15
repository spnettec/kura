package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.nio.file.Path;
import org.eclipse.kura.configuration.ConfigurationService;
import org.eclipse.kura.configuration.SelfConfiguringComponent;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.osgi.framework.Constants;
import org.osgi.framework.Filter;
import org.osgi.framework.ServiceReference;
import org.osgi.service.cm.ManagedService;

class SelfConfiguringServiceSelectionTest {
    @TempDir Path directory;
    static final String PID = RollbackPreflightTest.FIRST;

    @SuppressWarnings("unchecked")
    private ServiceReference<Object> reference(RollbackConvergenceTest.Fixture core, Object service) {
        ServiceReference<Object> ref = mock(ServiceReference.class);
        when(ref.getProperty(ConfigurationService.KURA_SERVICE_PID)).thenReturn(PID);
        when(ref.getProperty(Constants.SERVICE_PID)).thenReturn(PID);
        when(core.bundles.getService(ref)).thenReturn(service);
        return ref;
    }

    private ServiceReference<?> self(RollbackConvergenceTest.Fixture core) throws Exception {
        core.published.get(PID).put("value", "live-self-view");
        return core.bundles.getServiceReferences((String) null, "(kura.service.pid=" + PID + ")")[0];
    }

    private void order(RollbackConvergenceTest.Fixture core, ServiceReference<?>... refs) throws Exception {
        when(core.bundles.getServiceReferences((String) null, "(kura.service.pid=" + PID + ")")).thenReturn(refs);
    }

    @Test void unrelatedManagedServiceCannotEraseLiveSelfViewInEitherEnumerationOrder() throws Exception {
        try (var core = new RollbackConvergenceTest.Fixture(directory)) {
            var self = self(core);
            var managed = reference(core, (ManagedService) properties -> { fail("read dispatched an update"); });
            for (boolean selfFirst : new boolean[] { true, false }) {
                order(core, selfFirst ? self : managed, selfFirst ? managed : self);
                var view = core.getComponentConfiguration(PID);
                assertNotNull(view);
                assertEquals("live-self-view", view.getConfigurationProperties().get("value"));
            }
            verify(core.bundles, times(2)).ungetService(managed);
            assertEquals(0, core.cmWrites.get());
            assertEquals(0, core.writes);
        }
    }

    @Test void unavailableReferenceStoredFallbackCannotReplaceLiveSelfView() throws Exception {
        try (var core = new RollbackConvergenceTest.Fixture(directory)) {
            var self = self(core);
            var unavailable = reference(core, null);
            for (boolean selfFirst : new boolean[] { true, false }) {
                order(core, selfFirst ? self : unavailable, selfFirst ? unavailable : self);
                assertEquals("live-self-view", core.getComponentConfiguration(PID).getConfigurationProperties().get("value"));
            }
            assertEquals("current", core.live.get(PID).get("value"));
            assertEquals(0, core.cmWrites.get());
        }
    }

    @Test void storedFallbackRemainsAvailableWhenNoSelfProviderCanBeAcquired() throws Exception {
        try (var core = new RollbackConvergenceTest.Fixture(directory)) {
            var unavailable = reference(core, null);
            var unrelated = reference(core, new Object());
            for (boolean unavailableFirst : new boolean[] { true, false }) {
                order(core, unavailableFirst ? unavailable : unrelated, unavailableFirst ? unrelated : unavailable);
                var view = core.getComponentConfiguration(PID);
                assertNotNull(view);
                assertEquals("current", view.getConfigurationProperties().get("value"));
            }
            assertEquals(0, core.cmWrites.get());
        }
    }

    @Test void invalidSelfProviderStillRejectsInsteadOfFallingBackOrUsingAnotherView() throws Exception {
        try (var core = new RollbackConvergenceTest.Fixture(directory)) {
            var self = self(core);
            var invalid = reference(core, (SelfConfiguringComponent) () -> null);
            var unavailable = reference(core, null);
            order(core, self, invalid, unavailable);
            assertNull(core.getComponentConfiguration(PID));
            order(core, unavailable, invalid, self);
            assertNull(core.getComponentConfiguration(PID));
            assertEquals(0, core.cmWrites.get());
        }
    }

    @Test void filteredConfigurationsReturnOneLogicalViewForMultipleMatchingRegistrations() throws Exception {
        try (var core = new RollbackConvergenceTest.Fixture(directory)) {
            var self = self(core);
            var managed = reference(core, (ManagedService) properties -> { fail("read dispatched an update"); });
            order(core, self, managed);
            ProviderPlanReadBudgetTest.field("bundleContext").set(core, core.bundles);
            when(core.bundles.getAllServiceReferences(null, null)).thenReturn(new ServiceReference<?>[] { self, managed });
            Filter filter = mock(Filter.class);
            when(filter.match(self)).thenReturn(true);
            when(filter.match(managed)).thenReturn(true);
            var result = core.getComponentConfigurations(filter);
            assertEquals(1, result.size());
            assertEquals(PID, result.get(0).getPid());
            assertEquals("live-self-view", result.get(0).getConfigurationProperties().get("value"));
            assertEquals(0, core.cmWrites.get());
        }
    }

    @Test void unmatchedRegistrationDoesNotHideLaterMatchingRegistrationWithSamePid() throws Exception {
        try (var core = new RollbackConvergenceTest.Fixture(directory)) {
            var self = self(core);
            var managed = reference(core, (ManagedService) properties -> {});
            order(core, managed, self);
            ProviderPlanReadBudgetTest.field("bundleContext").set(core, core.bundles);
            when(core.bundles.getAllServiceReferences(null, null)).thenReturn(new ServiceReference<?>[] { managed, self });
            Filter filter = mock(Filter.class);
            when(filter.match(managed)).thenReturn(false);
            when(filter.match(self)).thenReturn(true);
            var result = core.getComponentConfigurations(filter);
            assertEquals(1, result.size());
            assertEquals("live-self-view", result.get(0).getConfigurationProperties().get("value"));
        }
    }
}
