/* SPDX-License-Identifier: EPL-2.0 */
package org.eclipse.kura.core.configuration;

import org.eclipse.kura.configuration.*;
import org.eclipse.kura.configuration.ConfigurationRevisionService.*;

import java.util.*;

/** Detached input; receipt metadata deliberately contains no property values or tokens. */
final class RecordedConfigurationPlan {
    final List<ComponentConfiguration> updates;
    final List<Creation> creations;
    final Set<String> deletions;
    final Map<String, String> guards;
    final DeletionGuard deletionGuard;
    final Map<String, String> createdFactories;
    final Set<String> updatedPids;
    final Set<String> scope;

    RecordedConfigurationPlan(
            List<ComponentConfiguration> updates,
            List<Creation> creations,
            Set<String> deletions,
            Map<String, String> guards,
            DeletionGuard deletionGuard)
            throws Rejected {
        if (updates == null
                || creations == null
                || deletions == null
                || guards == null
                || updates.size() + creations.size() + deletions.size() == 0
                || updates.size() + creations.size() + deletions.size() > 512
                || guards.size() > 512) throw invalid();
        this.updates = new ArrayList<>();
        this.creations = new ArrayList<>();
        this.deletions = new HashSet<>(deletions);
        this.guards = new HashMap<>(guards);
        this.updatedPids = new HashSet<>();
        this.createdFactories = new HashMap<>();
        this.scope = new HashSet<>();
        for (ComponentConfiguration value : new ArrayList<>(updates)) {
            if (value == null) throw invalid();
            String pid = pid(value.getPid());
            if (!updatedPids.add(pid)) throw invalid();
            this.updates.add(
                    new ComponentConfigurationImpl(
                            pid,
                            null,
                            ConfigurationRevision.copyEditProperties(
                                    value.getConfigurationProperties())));
        }
        for (Creation value : new ArrayList<>(creations)) {
            if (value == null) throw invalid();
            String pid = pid(value.pid()), factory = pid(value.factoryPid());
            if (createdFactories.put(pid, factory) != null) throw invalid();
            this.creations.add(
                    new Creation(
                            factory,
                            pid,
                            ConfigurationRevision.copyEditProperties(value.properties())));
        }
        for (String value : this.deletions) pid(value);
        for (var entry : this.guards.entrySet()) {
            pid(entry.getKey());
            if (entry.getValue() == null || !entry.getValue().matches("[0-9a-f]{64}"))
                throw invalid();
        }
        this.scope.addAll(this.guards.keySet());
        this.scope.addAll(this.updatedPids);
        this.scope.addAll(this.deletions);
        this.scope.addAll(this.createdFactories.keySet());
        if (this.scope.size() > 1024) throw invalid();
        if (deletionGuard == null) this.deletionGuard = null;
        else {
            var factories = deletionGuard.factoryPids();
            var references = deletionGuard.pidReferenceProperties();
            if (factories == null || references == null) throw invalid();
            this.deletionGuard = new DeletionGuard(factories, references);
        }
    }

    static String pid(String value) throws Rejected {
        if (value == null
                || value.isBlank()
                || value.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 512
                || value.codePoints().anyMatch(Character::isISOControl)) throw invalid();
        return value;
    }

    private static Rejected invalid() {
        return new Rejected(Reason.INVALID_ARGUMENT);
    }
}
