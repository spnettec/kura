/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.*;
import org.junit.jupiter.api.Test;

class ConditionalWriteOutcomeTest {
    static final String PID = "fixture.revision";
    static class Single extends ConfigurationServiceImpl {
        final Map<String,Object> values = new HashMap<>(Map.of("name", "initial"));
        final Throwable failure;
        int writes;
        Single(Throwable failure) { this.failure = failure; }
        @Override public ComponentConfiguration getComponentConfiguration(String pid) {
            return ConfigurationRevisionTest.component(values);
        }
        @Override protected boolean revisionTargetTracked(String pid) { return true; }
        @Override public synchronized void updateConfiguration(String pid, Map<String,Object> patch, boolean snapshot)
                throws KuraException {
            writes++; values.putAll(patch);
            if (failure instanceof KuraException kura) throw kura;
            if (failure instanceof RuntimeException runtime) throw runtime;
            if (failure instanceof Error error) throw error;
        }
        void assertUncertain() throws Exception {
            assertEquals(1, writes); assertEquals("written", values.get("name"));
            assertTrue(((Set<?>) ProviderPlanReadBudgetTest.field("revisionUncertain").get(this)).contains(PID));
            assertEquals(1L, ((Map<?,?>) ProviderPlanReadBudgetTest.field("revisionAdmissions").get(this)).get(PID));
            assertEquals(ConfigurationRevisionService.Reason.CONFLICT,
                    assertThrows(ConfigurationRevisionService.Rejected.class, () -> readRevision(PID)).getReason());
        }
        void write() throws KuraException { updateRevision(PID, readRevision(PID).revision(), Map.of("name", "written")); }
    }
    @Test void aRejectedFromAnEnteredSingleWriterIsNotAdvertisedAsAPreAdmissionRejection() throws Exception {
        var rejection = new ConfigurationRevisionService.Rejected(ConfigurationRevisionService.Reason.INVALID_ARGUMENT);
        var core = new Single(rejection);
        KuraException failure = assertThrows(KuraException.class, core::write);
        assertFalse(failure instanceof ConfigurationRevisionService.Rejected);
        assertSame(rejection, failure.getCause()); core.assertUncertain();
    }
    @Test void aRuntimeFailureFromAnEnteredSingleWriterHasAnExplicitUncertainOutcome() throws Exception {
        var original = new IllegalStateException("after mutation"); var core = new Single(original);
        KuraException failure = assertThrows(KuraException.class, core::write);
        assertSame(original, failure.getCause()); core.assertUncertain();
    }
    @Test void aFatalFailureStillWithholdsTheSingleTargetsRevisionBeforePropagating() throws Exception {
        var original = new AssertionError("after mutation"); var core = new Single(original);
        assertSame(original, assertThrows(AssertionError.class, core::write)); core.assertUncertain();
    }
    @Test void aFatalBatchFailureStillWithholdsAllAdmittedRevisionsBeforePropagating() throws Exception {
        var original = new AssertionError("after batch mutation");
        class Batch extends ConfigurationPlanAdmissionTest.Fixture {
            Batch() throws Exception { }
            @Override public synchronized void updateConfigurations(List<ComponentConfiguration> configurations, boolean snapshot) {
                super.updateConfigurations(configurations, snapshot); throw original;
            }
        }
        var core = new Batch(); var baseline = core.baseline();
        var updates = List.<ComponentConfiguration>of(
                new ComponentConfigurationImpl(ConfigurationPlanAdmissionTest.FIRST, null, Map.of("name", "changed-first")),
                new ComponentConfigurationImpl(ConfigurationPlanAdmissionTest.SECOND, null, Map.of("name", "changed-second")));
        assertSame(original, assertThrows(AssertionError.class, () -> core.updateConfigurationsIfUnchanged(updates, baseline)));
        assertEquals(2, core.dispatched.size());
        for (String pid : baseline.keySet()) {
            assertTrue(((Set<?>) ProviderPlanReadBudgetTest.field("revisionUncertain").get(core)).contains(pid));
            assertEquals(ConfigurationRevisionService.Reason.CONFLICT,
                    assertThrows(ConfigurationRevisionService.Rejected.class, () -> core.readRevision(pid)).getReason());
        }
    }
}
