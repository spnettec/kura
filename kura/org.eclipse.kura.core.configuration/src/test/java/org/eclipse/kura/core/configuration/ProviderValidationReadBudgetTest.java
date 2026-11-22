/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.*;
import org.eclipse.kura.core.configuration.metatype.Tocd;
import org.junit.jupiter.api.Test;
import org.osgi.service.metatype.AttributeDefinition;

class ProviderValidationReadBudgetTest {
    static class Fixture extends ProviderPlanReadBudgetTest.Fixture {
        boolean armValidation, readAfterDispatch;
        Fixture() throws Exception {
            var metadata = new ProviderDefinitionTest();
            @SuppressWarnings("unchecked") var definitions = (Map<String,Tocd>) ProviderPlanReadBudgetTest.field("ocds").get(this);
            for (String pid : List.of("first.provider", "second.provider")) {
                definitions.put(pid, new ProviderDefinition(new ProviderDefinition.Source(metadata.provider(
                        metadata.attribute("value", AttributeDefinition.STRING, 0, "original"))), pid));
            }
        }
        @Override public Set<String> getFactoryComponentPids() {
            if (armValidation) slow.set(true);
            return Set.of();
        }
        @Override public synchronized void updateConfigurations(List<ComponentConfiguration> configs, boolean snapshot)
                throws KuraException {
            writes++;
            if (readAfterDispatch) {
                try { Thread.sleep(200); } catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
                assertNotNull(getComponentConfiguration("second.provider"));
            }
        }
        void untouched() throws Exception {
            assertEquals(0, writes);
            assertTrue(((Map<?,?>) ProviderPlanReadBudgetTest.field("revisionAdmissions").get(this)).isEmpty());
            assertTrue(((Set<?>) ProviderPlanReadBudgetTest.field("revisionUncertain").get(this)).isEmpty());
        }
    }
    @Test void validationOfMultipleProvidersSharesOneReadBudgetBeforeAdmission() throws Exception {
        try (var core = new Fixture()) {
            var guards = core.baseline(); core.armValidation = true;
            var updates = List.<ComponentConfiguration>of(ProviderPlanReadBudgetTest.update(),
                    new ComponentConfigurationImpl("second.provider", null, new HashMap<>(Map.of("value", "changed"))));
            var rejection = assertThrows(ConfigurationRevisionService.Rejected.class, () ->
                    core.applyConfigurationPlanIfUnchanged(updates, List.of(), Set.of(), guards));
            assertEquals(ConfigurationRevisionService.Reason.CONFLICT, rejection.getReason()); core.untouched();
        }
    }
    @Test void aDispatchedWriterDoesNotInheritTheSpentValidationReadBudget() throws Exception {
        try (var core = new Fixture()) {
            var guards = Map.of("first.provider", core.readRevision("first.provider").revision());
            core.armValidation = true; core.readAfterDispatch = true;
            core.applyConfigurationPlanIfUnchanged(List.of(ProviderPlanReadBudgetTest.update()), List.of(), Set.of(), guards);
            assertEquals(1, core.writes);
            assertTrue(((Set<?>) ProviderPlanReadBudgetTest.field("revisionUncertain").get(core)).isEmpty());
        }
    }
}
