/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.*;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.junit.jupiter.api.Test;
import org.osgi.service.cm.ConfigurationAdmin;
import org.osgi.service.component.runtime.ServiceComponentRuntime;

class ProviderDeletionReadBudgetTest {
    static final String TARGET = "owned.deletion", FACTORY = "owned.factory";
    static class Fixture extends ProviderPlanReadBudgetTest.Fixture {
        int deletions, snapshots;
        Fixture() throws Exception {
            ProviderPlanReadBudgetTest.field("bundleContext").set(this, bundles);
            var scr = mock(ServiceComponentRuntime.class);
            when(scr.getComponentDescriptionDTOs()).thenReturn(List.of()); setScrService(scr);
            setConfigurationAdmin(mock(ConfigurationAdmin.class));
            @SuppressWarnings("unchecked") var factories = (Map<String,String>) ProviderPlanReadBudgetTest.field("factoryPidByPid").get(this);
            factories.put(TARGET, FACTORY);
        }
        @Override public synchronized ComponentConfiguration getComponentConfiguration(String pid) throws KuraException {
            if (!TARGET.equals(pid)) return super.getComponentConfiguration(pid);
            var definition = new Tocd(); definition.setId(pid);
            return new ComponentConfigurationImpl(pid, definition, new HashMap<>(Map.of("service.factoryPid", FACTORY)));
        }
        @Override public synchronized void deleteFactoryConfiguration(String pid, boolean snapshot) {
            assertEquals(TARGET, pid); assertFalse(snapshot); deletions++;
        }
        @Override public synchronized long snapshot() { return ++snapshots; }
        void delete(String revision) throws KuraException {
            applyConfigurationPlanIfUnchanged(List.of(), List.of(), Set.of(TARGET), Map.of(TARGET, revision),
                    new ConfigurationRevisionService.DeletionGuard(Map.of(TARGET, FACTORY), Set.of()));
        }
        void untouched() throws Exception {
            assertEquals(0, deletions); assertEquals(0, snapshots); assertEquals(0, writes);
            assertTrue(((Map<?, ?>) ProviderPlanReadBudgetTest.field("revisionAdmissions").get(this)).isEmpty());
            assertTrue(((Set<?>) ProviderPlanReadBudgetTest.field("revisionUncertain").get(this)).isEmpty());
        }
    }
    @Test void publicViewsShareOneBudgetBeforeDeletionAdmission() throws Exception {
        try (var core = new Fixture()) {
            String revision = core.readRevision(TARGET).revision(); core.slow.set(true);
            var rejection = assertThrows(ConfigurationRevisionService.Rejected.class, () -> core.delete(revision));
            assertEquals(ConfigurationRevisionService.Reason.CONFLICT, rejection.getReason()); core.untouched();
        }
    }
    @Test void unavailablePublicViewsAreConflictsBeforeAnyDeletionDispatch() throws Exception {
        try (var core = new Fixture()) {
            String revision = core.readRevision(TARGET).revision(); core.reads.close();
            var rejection = assertThrows(ConfigurationRevisionService.Rejected.class, () -> core.delete(revision));
            assertEquals(ConfigurationRevisionService.Reason.CONFLICT, rejection.getReason()); core.untouched();
        }
    }
    @Test void availablePublicViewsStillAllowOneDeletionAndOneSnapshot() throws Exception {
        try (var core = new Fixture()) {
            core.delete(core.readRevision(TARGET).revision());
            assertEquals(1, core.deletions); assertEquals(1, core.snapshots);
        }
    }
}
