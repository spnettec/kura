/*******************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 *
 * This program and the accompanying materials are made
 * available under the terms of the Eclipse Public License 2.0
 * which is available at https://www.eclipse.org/legal/epl-2.0/
 *
 * SPDX-License-Identifier: EPL-2.0
 ******************************************************************************/
package org.eclipse.kura.core.configuration;

import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import org.eclipse.kura.KuraErrorCode;
import org.eclipse.kura.KuraException;
import org.eclipse.kura.configuration.ComponentConfiguration;
import org.eclipse.kura.configuration.ExternalConfigurationHandler;
import org.eclipse.kura.configuration.ExternalConfigurationHandler.ChangeSource;
import org.eclipse.kura.configuration.metatype.OCD;
import org.osgi.service.cm.ConfigurationAdmin;

/** Keeps ownership reservations after a service disappears, so writes fail closed. */
final class ExternalConfigurations {
    static final String RESERVED_PIDS_PROPERTY = "kura.configuration.external.pids";

    private final Set<String> reserved = new TreeSet<>();
    private final Map<String, List<ExternalConfigurationHandler>> handlers = new HashMap<>();

    ExternalConfigurations(String configuredPids) {
        for (String pid : configuredPids.split(",")) {
            if (!pid.isBlank()) {
                this.reserved.add(pid.trim());
            }
        }
    }

    synchronized void bind(ExternalConfigurationHandler handler) {
        String pid = handler.getPid();
        if (pid == null || pid.isBlank()) {
            throw new IllegalArgumentException("External configuration PID is required");
        }
        if (!this.reserved.contains(pid)) {
            throw new IllegalStateException("External configuration PID was not reserved at startup: " + pid);
        }
        List<ExternalConfigurationHandler> values = this.handlers.computeIfAbsent(pid, key -> new ArrayList<>());
        if (values.stream().noneMatch(value -> value == handler)) {
            values.add(handler);
        }
    }

    synchronized void unbind(ExternalConfigurationHandler handler) {
        this.handlers.values().forEach(values -> values.removeIf(value -> value == handler));
    }

    synchronized boolean owns(String pid) {
        return pid != null && this.reserved.contains(pid);
    }

    boolean hasReservations() {
        return !this.reserved.isEmpty();
    }

    private synchronized Set<String> pids() {
        return new TreeSet<>(this.reserved);
    }

    private synchronized ExternalConfigurationHandler require(String pid) throws KuraException {
        List<ExternalConfigurationHandler> values = this.handlers.get(pid);
        if (values == null || values.size() != 1) {
            throw failure(pid, "EXTERNAL_CONFIGURATION_NOT_READY_OR_AMBIGUOUS");
        }
        return values.get(0);
    }

    ComponentConfiguration confirmed(String pid) throws KuraException {
        ComponentConfiguration result = require(pid).getConfirmedConfiguration();
        if (result == null || !pid.equals(result.getPid()) || result.getConfigurationProperties() == null) {
            throw failure(pid, "INVALID_CONFIRMED_CONFIGURATION");
        }
        Map<String, Object> properties = new HashMap<>(result.getConfigurationProperties());
        return new ComponentConfiguration() {
            @Override
            public String getPid() { return pid; }
            @Override
            public OCD getDefinition() { return result.getDefinition(); }
            @Override
            public OCD getLocalizedDefinition(String locale) { return result.getLocalizedDefinition(locale); }
            @Override
            public Map<String, Object> getConfigurationProperties() { return properties; }
        };
    }

    void validate(Collection<? extends ComponentConfiguration> requests, ChangeSource source) throws KuraException {
        Set<String> seen = new HashSet<>();
        for (ComponentConfiguration request : requests) {
            if (request != null && owns(request.getPid())) {
                String pid = request.getPid();
                if (!seen.add(pid) || request.getConfigurationProperties() == null
                        || request.getConfigurationProperties().containsKey(ConfigurationAdmin.SERVICE_FACTORYPID)) {
                    throw failure(pid, "INVALID_EXTERNAL_CONFIGURATION_REQUEST");
                }
                require(pid).validateConfiguration(new HashMap<>(request.getConfigurationProperties()), source);
            }
        }
        if (source == ChangeSource.SNAPSHOT_ROLLBACK && !seen.containsAll(pids())) {
            throw failure(String.join(",", pids()), "SNAPSHOT_OMITS_EXTERNAL_CONFIGURATION");
        }
    }

    void apply(Collection<? extends ComponentConfiguration> requests, ChangeSource source) throws KuraException {
        for (ComponentConfiguration request : requests) {
            if (request != null && owns(request.getPid())) {
                Map<String, Object> properties = new HashMap<>();
                if (source == ChangeSource.CONFIGURATION_UPDATE) {
                    properties.putAll(confirmed(request.getPid()).getConfigurationProperties());
                }
                properties.putAll(request.getConfigurationProperties());
                require(request.getPid()).applyConfiguration(properties, source);
            }
        }
    }

    List<ComponentConfiguration> snapshot(Collection<? extends ComponentConfiguration> configurations)
            throws KuraException {
        List<ComponentConfiguration> result = new ArrayList<>();
        for (ComponentConfiguration configuration : configurations) {
            if (!owns(configuration.getPid())) {
                result.add(configuration);
            }
        }
        for (String pid : pids()) {
            result.add(confirmed(pid));
        }
        return result;
    }

    void rejectFactoryOperation(String pid) throws KuraException {
        if (owns(pid)) {
            throw failure(pid, "EXTERNAL_CONFIGURATION_IS_NOT_A_FACTORY");
        }
    }

    private static KuraException failure(String pid, String reason) {
        return new KuraException(KuraErrorCode.CONFIGURATION_UPDATE, pid + ": " + reason);
    }
}
